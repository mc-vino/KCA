"""Юнит-тесты стадий BALANCE_TRACE §5.8 и DECOMPOSE §5.10."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from cashforensics.balance import (
    balance_trace,
    cash_floor_points,
    check_nonnegativity,
    daily_closing_balances,
    detect_level_shift_pelt,
    is_full_sweep,
    localize_shift_window,
    running_balance,
    target_balance_at,
)
from cashforensics.decompose import build_waterfall, check_tie, decompose, other_flows
from cashforensics.models import (
    Category,
    CategoryRecon,
    ClassifyResult,
    Config,
    LedgerEntry,
    OpsClass,
    OpsEntry,
    TargetBalanceRule,
)
from tests.unit.test_classify import ledger_entry, ops_entry

pytestmark = pytest.mark.unit

ZERO = Decimal("0.00")
START = date(2024, 2, 1)


def _day(offset: int) -> date:
    return START + timedelta(days=offset)


def _income(row: int, day: date, amount: Decimal) -> LedgerEntry:
    return ledger_entry(
        row=row,
        day=day,
        debit=amount,
        account="90.1.1",
        category=Category.INCOME,
    )


def _collection(row: int, day: date, amount: Decimal) -> LedgerEntry:
    return ledger_entry(
        row=row,
        day=day,
        credit=amount,
        account="51",
        category=Category.COLLECTION,
    )


def _refund(row: int, day: date, amount: Decimal) -> LedgerEntry:
    return ledger_entry(
        row=row,
        day=day,
        credit=amount,
        account="76.9.1",
        category=Category.REFUND,
    )


def _classified(
    ledger: tuple[LedgerEntry, ...] = (),
    ops: tuple[OpsEntry, ...] = (),
) -> ClassifyResult:
    return ClassifyResult(ledger=ledger, ops=ops, fallback=None, unknown_accounts=())


def _recon(category: Category, net: Decimal) -> CategoryRecon:
    return CategoryRecon(
        category=category,
        acc_total=ZERO,
        ops_total=ZERO,
        net=net,
        gross=ZERO,
        ratio=None,
        days_with_difference=0,
        acc_series=(),
        ops_series=(),
        daily_differences=(),
        adjusted_net=None,
        adjusted_gross=None,
    )


class TestRunningBalance:
    """§5.8.1: нарастающее сальдо."""

    def test_accumulates_in_date_row_order(self) -> None:
        ledger = (
            _collection(2, _day(0), Decimal("40.00")),
            _income(1, _day(0), Decimal("100.00")),
            _income(3, _day(1), Decimal("10.00")),
        )

        result = running_balance(ledger, ZERO)

        assert [entry.running_balance for entry in result] == [
            Decimal("100.00"),
            Decimal("60.00"),
            Decimal("70.00"),
        ]

    def test_does_not_mutate_input(self) -> None:
        """§5: стадии не мутируют вход."""
        ledger = (_income(1, _day(0), Decimal("100.00")),)

        running_balance(ledger, ZERO)

        assert ledger[0].running_balance == ZERO

    def test_opening_is_the_starting_point(self) -> None:
        ledger = (_income(1, _day(0), Decimal("100.00")),)

        result = running_balance(ledger, Decimal("500.00"))

        assert result[0].running_balance == Decimal("600.00")


class TestNonNegativity:
    """§5.8.2: инвариант неотрицательности."""

    def test_dates_the_first_minus(self, config: Config) -> None:
        """На PAX_119023531 инвариант сработал как датировщик проблемного дня."""
        ledger = running_balance(
            (
                _income(1, _day(0), Decimal("100.00")),
                _refund(2, _day(1), Decimal("150.00")),
                _income(3, _day(2), Decimal("500.00")),
            ),
            ZERO,
        )

        report = check_nonnegativity(ledger, config)

        assert report.first_below_target == _day(1)
        assert report.minimum == Decimal("-50.00")
        assert report.minimum_date == _day(1)

    def test_never_recovered_marks_the_last_descent(self, config: Config) -> None:
        ledger = running_balance(
            (
                _income(1, _day(0), Decimal("100.00")),
                _refund(2, _day(1), Decimal("150.00")),
                _income(3, _day(2), Decimal("500.00")),
                _refund(4, _day(3), Decimal("600.00")),
            ),
            ZERO,
        )

        report = check_nonnegativity(ledger, config)

        assert report.never_recovered_after == _day(3)

    def test_clean_register_has_no_minus(self, config: Config) -> None:
        ledger = running_balance((_income(1, _day(0), Decimal("100.00")),), ZERO)

        report = check_nonnegativity(ledger, config)

        assert report.first_below_target is None
        assert report.share_of_days_below == 0.0

    def test_target_schedule_shifts_the_threshold(self, config: Config) -> None:
        """§13.8: инварианты пересчитываются относительно T."""
        raised = config.model_copy(update={"target_balance": Decimal("200.00")})
        ledger = running_balance((_income(1, _day(0), Decimal("100.00")),), ZERO)

        assert check_nonnegativity(ledger, config).first_below_target is None
        assert check_nonnegativity(ledger, raised).first_below_target == _day(0)

    def test_target_balance_at_uses_schedule(self, config: Config) -> None:
        """§6: фонд кассы мог меняться во времени."""
        scheduled = config.model_copy(
            update={
                "target_balance_schedule": (
                    TargetBalanceRule.model_validate({"from": _day(5), "value": "200.00"}),
                ),
            },
        )

        assert target_balance_at(_day(0), scheduled) == ZERO
        assert target_balance_at(_day(9), scheduled) == Decimal("200.00")


class TestCashFloor:
    """§5.8.3: пол кассы и фильтр полноты выемки."""

    def test_full_sweep_requires_ratio(self, config: Config) -> None:
        median = Decimal("1000.00")

        assert is_full_sweep(Decimal("600.00"), ZERO, median, config)
        assert not is_full_sweep(Decimal("259.47"), ZERO, median, config)

    def test_sweep_requires_zero_income(self, config: Config) -> None:
        assert not is_full_sweep(Decimal("600.00"), Decimal("1.00"), Decimal("1000.00"), config)

    def test_partial_sweeps_are_kept_but_flagged(self, config: Config) -> None:
        """§5.8.3: копеечная инкассация даёт бессмысленный пол — её надо метить.

        На PAX_119023531 две из четырёх точек — именно такие (259,47 и 310,61).
        """
        ledger = running_balance(
            (
                _income(1, _day(0), Decimal("1000.00")),
                _collection(2, _day(1), Decimal("900.00")),
                _income(3, _day(2), Decimal("1000.00")),
                _collection(4, _day(3), Decimal("259.47")),
            ),
            ZERO,
        )

        points = cash_floor_points(ledger, config)

        assert [point.is_full for point in points] == [True, False]
        assert points[1].collection == Decimal("259.47")

    def test_floor_is_the_end_of_day_balance(self, config: Config) -> None:
        ledger = running_balance(
            (
                _income(1, _day(0), Decimal("1000.00")),
                _collection(2, _day(1), Decimal("900.00")),
            ),
            ZERO,
        )

        points = cash_floor_points(ledger, config)

        assert points[0].floor == Decimal("100.00")

    def test_daily_closing_takes_last_posting_of_day(self) -> None:
        ledger = running_balance(
            (
                _income(1, _day(0), Decimal("100.00")),
                _income(2, _day(0), Decimal("50.00")),
            ),
            ZERO,
        )

        assert daily_closing_balances(ledger) == ((_day(0), Decimal("150.00")),)


class TestChangePoint:
    """§5.8.4: датирование смещения окном, а не точкой."""

    def test_level_shift_is_returned_as_window(self, config: Config) -> None:
        series = tuple(
            (_day(index), Decimal("0.00") if index < 30 else Decimal("-1200.00"))
            for index in range(60)
        )

        windows = detect_level_shift_pelt(series, config)

        assert windows
        window = windows[0]
        assert window.window[0] < window.window[1]
        assert window.window[0] <= _day(30) <= window.window[1]

    def test_short_series_yields_nothing(self, config: Config) -> None:
        """Окно шире самого ряда — отказ вместо выдуманной даты (§16)."""
        series = tuple((_day(index), Decimal("1.00")) for index in range(3))

        assert detect_level_shift_pelt(series, config) == ()

    def test_returns_dates_not_amounts(self, config: Config) -> None:
        """§10: наружу из детектора идут индексы и даты, не суммы."""
        series = tuple(
            (_day(index), Decimal("0.00") if index < 30 else Decimal("-1200.00"))
            for index in range(60)
        )

        for window in detect_level_shift_pelt(series, config):
            assert isinstance(window.window[0], date)
            assert isinstance(window.index, int)


class TestShiftWindow:
    """§5.8.5: сравнение потоков внутри окна."""

    def test_zero_log_flow_points_at_the_ledger(self) -> None:
        """Логи ≈ 0, а 1С ≠ 0 → расхождение целиком в учёте.

        Эталон Солигорска, окно 06.09–19.12.2025: логи 0,00, 1С −2 911,51.
        """
        ledger = (
            _income(1, _day(1), Decimal("1000.00")),
            _collection(2, _day(2), Decimal("1000.00")),
            _refund(3, _day(3), Decimal("2911.51")),
        )
        ops = (
            ops_entry(
                row=100,
                moment=datetime(2024, 2, 2, 12, 0, 0),
                amount=Decimal("1000.00"),
            ).model_copy(update={"classification": OpsClass.INCOME, "classified_by": "block"}),
            ops_entry(
                row=101,
                moment=datetime(2024, 2, 3, 12, 0, 0),
                amount=Decimal("1000.00"),
            ).model_copy(
                update={"classification": OpsClass.COLLECTION, "classified_by": "counterparty"},
            ),
        )

        flows = localize_shift_window((_day(1), _day(4)), _classified(ledger, ops))

        assert flows.ops_flow == ZERO
        assert flows.ledger_flow == Decimal("-2911.51")
        assert flows.dominant_category is Category.REFUND


class TestWaterfall:
    """§5.10: раскладка без остатка."""

    def test_ties_at_zero_on_consistent_data(self, config: Config) -> None:
        """§13.2: |unresolved| < EPS_TIE."""
        ledger = (
            _income(1, _day(0), Decimal("1000.00")),
            _collection(2, _day(1), Decimal("900.00")),
            _refund(3, _day(2), Decimal("160.89")),
        )
        classified = _classified(ledger)
        balance = balance_trace(classified, ZERO, config)
        reconciliation = {
            Category.INCOME: _recon(Category.INCOME, Decimal("1000.00")),
            Category.COLLECTION: _recon(Category.COLLECTION, Decimal("900.00")),
            Category.REFUND: _recon(Category.REFUND, Decimal("160.89")),
        }

        waterfall = build_waterfall(reconciliation, balance, classified)

        assert waterfall.closing == Decimal("-60.89")
        assert abs(check_tie(waterfall)) < config.thresholds.EPS_TIE

    def test_ties_with_nonzero_target(self, config: Config) -> None:
        """§11.1: раскладка сходится при T=0 и при T≠0."""
        raised = config.model_copy(update={"target_balance": Decimal("200.00")})
        ledger = (_income(1, _day(0), Decimal("1000.00")),)
        classified = _classified(ledger)
        balance = balance_trace(classified, ZERO, raised)
        reconciliation = {
            Category.INCOME: _recon(Category.INCOME, Decimal("1000.00")),
            Category.COLLECTION: _recon(Category.COLLECTION, ZERO),
            Category.REFUND: _recon(Category.REFUND, ZERO),
        }

        waterfall = build_waterfall(reconciliation, balance, classified)

        assert waterfall.target == Decimal("200.00")
        assert abs(check_tie(waterfall)) < raised.thresholds.EPS_TIE

    def test_other_flows_cover_exchange(self) -> None:
        """Размен не входит в сверку §5.6, но обязан войти в тождество §5.10."""
        ledger = (
            ledger_entry(row=1, debit=Decimal("50.00"), account="50.1", category=Category.EXCHANGE),
            ledger_entry(row=2, credit=Decimal("20.00"), account="76.6", category=Category.OTHER),
        )

        assert other_flows(_classified(ledger)) == (Decimal("50.00"), Decimal("20.00"))

    def test_log_imbalance_is_a_separate_line(self, config: Config) -> None:
        """§5.10: дефект первички не смешивается с расхождениями 1С."""
        ledger = (_income(1, _day(0), Decimal("1000.00")),)
        classified = _classified(ledger)
        waterfall = build_waterfall(
            {
                Category.INCOME: _recon(Category.INCOME, Decimal("1000.00")),
                Category.COLLECTION: _recon(Category.COLLECTION, ZERO),
                Category.REFUND: _recon(Category.REFUND, ZERO),
            },
            balance_trace(classified, ZERO, config),
            classified,
        )

        assert waterfall.log_imbalance == ZERO

    def test_causal_lines_sum_to_the_deviation(self, config: Config) -> None:
        """§5.10: причинная раскладка обязана покрывать всё отклонение."""
        ledger = (
            _income(1, _day(0), Decimal("1000.00")),
            _refund(2, _day(1), Decimal("160.89")),
        )
        classified = _classified(ledger)
        balance = balance_trace(classified, ZERO, config)
        waterfall = decompose(
            {
                Category.INCOME: _recon(Category.INCOME, Decimal("1000.00")),
                Category.COLLECTION: _recon(Category.COLLECTION, ZERO),
                Category.REFUND: _recon(Category.REFUND, Decimal("160.89")),
            },
            balance,
            classified,
            (),
            (),
        )

        total = sum((line.amount for line in waterfall.causal_lines), ZERO)
        assert total == waterfall.closing - waterfall.target
