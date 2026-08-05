"""Сигнатуры риска — §8.1–8.2 ТЗ.

Ловят то, что сверка принципиально не ловит: повторные выдачи внутри дневного
агрегата, документы вне рабочих часов, разрывы нумерации, дубликаты.

Сигнатура — не улика (§16)
--------------------------
Базовая частота повторов в этих данных высока. Формулировка обязана быть
«повтор может быть законным (возврат нескольких одинаковых позиций); требует
точечной проверки», а не «двойная выдача» (§8.1). Квалификация — за человеком
(§1.2).
"""

from __future__ import annotations

from decimal import Decimal

from cashforensics.models import (
    ClassifyResult,
    Config,
    LedgerEntry,
    OpsEntry,
    Signature,
)

__all__ = [
    "collect_signatures",
    "duplicate_documents",
    "iqr_bounds",
    "late_time_documents",
    "modified_z_scores",
    "repeat_baseline_pko",
    "repeat_payouts",
    "round_number_bias",
    "sequence_gaps",
]


def repeat_payouts(ops: tuple[OpsEntry, ...], config: Config) -> tuple[Signature, ...]:
    """Повторная выдача одной суммы одному получателю — §8.1.

    Окно ``repeat_window_minutes``, минимум ``repeat_min_count`` повторов.

    **Сигнатура выдаётся только по РКО.** В ПКО повторы — норма: клиент
    забирает несколько одинаковых заказов (PAX_119049688: 15 в ПКО против 1 в
    РКО; Солигорск: 183 против 35).

    Самая заметная находка класса: 14.05 — четыре РКО по 164,99 одному
    получателю за 22 секунды (13:26:55 → 13:27:17); 1С провела агрегат
    1 358,96, поэтому сверка расхождения не даёт вовсе.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def repeat_baseline_pko(ops: tuple[OpsEntry, ...], config: Config) -> str:
    """Базовая частота повторов по ПКО — §8.1, обязательный контекст отчёта.

    Без неё сигнатура читается как обвинение.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def late_time_documents(
    ops: tuple[OpsEntry, ...],
    config: Config,
) -> tuple[Signature, ...]:
    """Документы в 23:59:59 и вне рабочих часов — §8, ``LATE_TIME_DOC``.

    Границы — ``signatures.business_hours`` и ``signatures.late_time`` (§6).

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def sequence_gaps(
    ledger: tuple[LedgerEntry, ...],
    config: Config,
) -> tuple[Signature, ...]:
    """Пропуски в нумерации документов — §8.2, ``SEQUENCE_GAP``.

    Номера группируются по префиксу/маске, сортируются, ищутся пропуски.
    Пропуск может означать удалённый или непроведённый документ.

    Нумерация в 1С может быть сквозной по организации, а не по кассе — тогда
    пропуски ожидаемы, и тест **понижается до информационного** (§8.2, §15).

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def duplicate_documents(
    ledger: tuple[LedgerEntry, ...],
    config: Config,
) -> tuple[Signature, ...]:
    """Дубликаты документов, точные и нечёткие — §8, ``DUPLICATE_DOC``.

    Ловит задвоение ПКО (§15). Нечёткое сравнение — по порогу
    ``statistics.fuzzy_name_threshold``.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def modified_z_scores(values: tuple[Decimal, ...]) -> tuple[float, ...]:
    """Модифицированный z-score (медиана + MAD) — §6, §15.

    Порог ``statistics.mod_z_threshold`` = 3.5. Робастная статистика,
    объяснима — в отличие от Isolation Forest / LOF, прямо запрещённых §15.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def iqr_bounds(
    values: tuple[Decimal, ...],
    multiplier: float,
) -> tuple[Decimal, Decimal]:
    """Границы IQR (1.5 — мягкая, 3.0 — экстремальная) — §6, §15.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def round_number_bias(
    values: tuple[Decimal, ...],
    config: Config,
) -> tuple[Signature, ...]:
    """Смещение к круглым числам — §15, **только как слабый признак**.

    Много ложных срабатываний; применяется исключительно в связке с другими
    признаками, самостоятельной находкой не является.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def collect_signatures(
    classified: ClassifyResult,
    config: Config,
) -> tuple[Signature, ...]:
    """Собрать все сигнатуры — §8.1–8.2.

    Закон Бенфорда не реализуется: §15 запрещает его при N < ~1700, а на этих
    данных пороги и лимиты транзакций искажают распределение первой цифры.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError
