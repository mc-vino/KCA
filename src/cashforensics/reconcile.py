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
    "block_present",
    "daily_differences",
    "daily_ledger_series",
    "daily_ops_series",
    "ledger_period_end",
    "log_imbalance",
    "ops_classes_for",
    "outside_ledger_period",
    "reconcile",
    "reconcile_category",
    "series_to_pairs",
    "within_ledger_period",
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


def block_present(ops: Sequence[OpsEntry], category: Category) -> bool:
    """Есть ли в выгрузке блок опер-лога для этой категории — §3.3, вариант D.

    Приход сверяется с блоком ПКО, инкассация и возвраты — с блоком РКО.
    Отсутствие блока и отсутствие операций в нём — разные вещи: во втором
    случае «проводка без выдачи» остаётся законной находкой §8, в первом
    сверять не с чем вовсе.

    Ловушка `Кса_с_отклонением` и `Максиму_касса_2`: блока ПКО в выгрузке нет
    (вариант D §3.3), и без этой проверки каждый день прихода объявлялся
    расхождением на всю свою сумму — 810 и 1 042 «проблемных дня» на
    2 979 052,00 и 4 870 682,41. §11.3 формулирует это прямо: «нет ПКО → приход
    не верифицируется».

    Признак наличия блока — хотя бы одна запись соответствующего вида: блок,
    присутствующий в листе, но пустой во всём периоде, на этих выгрузках не
    встречается, а пустой блок и его отсутствие означают одно и то же.
    """
    kind = OpsKind.PKO if category is Category.INCOME else OpsKind.RKO
    return any(entry.kind is kind for entry in ops)


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
    """Сверка одной категории — §5.6.

    Ряд лога срезан периодом карточки — см. :func:`within_ledger_period`.
    """
    acc = daily_ledger_series(classified.ledger, category, reversals.neutralized_rows)
    inside = within_ledger_period(classified.ops, classified.ledger)
    ops = daily_ops_series(inside, category, exclude_service=False)

    acc_total = sum(acc.values(), _ZERO)
    ops_total = sum(ops.values(), _ZERO)
    net = acc_total - ops_total
    gross = sum((abs(diff) for _, diff in daily_differences(acc, ops)), _ZERO)

    # Сверяемый ряд — «скорректированный», где он есть (§3.6). Служебной выдаче
    # проводки 1С не соответствует по определению, и считать её расхождением
    # значит объявить расхождением заведомо мнимое. Вариант «как есть» остаётся
    # в отчёте: разница между ними и есть мера мнимого расхождения (§5.6).
    #
    # Ловушка, стоившая пяти ложных дней на Солигорске: §5.7 сворачивала ряд
    # «как есть», а §5.9 разбирала день по «скорректированному». Дни, попавшие
    # в остаток только из-за судебной выплаты 11 310,00, приходили в
    # локализацию с нулевой разницей и оседали в отчёте как «не локализовано».
    adjusted_series: dict[date, Decimal] | None = None
    adjusted_net: Decimal | None = None
    adjusted_gross: Decimal | None = None
    if category is Category.REFUND:
        adjusted_series = daily_ops_series(inside, category, exclude_service=True)
        adjusted_net = acc_total - sum(adjusted_series.values(), _ZERO)
        adjusted_gross = sum(
            (abs(diff) for _, diff in daily_differences(acc, adjusted_series)),
            _ZERO,
        )

    reconciled = ops if adjusted_series is None else adjusted_series
    verifiable = block_present(classified.ops, category)
    beyond = outside_ledger_period(classified.ops, classified.ledger, category)
    differences = daily_differences(acc, reconciled) if verifiable else ()

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
        ops_series_adjusted=(None if adjusted_series is None else series_to_pairs(adjusted_series)),
        daily_differences=differences,
        adjusted_net=adjusted_net,
        adjusted_gross=adjusted_gross,
        verifiable=verifiable,
        outside_period=beyond,
    )


def ledger_period_end(ledger: Sequence[LedgerEntry]) -> date | None:
    """Последняя дата карточки 1С — граница сверяемого периода (§5.3)."""
    return max((entry.date for entry in ledger), default=None)


def within_ledger_period(
    ops: Sequence[OpsEntry],
    ledger: Sequence[LedgerEntry],
) -> tuple[OpsEntry, ...]:
    """Записи лога внутри периода карточки — §5.6, §5.3.

    Сверять можно только там, где есть обе стороны. Записи лога за последней
    проводкой карточки сравнивать не с чем: отсутствует не проводка, а вся
    вторая сторона — за этими датами в 1С нет ничего ни по одной категории.
    Это срез выгрузки §5.3, который V6 и отмечает.

    Что давал несрезанный ряд. `Кса_норма` — эталон §11.3 «без ошибок» — имеет
    карточку до 30.04.2026 и лог до 02.06.2026, и §5.6 сравнивала пять недель
    1С против десяти недель лога: инкассация 269 243,54 против 587 835,72,
    нетто −318 592,18 при отклонении сальдо +10 632,25. Раздутое нетто держало
    ``ratio`` = 0,59, гейт встречных потоков §5.6 не срабатывал, и день
    разбирался поштучно — отсюда 69 «непроведённых выдач» и завышенный РКО на
    16 888,05 на кассе, объявленной безошибочной.

    Со срезом те же величины становятся осмысленными: возвраты сходятся **в
    ноль**, инкассация даёт −10 632,25 — ровно отклонение сальдо этой кассы.

    Границу задаёт вся карточка, а не категория. Категория, остановленная
    раньше прочих, — законная находка: на Щучине приход прекращён 06.05.2026,
    а инкассация проведена до 12.05, и §11.3 требует назвать эти дни
    (−15 440,69). Их даты лежат внутри карточки и под срез не попадают.

    Тождество §5.10 срез не ломает: все логовые слагаемые в нём сокращаются
    тождественно, и достаточно применить один и тот же ряд и к дельтам
    категорий, и к :func:`log_imbalance`.
    """
    end = ledger_period_end(ledger)
    if end is None:
        return tuple(ops)
    return tuple(entry for entry in ops if entry.dt.date() <= end)


def outside_ledger_period(
    ops: Sequence[OpsEntry],
    ledger: Sequence[LedgerEntry],
    category: Category,
) -> Decimal:
    """Сумма записей лога категории за границей карточки — §5.3.

    Молча отбрасывать их нельзя (§5): величина идёт в отчёт как оговорка §16 и
    в объяснение находки ``PERIOD_CUTOFF``.
    """
    end = ledger_period_end(ledger)
    if end is None:
        return _ZERO
    classes = ops_classes_for(category, exclude_service=False)
    return sum(
        (
            entry.amount
            for entry in ops
            if entry.classification in classes and entry.dt.date() > end
        ),
        _ZERO,
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
