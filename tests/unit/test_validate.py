"""Юнит-тесты стадии VALIDATE — §5.3, инварианты V1–V6."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from cashforensics.models import (
    Config,
    LedgerEntry,
    LedgerTotals,
    NormalizeResult,
    OpsEntry,
    OpsKind,
    ValidationCheck,
    ValidationReport,
)
from cashforensics.validate import ValidationFailed, validate
from tests.unit.test_classify import ledger_entry, ops_entry

pytestmark = pytest.mark.unit

ZERO = Decimal("0.00")


def _normalized(
    *,
    ledger: tuple[LedgerEntry, ...] = (),
    ops: tuple[OpsEntry, ...] = (),
    opening: Decimal = ZERO,
    closing: Decimal | None = None,
    turnover_debit: Decimal | None = None,
    turnover_credit: Decimal | None = None,
) -> NormalizeResult:
    """Выход §5.2 для теста; ``closing`` по умолчанию делает V3 сходящимся."""
    debit_total = sum((entry.debit for entry in ledger), ZERO)
    credit_total = sum((entry.credit for entry in ledger), ZERO)
    return NormalizeResult(
        ledger=ledger,
        ops=ops,
        totals=LedgerTotals(
            opening=opening,
            closing_stated=(
                closing if closing is not None else opening + debit_total - credit_total
            ),
            turnover_debit=turnover_debit,
            turnover_credit=turnover_credit,
        ),
        issues=(),
    )


def _check(report: ValidationReport, code: str) -> ValidationCheck:
    """Достать конкретный контроль из отчёта §5.3."""
    return next(check for check in report.checks if check.code == code)


class TestHardInvariants:
    """§5.3: нарушение V1–V3 — остановка, а не предупреждение."""

    def test_all_pass_on_consistent_data(self, config: Config) -> None:
        normalized = _normalized(
            ledger=(
                ledger_entry(row=1, debit=Decimal("100.00"), account="90.1.1"),
                ledger_entry(row=2, credit=Decimal("40.00"), account="76.9.1"),
            ),
            turnover_debit=Decimal("100.00"),
            turnover_credit=Decimal("40.00"),
        )

        report = validate(normalized, config)

        assert not report.hard_failed
        assert all(_check(report, code).passed for code in ("V1", "V2", "V3"))

    def test_v1_fails_on_broken_debit_turnover(self, config: Config) -> None:
        normalized = _normalized(
            ledger=(ledger_entry(row=1, debit=Decimal("100.00"), account="90.1.1"),),
            turnover_debit=Decimal("999.00"),
            turnover_credit=ZERO,
        )

        with pytest.raises(ValidationFailed, match="V1"):
            validate(normalized, config)

    def test_v2_fails_on_broken_credit_turnover(self, config: Config) -> None:
        normalized = _normalized(
            ledger=(ledger_entry(row=1, credit=Decimal("40.00"), account="76.9.1"),),
            turnover_debit=ZERO,
            turnover_credit=Decimal("999.00"),
        )

        with pytest.raises(ValidationFailed, match="V2"):
            validate(normalized, config)

    def test_v3_catches_balance_read_from_wrong_column(self, config: Config) -> None:
        """Регресс на ловушку §3.2.

        Чтение сальдо из колонки 9 давало 0 вместо −4 952,36. Именно V3 поймал
        эту ошибку на Щучине.
        """
        normalized = _normalized(
            ledger=(ledger_entry(row=1, credit=Decimal("4952.36"), account="76.9.1"),),
            opening=ZERO,
            closing=ZERO,
        )

        with pytest.raises(ValidationFailed, match="V3"):
            validate(normalized, config)

    def test_v3_passes_with_correct_negative_closing(self, config: Config) -> None:
        normalized = _normalized(
            ledger=(ledger_entry(row=1, credit=Decimal("4952.36"), account="76.9.1"),),
            opening=ZERO,
            closing=Decimal("-4952.36"),
        )

        report = validate(normalized, config)

        assert _check(report, "V3").passed

    def test_tolerance_is_one_kopeck(self, config: Config) -> None:
        """§5.3: допуск 0,01 — не больше и не меньше."""
        within = _normalized(
            ledger=(ledger_entry(row=1, debit=Decimal("100.00"), account="90.1.1"),),
            closing=Decimal("100.01"),
        )
        beyond = _normalized(
            ledger=(ledger_entry(row=1, debit=Decimal("100.00"), account="90.1.1"),),
            closing=Decimal("100.02"),
        )

        assert validate(within, config).hard_failed is False
        with pytest.raises(ValidationFailed):
            validate(beyond, config)

    def test_stop_message_explains_why(self, config: Config) -> None:
        """§0.2: остановка обязана быть объяснимой."""
        normalized = _normalized(
            ledger=(ledger_entry(row=1, debit=Decimal("100.00"), account="90.1.1"),),
            closing=Decimal("999.00"),
        )

        with pytest.raises(ValidationFailed) as excinfo:
            validate(normalized, config)

        assert "V3" in str(excinfo.value)
        assert "расхождение" in str(excinfo.value)


class TestSkippedTurnovers:
    """§5.3: без «Оборотов за период» V1/V2 пропускаются, V3 остаётся."""

    def test_v1_v2_skipped_v3_still_enforced(self, config: Config) -> None:
        normalized = _normalized(
            ledger=(ledger_entry(row=1, debit=Decimal("100.00"), account="90.1.1"),),
            closing=Decimal("999.00"),
        )

        with pytest.raises(ValidationFailed) as excinfo:
            validate(normalized, config)

        assert "V3" in str(excinfo.value)
        assert "V1" not in str(excinfo.value)

    def test_skipped_checks_are_marked(self, config: Config) -> None:
        normalized = _normalized(
            ledger=(ledger_entry(row=1, debit=Decimal("100.00"), account="90.1.1"),),
        )

        report = validate(normalized, config)

        assert _check(report, "V1").skipped
        assert "отсутствует" in _check(report, "V1").message


class TestWarnings:
    """§5.3: V4–V6 — предупреждения, конвейер не останавливают."""

    def test_v4_disables_daily_reconciliation_on_modal_dates(self, config: Config) -> None:
        """Все записи в одной дате → даты блока ненадёжны."""
        ops = tuple(
            ops_entry(row=index, moment=datetime(2024, 2, 1, 10, index, 0))
            for index in range(1, 11)
        )
        normalized = _normalized(ops=ops)

        report = validate(normalized, config)

        assert not report.daily_reconciliation_enabled
        assert not _check(report, "V4").passed

    def test_v4_passes_on_spread_dates(self, config: Config) -> None:
        ops = tuple(
            ops_entry(row=index, moment=datetime(2024, 2, index, 10, 0, 0))
            for index in range(1, 11)
        )
        normalized = _normalized(ops=ops)

        report = validate(normalized, config)

        assert report.daily_reconciliation_enabled

    def test_v4_requires_min_days(self, config: Config) -> None:
        """На трёх днях дневная сверка бессмысленна — MIN_DAYS §6."""
        ops = tuple(
            ops_entry(row=index, moment=datetime(2024, 2, index, 10, 0, 0)) for index in range(1, 4)
        )
        normalized = _normalized(ops=ops)

        report = validate(normalized, config)

        assert not report.daily_reconciliation_enabled
        assert "MIN_DAYS" in _check(report, "V4").message

    def test_v5_lists_unknown_accounts_without_stopping(self, config: Config) -> None:
        """§3.5: счёт вне справочника — отдельная строка отчёта, не остановка."""
        normalized = _normalized(
            ledger=(ledger_entry(row=1, debit=Decimal("100.00"), account="99.9.9"),),
        )

        report = validate(normalized, config)

        assert report.unknown_accounts == ("99.9.9",)
        assert not _check(report, "V5").passed
        assert not report.hard_failed

    def test_v6_flags_cutoff(self, config: Config) -> None:
        """Записи лога позже последней проводки 1С — признак среза периода.

        Сравнение идёт по виду документа: ПКО с ПКО, РКО с РКО. Общий максимум
        по выгрузке срез маскирует — на Щучине приход в 1С остановлен 06.05, а
        инкассация шла до 12.05, и ``max`` совпадал (§11.3).
        """
        normalized = _normalized(
            ledger=(ledger_entry(row=1, day=date(2026, 5, 6), debit=Decimal("100.00")),),
            ops=(ops_entry(row=2, moment=datetime(2026, 5, 12, 10, 0, 0), kind=OpsKind.PKO),),
        )

        report = validate(normalized, config)

        assert report.cutoff_suspected
        assert "среза периода" in _check(report, "V6").message

    def test_v6_quiet_when_log_ends_with_ledger(self, config: Config) -> None:
        normalized = _normalized(
            ledger=(ledger_entry(row=1, day=date(2026, 5, 12), debit=Decimal("100.00")),),
            ops=(ops_entry(row=2, moment=datetime(2026, 5, 12, 10, 0, 0), kind=OpsKind.PKO),),
        )

        assert not validate(normalized, config).cutoff_suspected


def test_report_lists_all_six_checks_in_order(config: Config) -> None:
    """§5.3: отчёт содержит V1…V6 в фиксированном порядке (§13.5)."""
    report = validate(_normalized(), config)

    assert tuple(check.code for check in report.checks) == ("V1", "V2", "V3", "V4", "V5", "V6")
