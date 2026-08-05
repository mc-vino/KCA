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

from cashforensics.models import (
    ClassifyResult,
    Config,
    LedgerEntry,
    OpsEntry,
    ReversalResult,
)

__all__ = [
    "find_reversal_candidates",
    "has_actual_payout",
    "is_reversal",
    "neutralize_reversals",
    "select_counterpart",
]


def is_reversal(entry: LedgerEntry, reversal_pattern: str) -> bool:
    """Проводка является сторно — §5.5.

    Признак: документ «Корректировка записей регистров» либо отрицательная
    сумма.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def find_reversal_candidates(
    reversal: LedgerEntry,
    ledger: tuple[LedgerEntry, ...],
    neutralized: frozenset[int],
) -> tuple[LedgerEntry, ...]:
    """Кандидаты на гашение сторно — §5.5.

    Кандидат: не сторно, не нейтрализован ранее, ``|сумма| == |сумма s|``,
    ``корр_счёт == корр_счёт s``.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def select_counterpart(
    reversal: LedgerEntry,
    candidates: tuple[LedgerEntry, ...],
) -> LedgerEntry | None:
    """Выбрать пару детерминированно — §5.5, §12.

    Минимальное ``|дата − дата_s|``; при равенстве — меньший ``row``.
    Полный явный ключ сортировки обязателен (§12).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def has_actual_payout(
    original: LedgerEntry,
    ops: tuple[OpsEntry, ...],
    config: Config,
) -> bool:
    """Была ли фактическая выдача в день оригинальной проводки — §5.5.

    Если да, а проводка снята и не перепроведена — вместо ``REVERSAL_PAIR``
    выдаётся ``REVERSAL_WITHOUT_REBOOK`` с ``severity=ПРОВЕРИТЬ``.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def neutralize_reversals(
    classified: ClassifyResult,
    config: Config,
) -> ReversalResult:
    """Стадия NEUTRALIZE_REVERSALS целиком — §5.5.

    Порядок обхода сторно-записей строго по ``row`` (детерминированность §12).
    Каждое гашение пишется в журнал :class:`~cashforensics.models.AuditLogEntry`:
    что погашено, чем, каким правилом.

    Отключается флагом ``--no-reversal-neutralization`` (§12, обратимость).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError
