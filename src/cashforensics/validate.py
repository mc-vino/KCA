"""Стадия VALIDATE — §5.3 ТЗ.

Три жёстких инварианта V1–V3: нарушение любого = **остановка со статусом
ошибки**, а не предупреждение. V4–V6 — предупреждения.

Именно этот контроль поймал ошибку чтения сальдо на Щучине и подтвердил, что
все 8 разобранных касс распарсены полностью.
"""

from __future__ import annotations

from decimal import Decimal

from cashforensics.models import (
    Config,
    NormalizeResult,
    ValidationCheck,
    ValidationReport,
)

__all__ = [
    "TOLERANCE",
    "ValidationFailed",
    "check_v1_debit_turnover",
    "check_v2_credit_turnover",
    "check_v3_balance_identity",
    "check_v4_modal_date_share",
    "check_v5_unknown_accounts",
    "check_v6_cutoff",
    "validate",
]

TOLERANCE = Decimal("0.01")
"""Допуск инвариантов V1–V3 — §5.3."""


class ValidationFailed(RuntimeError):
    """Нарушен жёсткий инвариант V1–V3 — §5.3.

    Конвейер обязан остановиться: дальнейшие стадии на неполном разборе дадут
    правдоподобный, но неверный результат.
    """


def check_v1_debit_turnover(normalized: NormalizeResult) -> ValidationCheck:
    """V1: ``ΣДт(распарсено) == turnover_debit`` (допуск 0,01) — §5.3.

    Если ``turnover_debit`` в файле отсутствует — проверка пропускается с
    пометкой в отчёте.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def check_v2_credit_turnover(normalized: NormalizeResult) -> ValidationCheck:
    """V2: ``ΣКт(распарсено) == turnover_credit`` (допуск 0,01) — §5.3.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def check_v3_balance_identity(normalized: NormalizeResult) -> ValidationCheck:
    """V3: ``opening + ΣДт − ΣКт == closing_stated`` (допуск 0,01) — §5.3.

    Остаётся обязательной даже когда ``turnover_*`` отсутствуют.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def check_v4_modal_date_share(
    normalized: NormalizeResult,
    config: Config,
) -> ValidationCheck:
    """V4: доля записей опер-лога в одной дате > ``MODAL_BAD`` — §5.3.

    При срабатывании даты блока признаются ненадёжными: дневная сверка
    отключается, работает только сверка по итогам периода.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def check_v5_unknown_accounts(
    normalized: NormalizeResult,
    config: Config,
) -> ValidationCheck:
    """V5: счета вне справочника §3.5 — §5.3.

    Молчаливое поглощение неизвестного счёта запрещено: каждый обязан
    появиться в отчёте отдельной строкой.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def check_v6_cutoff(normalized: NormalizeResult) -> ValidationCheck:
    """V6: записи опер-лога позже последней проводки 1С — §5.3.

    Признак среза периода (§5.10, ``PERIOD_CUTOFF``).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def validate(normalized: NormalizeResult, config: Config) -> ValidationReport:
    """Стадия VALIDATE целиком — §5.3.

    Args:
        normalized: выход стадии NORMALIZE.
        config: конфигурация §6.

    Returns:
        :class:`ValidationReport` со всеми шестью проверками.

    Raises:
        ValidationFailed: нарушен V1, V2 или V3.
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError
