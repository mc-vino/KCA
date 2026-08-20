"""Юнит-тесты стадии RECONCILE — §5.6."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from cashforensics.models import (
    Category,
    ClassifyResult,
    Config,
    LedgerEntry,
    OpsClass,
    OpsEntry,
    OpsKind,
    ReversalResult,
)
from cashforensics.reconcile import (
    RECONCILED_CATEGORIES,
    daily_differences,
    daily_ledger_series,
    daily_ops_series,
    log_imbalance,
    outside_ledger_period,
    reconcile,
    within_ledger_period,
)
from tests.unit.test_classify import ledger_entry, ops_entry

pytestmark = pytest.mark.unit

ZERO = Decimal("0.00")


def _classified(
    ledger: tuple[LedgerEntry, ...] = (),
    ops: tuple[OpsEntry, ...] = (),
) -> ClassifyResult:
    """Выход §5.4 для теста."""
    return ClassifyResult(ledger=ledger, ops=ops, fallback=None, unknown_accounts=())


def _no_reversals() -> ReversalResult:
    return ReversalResult(neutralized_rows=frozenset(), findings=(), audit_log=())


def _income(row: int, day: date, amount: Decimal) -> LedgerEntry:
    """Проводка прихода — §5.4: только продажи и авансы."""
    return ledger_entry(
        row=row,
        day=day,
        debit=amount,
        account="90.1.1",
        category=Category.INCOME,
    )


def _refund_posting(row: int, day: date, amount: Decimal) -> LedgerEntry:
    """Проводка возврата — §3.5."""
    return ledger_entry(
        row=row,
        day=day,
        credit=amount,
        account="76.9.1",
        category=Category.REFUND,
    )


def _ops(
    row: int,
    moment: datetime,
    amount: Decimal,
    cls: OpsClass,
    kind: OpsKind = OpsKind.RKO,
) -> OpsEntry:
    """Классифицированная запись опер-лога — §3.6."""
    return ops_entry(row=row, moment=moment, amount=amount, kind=kind).model_copy(
        update={"classification": cls, "classified_by": "counterparty"},
    )


class TestDailySeries:
    """§5.6: дневные ряды 1С и опер-лога."""

    def test_ledger_series_sums_by_day(self) -> None:
        ledger = (
            _income(1, date(2024, 2, 1), Decimal("100.00")),
            _income(2, date(2024, 2, 1), Decimal("50.00")),
            _income(3, date(2024, 2, 2), Decimal("70.00")),
        )

        series = daily_ledger_series(ledger, Category.INCOME, frozenset())

        assert series == {date(2024, 2, 1): Decimal("150.00"), date(2024, 2, 2): Decimal("70.00")}

    def test_neutralized_rows_are_excluded(self) -> None:
        """§5.6: ряд строится без нейтрализованных §5.5."""
        ledger = (
            _income(1, date(2024, 2, 1), Decimal("100.00")),
            _income(2, date(2024, 2, 1), Decimal("50.00")),
        )

        series = daily_ledger_series(ledger, Category.INCOME, frozenset({2}))

        assert series == {date(2024, 2, 1): Decimal("100.00")}

    def test_service_included_as_is_excluded_when_adjusted(self) -> None:
        """§5.6: возвраты в двух вариантах — «как есть» и «скорректировано»."""
        ops = (
            _ops(1, datetime(2024, 2, 1, 10, 0, 0), Decimal("200.00"), OpsClass.REFUND),
            _ops(2, datetime(2024, 2, 1, 11, 0, 0), Decimal("150.00"), OpsClass.SERVICE),
        )

        as_is = daily_ops_series(ops, Category.REFUND, exclude_service=False)
        adjusted = daily_ops_series(ops, Category.REFUND, exclude_service=True)

        assert as_is == {date(2024, 2, 1): Decimal("350.00")}
        assert adjusted == {date(2024, 2, 1): Decimal("200.00")}

    def test_differences_are_sorted_and_skip_zeros(self) -> None:
        acc = {date(2024, 2, 2): Decimal("70.00"), date(2024, 2, 1): Decimal("100.00")}
        ops = {date(2024, 2, 1): Decimal("100.00"), date(2024, 2, 3): Decimal("5.00")}

        result = daily_differences(acc, ops)

        assert result == (
            (date(2024, 2, 2), Decimal("70.00")),
            (date(2024, 2, 3), Decimal("-5.00")),
        )


class TestCategoryReconciliation:
    """§5.6: нетто, брутто, ratio."""

    def test_net_and_gross(self, config: Config) -> None:
        ledger = (
            _income(1, date(2024, 2, 1), Decimal("100.00")),
            _income(2, date(2024, 2, 2), Decimal("100.00")),
        )
        ops = (
            _ops(
                10, datetime(2024, 2, 1, 10, 0, 0), Decimal("90.00"), OpsClass.INCOME, OpsKind.PKO
            ),
            _ops(
                11, datetime(2024, 2, 2, 10, 0, 0), Decimal("110.00"), OpsClass.INCOME, OpsKind.PKO
            ),
        )

        recon = reconcile(_classified(ledger, ops), _no_reversals(), config)[Category.INCOME]

        assert recon.net == ZERO
        assert recon.gross == Decimal("20.00")

    def test_ratio_zero_means_pure_churn(self, config: Config) -> None:
        """§5.6: ratio 0 → встречные потоки, 1 → односторонний сдвиг."""
        ledger = (
            _income(1, date(2024, 2, 1), Decimal("100.00")),
            _income(2, date(2024, 2, 2), Decimal("100.00")),
        )
        ops = (
            _ops(
                10, datetime(2024, 2, 1, 10, 0, 0), Decimal("90.00"), OpsClass.INCOME, OpsKind.PKO
            ),
            _ops(
                11, datetime(2024, 2, 2, 10, 0, 0), Decimal("110.00"), OpsClass.INCOME, OpsKind.PKO
            ),
        )

        recon = reconcile(_classified(ledger, ops), _no_reversals(), config)[Category.INCOME]

        assert recon.ratio == 0.0

    def test_ratio_one_means_one_sided_shift(self, config: Config) -> None:
        ledger = (_income(1, date(2024, 2, 1), Decimal("100.00")),)
        ops = ()

        recon = reconcile(_classified(ledger, ops), _no_reversals(), config)[Category.INCOME]

        assert recon.ratio == 1.0

    def test_ratio_is_none_when_no_differences(self, config: Config) -> None:
        ledger = (_income(1, date(2024, 2, 1), Decimal("100.00")),)
        ops = (
            _ops(
                10, datetime(2024, 2, 1, 10, 0, 0), Decimal("100.00"), OpsClass.INCOME, OpsKind.PKO
            ),
        )

        recon = reconcile(_classified(ledger, ops), _no_reversals(), config)[Category.INCOME]

        assert recon.ratio is None

    def test_adjusted_refunds_measure_the_phantom_gap(self, config: Config) -> None:
        """§3.6, §5.6: разница вариантов и есть мера мнимого расхождения.

        На Солигорске служебные РКО давали мнимое расхождение 11 610,00
        (судебная выплата 11 310,00 + АРХИВ ПВЗ 150,00 + Финконтроль 150,00).
        """
        ledger = (_refund_posting(1, date(2024, 2, 1), Decimal("200.00")),)
        ops = (
            _ops(10, datetime(2024, 2, 1, 10, 0, 0), Decimal("200.00"), OpsClass.REFUND),
            _ops(11, datetime(2024, 2, 1, 11, 0, 0), Decimal("11310.00"), OpsClass.SERVICE),
            _ops(12, datetime(2024, 2, 1, 12, 0, 0), Decimal("150.00"), OpsClass.SERVICE),
            _ops(13, datetime(2024, 2, 1, 13, 0, 0), Decimal("150.00"), OpsClass.SERVICE),
        )

        recon = reconcile(_classified(ledger, ops), _no_reversals(), config)[Category.REFUND]

        assert recon.net == Decimal("-11610.00")
        assert recon.adjusted_net == ZERO

    def test_reconciled_series_excludes_service(self, config: Config) -> None:
        """§3.6: сверка ведётся по «скорректированному» ряду, а не «как есть».

        Ловушка, стоившая пяти ложных дней на Солигорске: §5.7 сворачивала ряд
        «как есть», а §5.9 разбирала день по «скорректированному». День, попавший
        в остаток только из-за судебной выплаты, приходил в локализацию с нулевой
        разницей и оседал в отчёте строкой «не локализовано» на 0,00.
        """
        ledger = (_refund_posting(1, date(2024, 2, 1), Decimal("200.00")),)
        ops = (
            _ops(10, datetime(2024, 2, 1, 10, 0, 0), Decimal("200.00"), OpsClass.REFUND),
            _ops(11, datetime(2024, 2, 1, 11, 0, 0), Decimal("11310.00"), OpsClass.SERVICE),
        )

        recon = reconcile(_classified(ledger, ops), _no_reversals(), config)[Category.REFUND]

        assert recon.daily_differences == ()
        assert recon.reconciled_ops_series() == ((date(2024, 2, 1), Decimal("200.00")),)
        assert recon.ops_series == ((date(2024, 2, 1), Decimal("11510.00")),)

    def test_reconciled_series_is_the_raw_one_outside_refunds(self, config: Config) -> None:
        ledger = (_income(1, date(2024, 2, 1), Decimal("100.00")),)

        recon = reconcile(_classified(ledger), _no_reversals(), config)[Category.INCOME]

        assert recon.ops_series_adjusted is None
        assert recon.reconciled_ops_series() == recon.ops_series

    def test_adjusted_is_none_for_non_refund_categories(self, config: Config) -> None:
        ledger = (_income(1, date(2024, 2, 1), Decimal("100.00")),)

        recon = reconcile(_classified(ledger), _no_reversals(), config)[Category.INCOME]

        assert recon.adjusted_net is None

    def test_days_with_difference_uses_eps_floor(self, config: Config) -> None:
        """Копеечные расхождения — не «дни расхождения» (§5.7.2)."""
        ledger = (
            _income(1, date(2024, 2, 1), Decimal("100.00")),
            _income(2, date(2024, 2, 2), Decimal("100.00")),
        )
        ops = (
            _ops(
                10, datetime(2024, 2, 1, 10, 0, 0), Decimal("99.60"), OpsClass.INCOME, OpsKind.PKO
            ),
            _ops(
                11, datetime(2024, 2, 2, 10, 0, 0), Decimal("50.00"), OpsClass.INCOME, OpsKind.PKO
            ),
        )

        recon = reconcile(_classified(ledger, ops), _no_reversals(), config)[Category.INCOME]

        assert recon.days_with_difference == 1

    def test_all_three_categories_present(self, config: Config) -> None:
        result = reconcile(_classified(), _no_reversals(), config)

        assert tuple(result) == RECONCILED_CATEGORIES


class TestLogImbalance:
    """§5.10: логи сами не сходятся — отдельная строка, не расхождение 1С."""

    def test_imbalance_subtracts_all_payouts_including_service(self) -> None:
        """Служебные РКО вычитаются: деньги из ящика вышли — §5.10.

        Показатель меряет физическую сходимость лога, а не сверку возвратов.
        Исключение служебных из §3.6 сюда не переносится.
        """
        ops = (
            _ops(
                1, datetime(2024, 2, 1, 9, 0, 0), Decimal("1000.00"), OpsClass.INCOME, OpsKind.PKO
            ),
            _ops(2, datetime(2024, 2, 1, 10, 0, 0), Decimal("600.00"), OpsClass.COLLECTION),
            _ops(3, datetime(2024, 2, 1, 11, 0, 0), Decimal("200.00"), OpsClass.REFUND),
            _ops(4, datetime(2024, 2, 1, 12, 0, 0), Decimal("150.00"), OpsClass.SERVICE),
        )

        assert log_imbalance(ops) == Decimal("50.00")

    def test_soligorsk_reference_totals(self) -> None:
        """Эталон §11.3: дисбаланс логов Солигорска = −807,91.

        Агрегаты реальной кассы PAX_119011650. Без вычета служебных 11 610,00
        получалось +10 802,09 — ошибка чтения формулы §5.10, найденная прогоном
        на реальном файле.
        """
        ops = (
            _ops(
                1,
                datetime(2024, 2, 1, 9, 0, 0),
                Decimal("14062584.98"),
                OpsClass.INCOME,
                OpsKind.PKO,
            ),
            _ops(2, datetime(2024, 2, 1, 10, 0, 0), Decimal("12977844.10"), OpsClass.COLLECTION),
            _ops(3, datetime(2024, 2, 1, 11, 0, 0), Decimal("1073938.79"), OpsClass.REFUND),
            _ops(4, datetime(2024, 2, 1, 12, 0, 0), Decimal("11610.00"), OpsClass.SERVICE),
        )

        assert log_imbalance(ops) == Decimal("-807.91")

    def test_balanced_log_gives_zero(self) -> None:
        ops = (
            _ops(1, datetime(2024, 2, 1, 9, 0, 0), Decimal("800.00"), OpsClass.INCOME, OpsKind.PKO),
            _ops(2, datetime(2024, 2, 1, 10, 0, 0), Decimal("600.00"), OpsClass.COLLECTION),
            _ops(3, datetime(2024, 2, 1, 11, 0, 0), Decimal("200.00"), OpsClass.REFUND),
        )

        assert log_imbalance(ops) == ZERO


class TestLedgerPeriodClip:
    """§5.6, §5.3: сверять можно только там, где есть обе стороны."""

    @staticmethod
    def _register() -> tuple[tuple[LedgerEntry, ...], tuple[OpsEntry, ...]]:
        """Карточка до 02.02, лог до 05.02 — типовой срез выгрузки."""
        ledger = (
            _income(1, date(2024, 2, 1), Decimal("300.00")),
            _refund_posting(2, date(2024, 2, 2), Decimal("100.00")),
        )
        ops = (
            _ops(10, datetime(2024, 2, 2, 12, 0), Decimal("100.00"), OpsClass.REFUND),
            _ops(11, datetime(2024, 2, 5, 12, 0), Decimal("777.00"), OpsClass.REFUND),
        )
        return (ledger, ops)

    def test_records_past_the_last_posting_are_dropped(self) -> None:
        """За последней проводкой карточки отсутствует вся вторая сторона.

        `Кса_норма` — эталон §11.3 «без ошибок» — имеет карточку до 30.04.2026 и
        лог до 02.06.2026, и §5.6 сравнивала пять недель 1С против десяти недель
        лога: инкассация 269 243,54 против 587 835,72 при отклонении сальдо
        +10 632,25.
        """
        ledger, ops = self._register()

        inside = within_ledger_period(ops, ledger)

        assert [entry.row for entry in inside] == [10]

    def test_dropped_amount_is_reported_not_swallowed(self) -> None:
        """§5: тихих пропусков нет — величина идёт в оговорки §16."""
        ledger, ops = self._register()

        assert outside_ledger_period(ops, ledger, Category.REFUND) == Decimal("777.00")

    def test_clip_makes_the_category_net_meaningful(self, config: Config) -> None:
        """Со срезом нетто категории перестаёт быть артефактом выгрузки."""
        ledger, ops = self._register()

        recon = reconcile(_classified(ledger, ops), _no_reversals(), config)

        assert recon[Category.REFUND].net == ZERO
        assert recon[Category.REFUND].outside_period == Decimal("777.00")

    def test_empty_ledger_clips_nothing(self) -> None:
        """Без проводок границы нет — отбрасывать по ней нельзя."""
        _, ops = self._register()

        assert len(within_ledger_period(ops, ())) == len(ops)
