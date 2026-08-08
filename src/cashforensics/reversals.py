"""Стадия NEUTRALIZE_REVERSALS — §5.5 ТЗ.

Сторно = документ «Корректировка записей регистров» либо отрицательная сумма.

Обязательная дополнительная проверка (ловушка §5.5): для каждой
нейтрализованной пары проверить, была ли фактическая выдача в опер-логе в день
оригинальной проводки. Если выдача была, а проводка снята и не перепроведена —
это **не** нейтральная пара, а потеря учёта.

Реальный кейс (Солигорск): R9106 от 01.10.2023 сняло R7991 от 29.06.2023 на
1 046,75. В опер-логе 29.06.2023 было 8 выдач ровно на эту сумму — деньги ушли,
проводка снята, возвраты не перепроведены.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal

from cashforensics.models import (
    AuditLogEntry,
    Category,
    ClassifyResult,
    Config,
    Finding,
    FindingCode,
    LedgerEntry,
    Materiality,
    OpsClass,
    OpsEntry,
    ReversalResult,
    Severity,
)

__all__ = [
    "CATEGORY_TO_OPS_CLASS",
    "entry_amount",
    "find_reversal_candidates",
    "has_actual_payout",
    "has_rebooking",
    "is_reversal",
    "neutralize_reversals",
    "select_counterpart",
]

CATEGORY_TO_OPS_CLASS: dict[Category, OpsClass] = {
    Category.INCOME: OpsClass.INCOME,
    Category.COLLECTION: OpsClass.COLLECTION,
    Category.REFUND: OpsClass.REFUND,
}
"""Соответствие категорий 1С классам опер-лога — §5.6."""

_ZERO = Decimal("0.00")


def entry_amount(entry: LedgerEntry) -> Decimal:
    """Сумма проводки без учёта стороны — §5.5.

    У проводки заполнена ровно одна сторона (§4.1), поэтому сумма — их сложение.
    """
    return entry.debit + entry.credit


def is_reversal(entry: LedgerEntry, reversal_pattern: str) -> bool:
    """Проводка является сторно — §5.5.

    Признак: документ «Корректировка записей регистров» либо отрицательная
    сумма.
    """
    if re.search(reversal_pattern, entry.doc_text, re.IGNORECASE):
        return True
    return entry.debit < _ZERO or entry.credit < _ZERO


def find_reversal_candidates(
    reversal: LedgerEntry,
    ledger: Sequence[LedgerEntry],
    neutralized: frozenset[int],
) -> tuple[LedgerEntry, ...]:
    """Кандидаты на гашение сторно — §5.5.

    Кандидат: не сторно, не нейтрализован ранее, ``|сумма| == |сумма s|``,
    ``корр_счёт == корр_счёт s``.
    """
    target = abs(entry_amount(reversal))
    return tuple(
        entry
        for entry in ledger
        if not entry.is_reversal
        and entry.row not in neutralized
        and entry.row != reversal.row
        and abs(entry_amount(entry)) == target
        and entry.counter_account == reversal.counter_account
    )


def select_counterpart(
    reversal: LedgerEntry,
    candidates: Sequence[LedgerEntry],
) -> LedgerEntry | None:
    """Выбрать пару детерминированно — §5.5, §12.

    Минимальное ``|дата − дата_s|``; при равенстве — меньший ``row``.
    Полный явный ключ сортировки обязателен (§12).
    """
    if not candidates:
        return None
    return min(candidates, key=lambda entry: (abs((entry.date - reversal.date).days), entry.row))


def has_actual_payout(
    original: LedgerEntry,
    ops: Sequence[OpsEntry],
    config: Config,
) -> bool:
    """Была ли фактическая выдача в день оригинальной проводки — §5.5.

    Сравнивается сумма записей опер-лога соответствующего класса за этот день с
    суммой снятой проводки. На Солигорске 29.06.2023 деньги ушли восемью
    выдачами ровно на 1 046,75 — поэтому проверяется дневной итог, а не
    совпадение одной записи.
    """
    ops_class = CATEGORY_TO_OPS_CLASS.get(original.category)
    if ops_class is None:
        return False
    day_total = sum(
        (
            entry.amount
            for entry in ops
            if entry.classification is ops_class and entry.dt.date() == original.date
        ),
        _ZERO,
    )
    return day_total >= abs(entry_amount(original)) - config.thresholds.EPS_SUM


def has_rebooking(
    original: LedgerEntry,
    ledger: Sequence[LedgerEntry],
    neutralized: frozenset[int],
    config: Config,
) -> bool:
    """Была ли проводка перепроведена заново — §5.5.

    Ищется другая, ещё не нейтрализованная проводка того же счёта и той же
    суммы в окне ``LONG_WIN`` вокруг оригинала. Без этой проверки любое
    штатное «сторнировали и провели правильно» попадало бы в находки.
    """
    target = abs(entry_amount(original))
    window = config.thresholds.LONG_WIN
    return any(
        entry.row not in neutralized
        and entry.row != original.row
        and not entry.is_reversal
        and entry.counter_account == original.counter_account
        and abs(entry_amount(entry)) == target
        and abs((entry.date - original.date).days) <= window
        for entry in ledger
    )


def _pair_finding(
    reversal: LedgerEntry,
    original: LedgerEntry,
    ops_rows: tuple[int, ...],
    *,
    rebooked: bool,
) -> Finding:
    """Находка по нейтрализованной паре — ``REVERSAL_PAIR`` либо потеря учёта."""
    amount = abs(entry_amount(reversal))
    if rebooked:
        return Finding(
            code=FindingCode.REVERSAL_PAIR,
            severity=Severity.INFO,
            date=(min(original.date, reversal.date), max(original.date, reversal.date)),
            amount=amount,
            ledger_rows=[original.row, reversal.row],
            ops_rows=[],
            doc_numbers=[original.doc_number, reversal.doc_number],
            title="Сторно-пара нейтрализована",
            explanation=(
                f"Проводка от {original.date:%d.%m.%Y} на {amount} снята сторно от "
                f"{reversal.date:%d.%m.%Y}; пара взаимно погашается и на сальдо не влияет."
            ),
            evidence={
                "rule": "§5.5 нейтрализация сторно",
                "counter_account": original.counter_account,
                "original_row": original.row,
                "reversal_row": reversal.row,
            },
            confidence=1.0,
            materiality=Materiality.IMMATERIAL,
            balance_impact=_ZERO,
        )

    return Finding(
        code=FindingCode.REVERSAL_WITHOUT_REBOOK,
        severity=Severity.REVIEW,
        date=(min(original.date, reversal.date), max(original.date, reversal.date)),
        amount=amount,
        ledger_rows=[original.row, reversal.row],
        ops_rows=list(ops_rows),
        doc_numbers=[original.doc_number, reversal.doc_number],
        title="Сторно снято, выдача была, проводка не перепроведена",
        explanation=(
            f"Проводка от {original.date:%d.%m.%Y} на {amount} снята сторно от "
            f"{reversal.date:%d.%m.%Y}, но в опер-логе за {original.date:%d.%m.%Y} есть "
            "фактические выдачи на эту сумму, и повторной проводки в окне не найдено. "
            "Деньги из кассы вышли, в учёте операция отсутствует — требует проверки. "
            "Инструмент не может сказать, какая из систем права: возможна и ошибка "
            "выгрузки фронтальной системы (§16)."
        ),
        evidence={
            "rule": "§5.5 доп. проверка «была ли фактическая выдача»",
            "counter_account": original.counter_account,
            "original_row": original.row,
            "reversal_row": reversal.row,
            "ops_rows": list(ops_rows),
        },
        confidence=1.0,
        materiality=Materiality.IMMATERIAL,
        balance_impact=amount,
    )


def _unmatched_finding(reversal: LedgerEntry) -> Finding:
    """Находка ``REVERSAL_UNMATCHED`` — сторно без найденной пары (§5.5)."""
    amount = abs(entry_amount(reversal))
    return Finding(
        code=FindingCode.REVERSAL_UNMATCHED,
        severity=Severity.REVIEW,
        date=reversal.date,
        amount=amount,
        ledger_rows=[reversal.row],
        ops_rows=[],
        doc_numbers=[reversal.doc_number],
        title="Сторно без исходной проводки",
        explanation=(
            f"Сторно от {reversal.date:%d.%m.%Y} на {amount} по счёту "
            f"{reversal.counter_account} не нашло исходной проводки той же суммы. "
            "Отменяемая операция либо вне периода выгрузки, либо проведена с другой "
            "суммой — требует проверки."
        ),
        evidence={
            "rule": "§5.5 нейтрализация сторно",
            "counter_account": reversal.counter_account,
            "reversal_row": reversal.row,
        },
        confidence=1.0,
        materiality=Materiality.IMMATERIAL,
        balance_impact=reversal.debit - reversal.credit,
    )


def neutralize_reversals(
    classified: ClassifyResult,
    config: Config,
    *,
    enabled: bool = True,
) -> ReversalResult:
    """Стадия NEUTRALIZE_REVERSALS целиком — §5.5.

    Порядок обхода сторно-записей строго по ``row`` (детерминированность §12).
    Каждое гашение пишется в журнал :class:`~cashforensics.models.AuditLogEntry`:
    что погашено, чем, каким правилом.

    Пара помечается нейтрализованной и тогда, когда выдача фактически была: в
    1С обе проводки существуют и арифметически гасятся. Меняется только
    находка — вместо ``REVERSAL_PAIR`` выдаётся ``REVERSAL_WITHOUT_REBOOK``, и
    расхождение честно всплывает в сверке §5.6.

    Args:
        classified: выход стадии §5.4.
        config: конфигурация §6.
        enabled: ``False`` соответствует флагу ``--no-reversal-neutralization``
            (§12, обратимость): показывает сырую картину без автогашения.
    """
    if not enabled:
        return ReversalResult(neutralized_rows=frozenset(), findings=(), audit_log=())

    ledger = classified.ledger
    reversals = sorted(
        (entry for entry in ledger if is_reversal(entry, config.patterns.reversal_doc)),
        key=lambda entry: entry.row,
    )

    neutralized: set[int] = set()
    findings: list[Finding] = []
    audit: list[AuditLogEntry] = []

    for reversal in reversals:
        if reversal.row in neutralized:
            continue
        counterpart = select_counterpart(
            reversal,
            find_reversal_candidates(reversal, ledger, frozenset(neutralized)),
        )
        if counterpart is None:
            # Строка НЕ нейтрализуется: гасить нечем. §5.5 снимает **пару**, а
            # одиночное сторно — обычная проводка со знаком минус, и в сверке
            # §5.6 оно обязано участвовать наравне с прочими.
            #
            # Пока строка попадала в ``neutralized``, её сумма уходила из
            # категорийного ряда, но оставалась в нарастающем сальдо, и
            # тождество §5.10 расходилось ровно на неё. На `Кса_с_отклонением`
            # это давало `unresolved` = −40,00 при пороге §13.2 |x| < 2,00 —
            # блокирующий дефект по критерию приёмки.
            findings.append(_unmatched_finding(reversal))
            audit.append(
                AuditLogEntry(
                    stage="§5.5 neutralize_reversals",
                    rule="сторно без пары",
                    subject_rows=(reversal.row,),
                    counterpart_rows=(),
                    amount=abs(entry_amount(reversal)),
                    note="исходная проводка той же суммы и счёта не найдена",
                ),
            )
            continue

        neutralized.update({reversal.row, counterpart.row})
        payout_rows = tuple(
            entry.row
            for entry in classified.ops
            if entry.classification is CATEGORY_TO_OPS_CLASS.get(counterpart.category)
            and entry.dt.date() == counterpart.date
        )
        rebooked = not has_actual_payout(counterpart, classified.ops, config) or has_rebooking(
            counterpart,
            ledger,
            frozenset(neutralized),
            config,
        )
        findings.append(
            _pair_finding(reversal, counterpart, payout_rows, rebooked=rebooked),
        )
        audit.append(
            AuditLogEntry(
                stage="§5.5 neutralize_reversals",
                rule="сторно-пара по сумме и корр. счёту",
                subject_rows=(reversal.row,),
                counterpart_rows=(counterpart.row,),
                amount=abs(entry_amount(reversal)),
                note=(
                    "пара взаимно погашена"
                    if rebooked
                    else "выдача в опер-логе была, перепроведения не найдено"
                ),
            ),
        )

    findings.sort(key=lambda finding: (finding.ledger_rows[0], finding.code.value))
    return ReversalResult(
        neutralized_rows=frozenset(neutralized),
        findings=tuple(findings),
        audit_log=tuple(audit),
    )
