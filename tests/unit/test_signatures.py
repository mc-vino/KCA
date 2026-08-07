"""Юнит-тесты сигнатур §8.1–8.2.

Ловушки, закреплённые здесь (§11.1):

* сигнатура повтора выдаётся **только по РКО** и всегда несёт базовую частоту
  по ПКО — без неё она читается как обвинение (§8.1);
* формулировка §8.1 дословная: «повтор может быть законным», а не «двойная
  выдача»;
* пропуски нумерации не подсчитываются на разреженном ряду: 250 документов на
  21 000 номеров — это сквозная нумерация организации, а не 20 893 удалённых
  документа (§8.2).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from cashforensics.models import Config, FindingCode, OpsEntry, OpsKind, Severity
from cashforensics.signatures import (
    REPEAT_DISCLAIMER,
    duplicate_documents,
    iqr_bounds,
    late_time_documents,
    modified_z_scores,
    repeat_baseline_pko,
    repeat_payouts,
    round_number_bias,
    sequence_gaps,
)
from tests.unit.test_classify import ledger_entry, ops_entry

pytestmark = pytest.mark.unit

DAY = date(2024, 2, 1)


def _payout(row: int, minute: int, amount: str, *, kind: OpsKind = OpsKind.RKO) -> OpsEntry:
    return ops_entry(
        row=row,
        moment=datetime(2024, 2, 1, 13, 26, minute),
        amount=Decimal(amount),
        counterparty="Иванов Иван",
        kind=kind,
    )


class TestRepeatPayouts:
    """§8.1 — повторная выдача одной суммы одному получателю."""

    def test_four_payouts_in_22_seconds_are_one_signature(self, config: Config) -> None:
        """Эталон §8.1: 14.05, четыре РКО по 164,99 за 22 секунды."""
        entries = [
            ops_entry(
                row=row,
                moment=datetime(2024, 2, 1, 13, 26, 55) + timedelta(seconds=shift),
                amount=Decimal("164.99"),
                counterparty="Правосуд Дмитрий",
            )
            for row, shift in enumerate((0, 7, 14, 22), start=10)
        ]
        signatures = repeat_payouts(entries, config)
        assert len(signatures) == 1
        assert signatures[0].code is FindingCode.REPEAT_PAYOUT
        assert signatures[0].amount == Decimal("659.96")
        assert signatures[0].rows == (10, 11, 12, 13)

    def test_pko_repeats_never_produce_a_signature(self, config: Config) -> None:
        """§8.1: сигнатура выдаётся только по РКО. В ПКО повтор — норма."""
        entries = [_payout(row, 55, "164.99", kind=OpsKind.PKO) for row in (10, 11, 12)]
        assert repeat_payouts(entries, config) == ()

    def test_baseline_is_mandatory_context(self, config: Config) -> None:
        """§8.1: без базовой частоты по ПКО сигнатура читается как обвинение."""
        entries = [_payout(row, 55, "164.99") for row in (10, 11)]
        signature = repeat_payouts(entries, config)[0]
        assert signature.baseline is not None
        assert "ПКО" in signature.baseline

    def test_wording_is_the_one_the_spec_requires(self, config: Config) -> None:
        """§8.1, §6 правил: «повтор может быть законным», не «двойная выдача»."""
        entries = [_payout(row, 55, "164.99") for row in (10, 11)]
        signature = repeat_payouts(entries, config)[0]
        assert REPEAT_DISCLAIMER in signature.explanation
        for forbidden in ("двойная выдача", "фрод", "кража", "хищение"):
            assert forbidden not in signature.explanation.lower()

    def test_outside_the_window_is_not_a_repeat(self, config: Config) -> None:
        """Окно §6 ``repeat_window_minutes`` — 10 минут."""
        entries = [
            ops_entry(
                row=10,
                moment=datetime(2024, 2, 1, 13, 0, 0),
                amount=Decimal("164.99"),
                counterparty="Иванов Иван",
            ),
            ops_entry(
                row=11,
                moment=datetime(2024, 2, 1, 13, 30, 0),
                amount=Decimal("164.99"),
                counterparty="Иванов Иван",
            ),
        ]
        assert repeat_payouts(entries, config) == ()

    def test_baseline_counts_both_streams(self, config: Config) -> None:
        """§8.1: контекст — число случаев в ПКО против РКО."""
        ops = [
            *(_payout(row, 55, "100.00", kind=OpsKind.PKO) for row in (1, 2)),
            *(_payout(row, 55, "200.00") for row in (3, 4)),
        ]
        baseline = repeat_baseline_pko(ops, config)
        assert "1 таких случаев в ПКО против 1 в РКО" in baseline


class TestLateTimeDocuments:
    """§8 — ``LATE_TIME_DOC``."""

    def test_midnight_is_a_daily_aggregate_not_a_night_payout(self, config: Config) -> None:
        """00:00:00 — метка дневного агрегата §3.3, а не операция ночью."""
        entry = ops_entry(row=5, moment=datetime(2024, 2, 1, 0, 0, 0))
        assert late_time_documents([entry], config) == ()

    def test_shift_closing_stamp_is_flagged(self, config: Config) -> None:
        """23:59:59 — типичная отметка автоматического закрытия смены."""
        entry = ops_entry(row=5, moment=datetime(2024, 2, 1, 23, 59, 59))
        signatures = late_time_documents([entry], config)
        assert len(signatures) == 1
        assert signatures[0].code is FindingCode.LATE_TIME_DOC

    def test_business_hours_are_not_flagged(self, config: Config) -> None:
        entry = ops_entry(row=5, moment=datetime(2024, 2, 1, 12, 0, 0))
        assert late_time_documents([entry], config) == ()


class TestSequenceGaps:
    """§8.2 — непрерывность нумерации."""

    def test_dense_run_reports_missing_numbers(self) -> None:
        ledger = [
            ledger_entry(row=row, number=f"{number:011d}")
            for row, number in enumerate((100, 101, 103, 104), start=1)
        ]
        signatures = sequence_gaps(ledger)
        assert len(signatures) == 1
        assert signatures[0].code is FindingCode.SEQUENCE_GAP
        assert "не хватает 1" in signatures[0].explanation
        assert "102" in signatures[0].explanation
        assert signatures[0].severity is None

    def test_continuous_run_is_silent(self) -> None:
        ledger = [
            ledger_entry(row=row, number=f"{number:011d}")
            for row, number in enumerate((100, 101, 102), start=1)
        ]
        assert sequence_gaps(ledger) == ()

    def test_sparse_series_is_demoted_and_not_counted(self) -> None:
        """§8.2: сквозная по организации нумерация — тест информационный.

        Ловушка PAX_119049688: номер 1С ``000000223359`` и штрихкод
        ``12258438561`` имеют одну разрядность. Наивный подсчёт объявлял
        12 258 215 202 «пропущенных документа».
        """
        ledger = [
            ledger_entry(row=row, number=f"{number:011d}")
            for row, number in enumerate((223359, 223360, 12258438561), start=1)
        ]
        signatures = sequence_gaps(ledger)
        assert len(signatures) == 1
        assert signatures[0].severity is Severity.INFO
        assert "непроверяема" in signatures[0].title
        assert "12258215202" not in signatures[0].explanation

    def test_two_numbers_are_not_a_sequence(self) -> None:
        ledger = [
            ledger_entry(row=1, number="00000000100"),
            ledger_entry(row=2, number="00000000105"),
        ]
        assert sequence_gaps(ledger) == ()


class TestDuplicateDocuments:
    """§8 — ``PKO_DOUBLE_BOOKED``: одна сумма, один день, один счёт, разные номера."""

    def test_same_number_is_not_a_double_booking(self) -> None:
        ledger = [
            ledger_entry(row=1, debit=Decimal("100.00"), number="00000000100"),
            ledger_entry(row=2, debit=Decimal("100.00"), number="00000000100"),
        ]
        assert duplicate_documents(ledger) == ()

    def test_different_numbers_same_day_and_amount_are_flagged(self) -> None:
        ledger = [
            ledger_entry(row=1, debit=Decimal("100.00"), number="00000000100"),
            ledger_entry(row=2, debit=Decimal("100.00"), number="00000000101"),
        ]
        signatures = duplicate_documents(ledger)
        assert len(signatures) == 1
        assert signatures[0].code is FindingCode.PKO_DOUBLE_BOOKED
        assert signatures[0].rows == (1, 2)

    def test_different_days_are_not_a_double_booking(self) -> None:
        ledger = [
            ledger_entry(row=1, day=DAY, debit=Decimal("100.00"), number="00000000100"),
            ledger_entry(
                row=2,
                day=date(2024, 2, 2),
                debit=Decimal("100.00"),
                number="00000000101",
            ),
        ]
        assert duplicate_documents(ledger) == ()


class TestRoundNumberBias:
    """§8 ``SHIFT_ROUNDING`` — слабый признак, severity НОРМА (§15)."""

    def test_round_amount_below_limit_is_flagged(self, config: Config) -> None:
        ledger = [ledger_entry(row=1, debit=Decimal("50.00"))]
        signatures = round_number_bias(ledger, config)
        assert len(signatures) == 1
        assert signatures[0].code is FindingCode.SHIFT_ROUNDING

    def test_above_round_max_is_not_a_shift_rounding(self, config: Config) -> None:
        ledger = [ledger_entry(row=1, debit=config.thresholds.ROUND_MAX)]
        assert round_number_bias(ledger, config) == ()

    def test_non_round_amount_is_ignored(self, config: Config) -> None:
        ledger = [ledger_entry(row=1, debit=Decimal("51.30"))]
        assert round_number_bias(ledger, config) == ()

    def test_weakness_is_stated_in_the_baseline(self, config: Config) -> None:
        """§15: round-number bias — только как слабый признак, в связке."""
        signatures = round_number_bias([ledger_entry(row=1, debit=Decimal("50.00"))], config)
        assert signatures[0].baseline is not None
        assert "слабый" in signatures[0].baseline


class TestRobustStatistics:
    """Робастные оценки §5.8/§15 — медиана и MAD, без ML."""

    def test_modified_z_flags_the_outlier(self) -> None:
        values = [Decimal(x) for x in ("9", "10", "11", "12", "1000")]
        scores = modified_z_scores(values)
        assert scores[-1] > 3.5
        assert max(abs(score) for score in scores[:-1]) < 3.5

    def test_zero_mad_does_not_divide_by_zero(self) -> None:
        values = [Decimal(10)] * 5
        assert modified_z_scores(values) == (0.0, 0.0, 0.0, 0.0, 0.0)

    def test_iqr_bounds_widen_with_the_multiplier(self) -> None:
        values = [Decimal(x) for x in ("1", "2", "3", "4", "5", "6", "7", "8")]
        soft_low, soft_high = iqr_bounds(values, 1.5)
        wide_low, wide_high = iqr_bounds(values, 3.0)
        assert wide_low < soft_low
        assert wide_high > soft_high
