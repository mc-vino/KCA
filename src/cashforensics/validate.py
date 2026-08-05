"""Стадия VALIDATE — §5.3 ТЗ.

Три жёстких инварианта V1–V3: нарушение любого = **остановка со статусом
ошибки**, а не предупреждение. V4–V6 — предупреждения.

Именно этот контроль поймал ошибку чтения сальдо на Щучине и подтвердил, что
все 8 разобранных касс распарсены полностью.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from cashforensics.classify import unknown_accounts
from cashforensics.models import (
    Config,
    NormalizeResult,
    ValidationCheck,
    ValidationReport,
)

__all__ = [
    "HARD_CHECKS",
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

HARD_CHECKS = ("V1", "V2", "V3")
"""Инварианты, нарушение которых останавливает конвейер — §5.3."""

_ZERO = Decimal("0.00")


class ValidationFailed(RuntimeError):
    """Нарушен жёсткий инвариант V1–V3 — §5.3.

    Конвейер обязан остановиться: дальнейшие стадии на неполном разборе дадут
    правдоподобный, но неверный результат.
    """


def _skipped(code: str, reason: str) -> ValidationCheck:
    return ValidationCheck(
        code=code,
        passed=True,
        skipped=True,
        expected=None,
        actual=None,
        message=reason,
    )


def _compare(code: str, expected: Decimal, actual: Decimal, subject: str) -> ValidationCheck:
    delta = actual - expected
    passed = abs(delta) <= TOLERANCE
    return ValidationCheck(
        code=code,
        passed=passed,
        skipped=False,
        expected=expected,
        actual=actual,
        message=(
            f"{subject} сходится (расхождение {delta})"
            if passed
            else f"{subject}: расхождение {delta} при допуске {TOLERANCE}"
        ),
    )


def check_v1_debit_turnover(normalized: NormalizeResult) -> ValidationCheck:
    """V1: ``ΣДт(распарсено) == turnover_debit`` (допуск 0,01) — §5.3.

    Если ``turnover_debit`` в файле отсутствует — проверка пропускается с
    пометкой в отчёте.
    """
    expected = normalized.totals.turnover_debit
    if expected is None:
        return _skipped("V1", "строка «Обороты за период» отсутствует: дебетовый оборот не сверен")
    actual = sum((entry.debit for entry in normalized.ledger), _ZERO)
    return _compare("V1", expected, actual, "дебетовый оборот")


def check_v2_credit_turnover(normalized: NormalizeResult) -> ValidationCheck:
    """V2: ``ΣКт(распарсено) == turnover_credit`` (допуск 0,01) — §5.3."""
    expected = normalized.totals.turnover_credit
    if expected is None:
        return _skipped("V2", "строка «Обороты за период» отсутствует: кредитовый оборот не сверен")
    actual = sum((entry.credit for entry in normalized.ledger), _ZERO)
    return _compare("V2", expected, actual, "кредитовый оборот")


def check_v3_balance_identity(normalized: NormalizeResult) -> ValidationCheck:
    """V3: ``opening + ΣДт − ΣКт == closing_stated`` (допуск 0,01) — §5.3.

    Остаётся обязательной даже когда ``turnover_*`` отсутствуют. Именно эта
    проверка ловит чтение сальдо не из той колонки (§3.2).
    """
    totals = normalized.totals
    computed = (
        totals.opening
        + sum((entry.debit for entry in normalized.ledger), _ZERO)
        - sum((entry.credit for entry in normalized.ledger), _ZERO)
    )
    return _compare("V3", totals.closing_stated, computed, "сальдо на конец")


def check_v4_modal_date_share(
    normalized: NormalizeResult,
    config: Config,
) -> ValidationCheck:
    """V4: доля записей опер-лога в одной дате > ``MODAL_BAD`` — §5.3.

    При срабатывании даты блока признаются ненадёжными: дневная сверка
    отключается, работает только сверка по итогам периода. Сюда же отнесён
    порог ``MIN_DAYS``: на трёх днях дневная сверка бессмысленна.
    """
    if not normalized.ops:
        return _skipped("V4", "записей опер-лога нет: дневная сверка неприменима")

    days = Counter(entry.dt.date() for entry in normalized.ops)
    modal_share = max(days.values()) / len(normalized.ops)
    enough_days = len(days) >= config.thresholds.MIN_DAYS
    passed = modal_share <= config.thresholds.MODAL_BAD and enough_days

    if not enough_days:
        message = (
            f"дней в опер-логе {len(days)} < MIN_DAYS {config.thresholds.MIN_DAYS}: "
            "дневная сверка отключена, работает только сверка по итогам периода"
        )
    elif passed:
        message = f"даты блока надёжны (модальная доля {modal_share:.1%})"
    else:
        message = (
            f"модальная доля дат {modal_share:.1%} > {config.thresholds.MODAL_BAD:.0%}: "
            "даты блока ненадёжны, дневная сверка отключена"
        )

    return ValidationCheck(
        code="V4",
        passed=passed,
        skipped=False,
        expected=None,
        actual=None,
        message=message,
    )


def check_v5_unknown_accounts(
    normalized: NormalizeResult,
    config: Config,
) -> ValidationCheck:
    """V5: счета вне справочника §3.5 — §5.3.

    Молчаливое поглощение неизвестного счёта запрещено: каждый обязан
    появиться в отчёте отдельной строкой.
    """
    unknown = unknown_accounts(normalized.ledger, config)
    return ValidationCheck(
        code="V5",
        passed=not unknown,
        skipped=False,
        expected=None,
        actual=None,
        message=(
            "все корр. счета есть в справочнике §3.5"
            if not unknown
            else "счета вне справочника §3.5: " + ", ".join(unknown)
        ),
    )


def check_v6_cutoff(normalized: NormalizeResult) -> ValidationCheck:
    """V6: записи опер-лога позже последней проводки 1С — §5.3.

    Признак среза периода (``PERIOD_CUTOFF``, §8): цикл «приход → инкассация»
    оборвался на границе выгрузки.
    """
    if not normalized.ledger or not normalized.ops:
        return _skipped("V6", "недостаточно данных для проверки среза периода")

    last_ledger = max(entry.date for entry in normalized.ledger)
    last_ops = max(entry.dt.date() for entry in normalized.ops)
    suspected = last_ops > last_ledger
    return ValidationCheck(
        code="V6",
        passed=not suspected,
        skipped=False,
        expected=None,
        actual=None,
        message=(
            f"последняя проводка 1С {last_ledger:%d.%m.%Y}, последняя запись лога "
            f"{last_ops:%d.%m.%Y}" + (": признак среза периода" if suspected else "")
        ),
    )


def validate(normalized: NormalizeResult, config: Config) -> ValidationReport:
    """Стадия VALIDATE целиком — §5.3.

    Args:
        normalized: выход стадии NORMALIZE.
        config: конфигурация §6.

    Returns:
        :class:`~cashforensics.models.ValidationReport` со всеми шестью
        проверками в порядке V1…V6.

    Raises:
        ValidationFailed: нарушен V1, V2 или V3 — остановка, а не
            предупреждение (§5.3).
    """
    checks = (
        check_v1_debit_turnover(normalized),
        check_v2_credit_turnover(normalized),
        check_v3_balance_identity(normalized),
        check_v4_modal_date_share(normalized, config),
        check_v5_unknown_accounts(normalized, config),
        check_v6_cutoff(normalized),
    )
    failed = tuple(check for check in checks if check.code in HARD_CHECKS and not check.passed)
    v4 = next(check for check in checks if check.code == "V4")
    v6 = next(check for check in checks if check.code == "V6")

    report = ValidationReport(
        checks=checks,
        hard_failed=bool(failed),
        daily_reconciliation_enabled=v4.passed or v4.skipped,
        unknown_accounts=unknown_accounts(normalized.ledger, config),
        cutoff_suspected=not v6.passed and not v6.skipped,
    )

    if failed:
        details = "; ".join(f"{check.code}: {check.message}" for check in failed)
        message = (
            "разбор выгрузки неполон или некорректен, дальнейший анализ дал бы "
            f"правдоподобный, но неверный результат — {details}"
        )
        raise ValidationFailed(message)

    return report
