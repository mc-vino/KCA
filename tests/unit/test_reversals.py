"""Юнит-тесты стадии NEUTRALIZE_REVERSALS — §5.5."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from cashforensics.models import (
    Category,
    ClassifyResult,
    Config,
    DocType,
    FindingCode,
    LedgerEntry,
    OpsClass,
    OpsEntry,
    Severity,
)
from cashforensics.reversals import (
    find_reversal_candidates,
    is_reversal,
    neutralize_reversals,
    select_counterpart,
)
from tests.unit.test_classify import ledger_entry, ops_entry

pytestmark = pytest.mark.unit

ZERO = Decimal("0.00")
REVERSAL_DOC = "Корректировка записей регистров 000009106"


def _classified(
    ledger: tuple[LedgerEntry, ...] = (),
    ops: tuple[OpsEntry, ...] = (),
) -> ClassifyResult:
    """Выход §5.4 для теста."""
    return ClassifyResult(ledger=ledger, ops=ops, fallback=None, unknown_accounts=())


def _refund(
    row: int,
    day: date,
    amount: Decimal,
    doc: str = "РКО 000007991",
) -> LedgerEntry:
    """Проводка возврата — §3.5."""
    return ledger_entry(
        row=row,
        day=day,
        credit=amount,
        account="76.9.1",
        category=Category.REFUND,
        doc=doc,
        doc_type=DocType.RKO,
    )


def _storno(row: int, day: date, amount: Decimal) -> LedgerEntry:
    """Сторно «Корректировка записей регистров» — §5.5."""
    return ledger_entry(
        row=row,
        day=day,
        debit=amount,
        account="76.9.1",
        category=Category.OTHER,
        doc=REVERSAL_DOC,
        doc_type=DocType.REVERSAL,
        is_reversal=True,
    )


def _payout(row: int, moment: datetime, amount: Decimal) -> OpsEntry:
    """Фактическая выдача клиенту в опер-логе — §3.6."""
    entry = ops_entry(row=row, moment=moment, amount=amount, counterparty="Иванов Иван")
    return entry.model_copy(
        update={"classification": OpsClass.REFUND, "classified_by": "counterparty"},
    )


class TestReversalDetection:
    """§5.5: сторно — документ корректировки либо отрицательная сумма."""

    def test_correction_document_is_reversal(self, config: Config) -> None:
        entry = _storno(1, date(2023, 10, 1), Decimal("1046.75"))

        assert is_reversal(entry, config.patterns.reversal_doc)

    def test_negative_amount_is_reversal(self, config: Config) -> None:
        entry = ledger_entry(row=1, credit=Decimal("-100.00"), doc="РКО 000123456")

        assert is_reversal(entry, config.patterns.reversal_doc)

    def test_ordinary_posting_is_not_reversal(self, config: Config) -> None:
        entry = _refund(1, date(2023, 6, 29), Decimal("100.00"))

        assert not is_reversal(entry, config.patterns.reversal_doc)


class TestCounterpartSelection:
    """§5.5: пара выбирается детерминированно."""

    def test_candidates_match_amount_and_account(self) -> None:
        storno = _storno(9, date(2023, 10, 1), Decimal("1046.75"))
        ledger = (
            _refund(1, date(2023, 6, 29), Decimal("1046.75")),
            _refund(2, date(2023, 6, 29), Decimal("999.00")),
            ledger_entry(
                row=3,
                credit=Decimal("1046.75"),
                account="51",
                category=Category.COLLECTION,
            ),
            storno,
        )

        candidates = find_reversal_candidates(storno, ledger, frozenset())

        assert [entry.row for entry in candidates] == [1]

    def test_nearest_date_wins(self) -> None:
        storno = _storno(9, date(2023, 10, 1), Decimal("100.00"))
        candidates = (
            _refund(1, date(2023, 1, 1), Decimal("100.00")),
            _refund(2, date(2023, 9, 28), Decimal("100.00")),
        )

        chosen = select_counterpart(storno, candidates)

        assert chosen is not None
        assert chosen.row == 2

    def test_tie_broken_by_smaller_row(self) -> None:
        """§5.5: при равном расстоянии по дате — меньший row (§12)."""
        storno = _storno(9, date(2023, 10, 1), Decimal("100.00"))
        candidates = (
            _refund(5, date(2023, 9, 28), Decimal("100.00")),
            _refund(2, date(2023, 9, 28), Decimal("100.00")),
        )

        chosen = select_counterpart(storno, candidates)

        assert chosen is not None
        assert chosen.row == 2


class TestNeutralization:
    """§5.5: пара гасится; сторно с реальной выдачей — не нейтральная пара."""

    def test_pair_is_neutralized(self, config: Config) -> None:
        """§11.1: пара гасится."""
        ledger = (
            _refund(1, date(2023, 6, 29), Decimal("1046.75")),
            _storno(9, date(2023, 10, 1), Decimal("1046.75")),
        )

        result = neutralize_reversals(_classified(ledger=ledger), config)

        assert result.neutralized_rows == frozenset({1, 9})
        assert [finding.code for finding in result.findings] == [FindingCode.REVERSAL_PAIR]
        assert result.findings[0].balance_impact == ZERO

    def test_storno_with_real_payout_is_not_neutral(self, config: Config) -> None:
        """§11.1: сторно с реальной выдачей НЕ гасится как нейтральное.

        Кейс Солигорска: R9106 от 01.10.2023 сняло R7991 от 29.06.2023 на
        1 046,75. В опер-логе 29.06.2023 было 8 выдач ровно на эту сумму —
        деньги ушли, проводка снята, возвраты не перепроведены.
        """
        ledger = (
            _refund(1, date(2023, 6, 29), Decimal("1046.75")),
            _storno(9, date(2023, 10, 1), Decimal("1046.75")),
        )
        ops = tuple(
            _payout(100 + index, datetime(2023, 6, 29, 10 + index, 0, 0), Decimal("130.84"))
            for index in range(8)
        )
        # Восемь выдач в сумме дают ровно снятую проводку.
        ops = (*ops[:7], _payout(107, datetime(2023, 6, 29, 17, 0, 0), Decimal("130.87")))

        result = neutralize_reversals(_classified(ledger=ledger, ops=ops), config)

        finding = result.findings[0]
        assert finding.code is FindingCode.REVERSAL_WITHOUT_REBOOK
        assert finding.severity is Severity.REVIEW
        assert finding.balance_impact == Decimal("1046.75")
        assert finding.ops_rows

    def test_rebooked_posting_stays_an_ordinary_pair(self, config: Config) -> None:
        """Штатное «сторнировали и провели правильно» находкой не является."""
        ledger = (
            _refund(1, date(2023, 6, 29), Decimal("1046.75")),
            _refund(2, date(2023, 7, 3), Decimal("1046.75"), doc="РКО 000008001"),
            _storno(9, date(2023, 10, 1), Decimal("1046.75")),
        )
        ops = (_payout(100, datetime(2023, 6, 29, 12, 0, 0), Decimal("1046.75")),)

        result = neutralize_reversals(_classified(ledger=ledger, ops=ops), config)

        assert result.findings[0].code is FindingCode.REVERSAL_PAIR

    def test_unmatched_storno_is_reported(self, config: Config) -> None:
        ledger = (_storno(9, date(2023, 10, 1), Decimal("1046.75")),)

        result = neutralize_reversals(_classified(ledger=ledger), config)

        assert result.findings[0].code is FindingCode.REVERSAL_UNMATCHED
        assert result.neutralized_rows == frozenset({9})

    def test_findings_never_call_it_theft(self, config: Config) -> None:
        """§1.2, §13.10: инструмент не квалифицирует находку как хищение."""
        ledger = (
            _refund(1, date(2023, 6, 29), Decimal("1046.75")),
            _storno(9, date(2023, 10, 1), Decimal("1046.75")),
        )
        ops = (_payout(100, datetime(2023, 6, 29, 12, 0, 0), Decimal("1046.75")),)

        result = neutralize_reversals(_classified(ledger=ledger, ops=ops), config)

        forbidden = ("фрод", "кража", "виновен", "хищен", "мошенн")
        for finding in result.findings:
            text = (finding.title + finding.explanation).lower()
            assert not any(word in text for word in forbidden)

    def test_audit_log_records_each_neutralization(self, config: Config) -> None:
        """§12: что погашено, чем, каким правилом."""
        ledger = (
            _refund(1, date(2023, 6, 29), Decimal("1046.75")),
            _storno(9, date(2023, 10, 1), Decimal("1046.75")),
        )

        result = neutralize_reversals(_classified(ledger=ledger), config)

        record = result.audit_log[0]
        assert record.subject_rows == (9,)
        assert record.counterpart_rows == (1,)
        assert record.amount == Decimal("1046.75")

    def test_disabled_neutralization_shows_raw_picture(self, config: Config) -> None:
        """§12, обратимость: ``--no-reversal-neutralization``."""
        ledger = (
            _refund(1, date(2023, 6, 29), Decimal("1046.75")),
            _storno(9, date(2023, 10, 1), Decimal("1046.75")),
        )

        result = neutralize_reversals(_classified(ledger=ledger), config, enabled=False)

        assert result.neutralized_rows == frozenset()
        assert result.findings == ()

    def test_is_deterministic(self, config: Config) -> None:
        """§13.5: повторный прогон даёт тот же результат."""
        ledger = (
            _refund(1, date(2023, 6, 29), Decimal("100.00")),
            _refund(2, date(2023, 6, 29), Decimal("100.00")),
            _storno(9, date(2023, 10, 1), Decimal("100.00")),
            _storno(10, date(2023, 10, 2), Decimal("100.00")),
        )
        classified = _classified(ledger=ledger)

        first = neutralize_reversals(classified, config)
        second = neutralize_reversals(classified, config)

        assert first.neutralized_rows == second.neutralized_rows
        assert [f.model_dump() for f in first.findings] == [f.model_dump() for f in second.findings]
