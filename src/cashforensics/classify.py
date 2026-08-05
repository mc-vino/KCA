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
)

__all__ = [
    "FALLBACK_MIN_SHARE",
    "BlockClassificationFailed",
    "classify",
    "classify_ledger_entry",
    "classify_ops_entry",
    "is_central_cash",
    "is_service_recipient",
    "service_total",
    "unknown_accounts",
    "verify_time_fallback",
]

FALLBACK_MIN_SHARE = 0.90
"""Минимальная доля точно сходящихся дней для принятия time-fallback — §3.3."""


class BlockClassificationFailed(RuntimeError):
    """Статус ``BLOCK_CLASSIFICATION_FAILED`` — §3.3.

    Time-fallback варианта C не прошёл верификацию. Приложение обязано
    остановиться, а не гадать (принцип «отказ вместо догадки», §0.3).
    """


def classify_ledger_entry(
    counter_account: str,
    is_debit: bool,
    config: Config,
) -> Category:
    """Категория проводки 1С по корр. счёту — §3.5, §5.4.

    Приход = продажи (90.1.1) + авансы (62.4.1) и только они. Дебет по
    76.9.1/76.6 — «прочее». Счёт вне справочника — «прочее» плюс находка
    ``UNKNOWN_ACCOUNT``.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def is_central_cash(counterparty: str, pattern: str) -> bool:
    """Получатель — центральная касса (подстрока ``ентральн``) — §3.6.

    Сравнение регистронезависимое; совпадение → инкассация, иначе — возврат.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def is_service_recipient(counterparty: str, pattern: str) -> bool:
    r"""Служебная запись, не являющаяся возвратом клиенту — §3.6.

    Паттерн ``^суд\b|^суд\s|архив пвз|финконтрол``. Якорь обязателен.
    При добавлении новых служебных паттернов обязательно прогонять регулярку
    по полному списку получателей и глазами проверять отсев (§3.6).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def classify_ops_entry(entry: OpsEntry, config: Config) -> tuple[OpsClass, str]:
    """Классификация записи опер-лога — §3.6.

    Returns:
        Пара ``(classification, classified_by)``, где ``classified_by`` —
        ``"counterparty"`` либо ``"time_fallback"`` (аудиторский след §12).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def verify_time_fallback(
    ops: tuple[OpsEntry, ...],
    ledger: tuple[LedgerEntry, ...],
    config: Config,
) -> FallbackVerification:
    """Верифицировать гипотезу «00:00:00 = инкассация» — §3.3, вариант C.

    Гипотеза обязательно проверяется **до применения**:

    * сумма записей ``00:00:00`` сравнивается с суммой инкассации по 1С;
    * сумма записей с реальным временем — с суммой возвратов по 1С;
    * доля дней с точным сходом возвратов должна быть ≥ :data:`FALLBACK_MIN_SHARE`.

    На PAX_119023531 проверка дала 357 из 368 дней (97 %) — гипотеза принята.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def unknown_accounts(
    ledger: tuple[LedgerEntry, ...],
    config: Config,
) -> tuple[str, ...]:
    """Счета вне справочника §3.5 — §5.4, находка ``UNKNOWN_ACCOUNT``.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def service_total(ops: tuple[OpsEntry, ...]) -> Decimal:
    """Сумма служебных записей — мера мнимого расхождения возвратов (§3.6, §5.6).

    На Солигорске служебные давали мнимое расхождение 11 610,00.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def classify(normalized: NormalizeResult, config: Config) -> ClassifyResult:
    """Стадия CLASSIFY целиком — §5.4.

    Raises:
        BlockClassificationFailed: time-fallback не прошёл верификацию §3.3.
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError
