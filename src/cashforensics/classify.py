"""Стадия CLASSIFY — §5.4 ТЗ, справочники §3.5 и §3.6.

Присваивает ``category`` проводкам 1С и ``classification`` записям опер-лога.

Два правила, нарушение которых уже ломало результат:

* **Приход в 1С — только продажи + авансы.** Дебетовые проводки по 76.9.1/76.6
  идут в «прочее». Включение дебета 76.9.1 в приход давало на Кассе 3
  579 868,96 вместо корректных 579 749,96 и ломало сходимость раскладки (§5.4).
* **Якорь ``^`` в регулярке служебных обязателен.** Версия без якоря отбросила
  выдачу клиенту «Правосуд Дмитрий» (203,93), потому что строка содержит
  «суд » (§3.6).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, time
from decimal import Decimal

from cashforensics.models import (
    Category,
    ClassifyResult,
    Config,
    FallbackVerification,
    LedgerEntry,
    NormalizeResult,
    OpsClass,
    OpsEntry,
    OpsKind,
)

__all__ = [
    "EXACT_DAY_TOLERANCE",
    "FALLBACK_MIN_SHARE",
    "GROUP_TO_CATEGORY",
    "BlockClassificationFailed",
    "account_index",
    "classify",
    "classify_ledger_entry",
    "classify_ops_entry",
    "is_central_cash",
    "is_service_recipient",
    "needs_time_fallback",
    "service_total",
    "unknown_accounts",
    "verify_time_fallback",
]

FALLBACK_MIN_SHARE = 0.90
"""Минимальная доля точно сходящихся дней для принятия time-fallback — §3.3."""

EXACT_DAY_TOLERANCE = Decimal("0.005")
"""«Сходится точно» — до копейки (§3.3)."""

GROUP_TO_CATEGORY: dict[str, Category] = {
    "инкассация": Category.COLLECTION,
    "возвраты": Category.REFUND,
    "продажи": Category.INCOME,
    "авансы": Category.INCOME,
    "размен": Category.EXCHANGE,
    "претензии": Category.OTHER,
    "прочие": Category.OTHER,
}
"""Группы справочника §3.5 → категории §4.1."""

_ZERO = Decimal("0.00")


class BlockClassificationFailed(RuntimeError):
    """Статус ``BLOCK_CLASSIFICATION_FAILED`` — §3.3.

    Time-fallback варианта C не прошёл верификацию. Приложение обязано
    остановиться, а не гадать (принцип «отказ вместо догадки», §0.3).
    """


def account_index(config: Config) -> dict[str, Category]:
    """Обратный индекс «счёт → категория» из справочника §3.5.

    Счёт, встречающийся в нескольких группах (76.3.1 — и «претензии», и
    «прочие»), разрешается в пользу первой встреченной; обе группы ведут в
    «прочее», поэтому неоднозначности не возникает.
    """
    index: dict[str, Category] = {}
    for group, accounts in config.accounts.items():
        category = GROUP_TO_CATEGORY.get(group, Category.OTHER)
        for account in accounts:
            index.setdefault(account, category)
    return index


def classify_ledger_entry(
    counter_account: str,
    is_debit: bool,
    config: Config,
) -> Category:
    """Категория проводки 1С по корр. счёту — §3.5, §5.4.

    Приход = продажи (90.1.1) + авансы (62.4.1) и **только** они, и только по
    дебету кассы. Дебет по 76.9.1/76.6 — это возврат денег обратно в ящик, он
    идёт в «прочее»: включение его в приход ломало сходимость раскладки (§5.4).

    Счёт вне справочника — «прочее» плюс находка ``UNKNOWN_ACCOUNT``; молчаливое
    поглощение запрещено (§3.5).
    """
    category = account_index(config).get(counter_account)
    if category is None:
        return Category.OTHER
    if category is Category.INCOME and not is_debit:
        # Кредит на счёт продаж — не приход кассы.
        return Category.OTHER
    if category is Category.REFUND and is_debit:
        # Деньги вернулись в ящик: ловушка §5.4.
        return Category.OTHER
    return category


def is_central_cash(counterparty: str, pattern: str) -> bool:
    """Получатель — центральная касса (подстрока ``ентральн``) — §3.6.

    Сравнение регистронезависимое; совпадение → инкассация, иначе — возврат.
    """
    if not counterparty:
        return False
    return re.search(pattern, counterparty, re.IGNORECASE) is not None


def is_service_recipient(counterparty: str, pattern: str) -> bool:
    r"""Служебная запись, не являющаяся возвратом клиенту — §3.6.

    Паттерн ``^суд\b|^суд\s|архив пвз|финконтрол``. Якорь обязателен.
    При добавлении новых служебных паттернов обязательно прогонять регулярку
    по полному списку получателей и глазами проверять отсев (§3.6).
    """
    if not counterparty:
        return False
    return re.search(pattern, counterparty, re.IGNORECASE) is not None


def classify_ops_entry(entry: OpsEntry, config: Config) -> tuple[OpsClass, str]:
    """Классификация записи опер-лога — §3.6.

    Блок ПКО — всегда приход. Для блока РКО: получатель содержит «ентральн» →
    инкассация; служебный получатель → служебная; иначе — возврат клиенту.

    Когда колонки получателя нет (вариант C, §3.3), применяется time-fallback:
    ``00:00:00`` → инкассация, иначе — возврат. Гипотеза обязана быть
    верифицирована :func:`verify_time_fallback` **до** применения.

    Returns:
        Пара ``(classification, classified_by)``, где ``classified_by`` —
        ``"block"``, ``"counterparty"`` либо ``"time_fallback"`` (аудиторский
        след §12).
    """
    if entry.kind is OpsKind.PKO:
        return (OpsClass.INCOME, "block")

    if entry.counterparty:
        if is_central_cash(entry.counterparty, config.patterns.central_cash):
            return (OpsClass.COLLECTION, "counterparty")
        if is_service_recipient(entry.counterparty, config.patterns.service_recipients):
            return (OpsClass.SERVICE, "counterparty")
        return (OpsClass.REFUND, "counterparty")

    if entry.dt.time() == time.min:
        return (OpsClass.COLLECTION, "time_fallback")
    return (OpsClass.REFUND, "time_fallback")


def needs_time_fallback(ops: Sequence[OpsEntry]) -> bool:
    """Требуется ли time-fallback — §3.3, вариант C.

    Признак: блок РКО есть, но получатель не заполнен ни у одной записи.
    """
    rko = [entry for entry in ops if entry.kind is OpsKind.RKO]
    return bool(rko) and all(not entry.counterparty for entry in rko)


def _daily_sum(pairs: Sequence[tuple[date, Decimal]]) -> dict[date, Decimal]:
    totals: dict[date, Decimal] = {}
    for day, amount in pairs:
        totals[day] = totals.get(day, _ZERO) + amount
    return totals


def verify_time_fallback(
    ops: Sequence[OpsEntry],
    ledger: Sequence[LedgerEntry],
) -> FallbackVerification:
    """Верифицировать гипотезу «00:00:00 = инкассация» — §3.3, вариант C.

    Гипотеза обязательно проверяется **до применения**:

    * сумма записей ``00:00:00`` сравнивается с суммой инкассации по 1С;
    * сумма записей с реальным временем — с суммой возвратов по 1С;
    * доля дней с точным сходом возвратов должна быть ≥
      :data:`FALLBACK_MIN_SHARE`.

    На PAX_119023531 проверка дала 357 из 368 дней (97 %) — гипотеза принята.

    Порог ≥ 90 % и допуск «до копейки» заданы §3.3 напрямую и в конфиг §6 не
    вынесены: смягчать их настройкой значило бы обходить гейт, а не проходить.

    Args:
        ops: записи опер-лога; классификация ещё не проставлена.
        ledger: проводки 1С с уже назначенными категориями (§5.4).
    """
    rko = [entry for entry in ops if entry.kind is OpsKind.RKO]
    midnight = [entry for entry in rko if entry.dt.time() == time.min]
    timed = [entry for entry in rko if entry.dt.time() != time.min]

    collection_ledger = sum(
        (entry.credit for entry in ledger if entry.category is Category.COLLECTION),
        _ZERO,
    )
    refund_ledger = sum(
        (entry.credit for entry in ledger if entry.category is Category.REFUND),
        _ZERO,
    )

    refund_by_day = _daily_sum(
        [(entry.date, entry.credit) for entry in ledger if entry.category is Category.REFUND],
    )
    timed_by_day = _daily_sum([(entry.dt.date(), entry.amount) for entry in timed])

    days = sorted(set(refund_by_day) | set(timed_by_day))
    exact = sum(
        1
        for day in days
        if abs(refund_by_day.get(day, _ZERO) - timed_by_day.get(day, _ZERO)) < EXACT_DAY_TOLERANCE
    )
    share = exact / len(days) if days else 0.0

    return FallbackVerification(
        accepted=share >= FALLBACK_MIN_SHARE,
        days_total=len(days),
        days_exact=exact,
        exact_day_share=share,
        collection_delta=collection_ledger - sum((entry.amount for entry in midnight), _ZERO),
        refund_delta=refund_ledger - sum((entry.amount for entry in timed), _ZERO),
    )


def unknown_accounts(
    ledger: Sequence[LedgerEntry],
    config: Config,
) -> tuple[str, ...]:
    """Счета вне справочника §3.5 — §5.4, находка ``UNKNOWN_ACCOUNT``.

    Порядок — лексикографический: результат попадает в отчёт и обязан быть
    воспроизводимым (§12).
    """
    known = account_index(config)
    return tuple(
        sorted({entry.counter_account for entry in ledger if entry.counter_account not in known}),
    )


def service_total(ops: Sequence[OpsEntry]) -> Decimal:
    """Сумма служебных записей — мера мнимого расхождения возвратов (§3.6, §5.6).

    На Солигорске служебные давали мнимое расхождение 11 610,00.
    """
    return sum(
        (entry.amount for entry in ops if entry.classification is OpsClass.SERVICE),
        _ZERO,
    )


def classify(normalized: NormalizeResult, config: Config) -> ClassifyResult:
    """Стадия CLASSIFY целиком — §5.4.

    Порядок важен: сначала категории проводок 1С, потому что верификация
    time-fallback §3.3 сравнивает опер-лог именно с ними.

    Raises:
        BlockClassificationFailed: time-fallback не прошёл верификацию §3.3.
    """
    ledger = tuple(
        entry.model_copy(
            update={
                "category": classify_ledger_entry(
                    entry.counter_account,
                    is_debit=entry.debit != _ZERO,
                    config=config,
                ),
            },
        )
        for entry in normalized.ledger
    )

    fallback: FallbackVerification | None = None
    if needs_time_fallback(normalized.ops):
        fallback = verify_time_fallback(normalized.ops, ledger)
        if not fallback.accepted:
            message = (
                "BLOCK_CLASSIFICATION_FAILED: time-fallback §3.3 не верифицирован — "
                f"точно сходятся {fallback.days_exact} из {fallback.days_total} дней "
                f"({fallback.exact_day_share:.1%} при пороге {FALLBACK_MIN_SHARE:.0%}). "
                "Разделение инкассации и возвратов по времени применять нельзя."
            )
            raise BlockClassificationFailed(message)

    ops: list[OpsEntry] = []
    for entry in normalized.ops:
        classification, classified_by = classify_ops_entry(entry, config)
        ops.append(
            entry.model_copy(
                update={"classification": classification, "classified_by": classified_by},
            ),
        )

    return ClassifyResult(
        ledger=ledger,
        ops=tuple(ops),
        fallback=fallback,
        unknown_accounts=unknown_accounts(ledger, config),
    )
