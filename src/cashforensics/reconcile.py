"""Стадия RECONCILE — §5.6 ТЗ.

Для каждой из трёх категорий (приход, инкассация, возвраты) строит дневные ряды
``acc[d]`` (1С, без нейтрализованных §5.5) и ``ops[d]`` (опер-лог) и считает::

    нетто  = Σacc − Σops
    брутто = Σ|acc[d] − ops[d]|
    ratio  = |нетто| / брутто          # 0 → чистый churn, 1 → односторонний сдвиг

Возвраты считаются в двух вариантах: «как есть» и «скорректировано» (за вычетом
служебных записей §3.6). В отчёт выводятся оба — разница между ними и есть мера
мнимого расхождения.

Низкий ``ratio`` при большом брутто = сильные встречные потоки. На Солигорске
возвраты дали нетто +1 673,29 при брутто, разложенном на +17 052,81
переучтённого и −15 379,10 недоучтённого: одиночная дневная разница в таком
режиме малоинформативна, нужна сегментация по окнам (§5.8).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from cashforensics.models import (
    Category,
    CategoryRecon,
    ClassifyResult,
    Config,
    LedgerEntry,
    OpsEntry,
    ReversalResult,
)

__all__ = [
    "RECONCILED_CATEGORIES",
    "daily_differences",
    "daily_ledger_series",
    "daily_ops_series",
    "log_imbalance",
    "reconcile",
    "reconcile_category",
]

RECONCILED_CATEGORIES: tuple[Category, ...] = (
    Category.INCOME,
    Category.COLLECTION,
    Category.REFUND,
)
"""Три категории, по которым строится сверка — §5.6."""


def daily_ledger_series(
    ledger: tuple[LedgerEntry, ...],
    category: Category,
    neutralized: frozenset[int],
) -> dict[date, Decimal]:
    """Дневной ряд 1С по категории, без нейтрализованных — §5.6.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def daily_ops_series(
    ops: tuple[OpsEntry, ...],
    category: Category,
    exclude_service: bool,
) -> dict[date, Decimal]:
    """Дневной ряд опер-лога по категории — §5.6.

    ``exclude_service=True`` даёт вариант «скорректировано» (§3.6).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def daily_differences(
    acc: dict[date, Decimal],
    ops: dict[date, Decimal],
) -> tuple[tuple[date, Decimal], ...]:
    """Разности ``acc[d] − ops[d]`` по всем датам обоих рядов — §5.6.

    Порядок строго по дате (детерминированность §12).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def reconcile_category(
    category: Category,
    classified: ClassifyResult,
    reversals: ReversalResult,
    config: Config,
) -> CategoryRecon:
    """Сверка одной категории — §5.6.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def log_imbalance(ops: tuple[OpsEntry, ...]) -> Decimal:
    """Дисбаланс самих логов: ``ΣПКО − ΣРКО_инкассация − ΣРКО_возвраты`` — §5.10.

    Отдельная строка раскладки и находка ``LOG_IMBALANCE``. Измеряется, но не
    объясняется: причина лежит вне обоих файлов (§16).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def reconcile(
    classified: ClassifyResult,
    reversals: ReversalResult,
    config: Config,
) -> dict[Category, CategoryRecon]:
    """Стадия RECONCILE целиком — §5.6.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError
