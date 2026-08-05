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

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from cashforensics.models import (
    Category,
    CategoryRecon,
    ClassifyResult,
    Config,
    LedgerEntry,
    OpsClass,
    OpsEntry,
    OpsKind,
    ReversalResult,
)

__all__ = [
    "RECONCILED_CATEGORIES",
    "daily_differences",
    "daily_ledger_series",
    "daily_ops_series",
    "log_imbalance",
    "ops_classes_for",
    "reconcile",
    "reconcile_category",
    "series_to_pairs",
]

RECONCILED_CATEGORIES: tuple[Category, ...] = (
    Category.INCOME,
    Category.COLLECTION,
    Category.REFUND,
)
"""Три категории, по которым строится сверка — §5.6."""

_ZERO = Decimal("0.00")


def ops_classes_for(category: Category, *, exclude_service: bool) -> tuple[OpsClass, ...]:
    """Классы опер-лога, соответствующие категории 1С — §5.6, §3.6.

    Служебные записи физически лежат в блоке РКО и в варианте «как есть»
    считаются вместе с возвратами: именно их разница с вариантом
    «скорректировано» и есть мера мнимого расхождения (§5.6).
    """
    if category is Category.INCOME:
        return (OpsClass.INCOME,)
    if category is Category.COLLECTION:
        return (OpsClass.COLLECTION,)
    if category is Category.REFUND:
        return (OpsClass.REFUND,) if exclude_service else (OpsClass.REFUND, OpsClass.SERVICE)
    return ()


def daily_ledger_series(
    ledger: Sequence[LedgerEntry],
    category: Category,
    neutralized: frozenset[int],
) -> dict[date, Decimal]:
    """Дневной ряд 1С по категории, без нейтрализованных — §5.6."""
    totals: dict[date, Decimal] = {}
    for entry in ledger:
        if entry.category is not category or entry.row in neutralized:
            continue
        totals[entry.date] = totals.get(entry.date, _ZERO) + entry.debit + entry.credit
    return totals


def daily_ops_series(
    ops: Sequence[OpsEntry],
    category: Category,
    *,
    exclude_service: bool,
) -> dict[date, Decimal]:
    """Дневной ряд опер-лога по категории — §5.6.

    ``exclude_service=True`` даёт вариант «скорректировано» (§3.6).
    """
    classes = ops_classes_for(category, exclude_service=exclude_service)
    totals: dict[date, Decimal] = {}
    for entry in ops:
        if entry.classification not in classes:
            continue
        day = entry.dt.date()
        totals[day] = totals.get(day, _ZERO) + entry.amount
    return totals


def series_to_pairs(series: dict[date, Decimal]) -> tuple[tuple[date, Decimal], ...]:
    """Ряд в упорядоченный по дате кортеж пар — §12, детерминированность."""
    return tuple((day, series[day]) for day in sorted(series))


def daily_differences(
    acc: dict[date, Decimal],
    ops: dict[date, Decimal],
) -> tuple[tuple[date, Decimal], ...]:
    """Разности ``acc[d] − ops[d]`` по всем датам обоих рядов — §5.6.

    Порядок строго по дате (детерминированность §12). Нулевые разницы
    отбрасываются: они не несут информации и только раздувают ряд.
    """
    return tuple(
        (day, acc.get(day, _ZERO) - ops.get(day, _ZERO))
        for day in sorted(set(acc) | set(ops))
        if acc.get(day, _ZERO) != ops.get(day, _ZERO)
    )


def reconcile_category(
    category: Category,
    classified: ClassifyResult,
    reversals: ReversalResult,
    config: Config,
) -> CategoryRecon:
    """Сверка одной категории — §5.6."""
    acc = daily_ledger_series(classified.ledger, category, reversals.neutralized_rows)
    ops = daily_ops_series(classified.ops, category, exclude_service=False)
    differences = daily_differences(acc, ops)

    acc_total = sum(acc.values(), _ZERO)
    ops_total = sum(ops.values(), _ZERO)
    net = acc_total - ops_total
    gross = sum((abs(diff) for _, diff in differences), _ZERO)

    adjusted_net: Decimal | None = None
    adjusted_gross: Decimal | None = None
    if category is Category.REFUND:
        adjusted_ops = daily_ops_series(classified.ops, category, exclude_service=True)
        adjusted_net = acc_total - sum(adjusted_ops.values(), _ZERO)
        adjusted_gross = sum(
            (abs(diff) for _, diff in daily_differences(acc, adjusted_ops)),
            _ZERO,
        )

    return CategoryRecon(
        category=category,
        acc_total=acc_total,
        ops_total=ops_total,
        net=net,
        gross=gross,
        ratio=float(abs(net) / gross) if gross != _ZERO else None,
        days_with_difference=sum(
            1 for _, diff in differences if abs(diff) >= config.thresholds.EPS_FLOOR
        ),
        acc_series=series_to_pairs(acc),
        ops_series=series_to_pairs(ops),
        daily_differences=differences,
        adjusted_net=adjusted_net,
        adjusted_gross=adjusted_gross,
    )


def log_imbalance(ops: Sequence[OpsEntry]) -> Decimal:
    """Дисбаланс самих логов: ``ΣПКО − ΣРКО`` — §5.10.

    Отдельная строка раскладки и находка ``LOG_IMBALANCE``. Измеряется, но не
    объясняется: причина лежит вне обоих файлов (§16).

    Вычитаются **все** РКО, включая служебные. Показатель меряет физическую
    сходимость самого лога — сколько денег в него вошло и сколько вышло, — а
    судебная выплата или инкассация в архив ПВЗ выносят наличные из ящика
    ничуть не меньше, чем возврат клиенту. Это не противоречит §3.6: там
    служебные исключаются из **сверки возвратов**, потому что им не
    соответствуют проводки возвратов в 1С.

    Проверено на Солигорске: 14 062 584,98 − 12 977 844,10 − 1 073 938,79 −
    11 610,00 = −807,91, что совпадает с эталоном §11.3. Без служебных
    получалось +10 802,09.
    """
    incoming = sum((entry.amount for entry in ops if entry.kind is OpsKind.PKO), _ZERO)
    outgoing = sum((entry.amount for entry in ops if entry.kind is OpsKind.RKO), _ZERO)
    return incoming - outgoing


def reconcile(
    classified: ClassifyResult,
    reversals: ReversalResult,
    config: Config,
) -> dict[Category, CategoryRecon]:
    """Стадия RECONCILE целиком — §5.6.

    Порядок ключей — :data:`RECONCILED_CATEGORIES`; словарь не должен зависеть
    от порядка вставки (§12).
    """
    return {
        category: reconcile_category(category, classified, reversals, config)
        for category in RECONCILED_CATEGORIES
    }
