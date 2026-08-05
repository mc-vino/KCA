"""Стадия COLLAPSE_TIMING — §5.7 ТЗ.

Устраняет мнимые расхождения. Без неё инструмент показывает сотни ложных строк:
на Солигорске инкассация давала 1 325 «расхождений» при нетто 0,00.

Состав: детектор лага (§5.7.1), свёртка в три прохода (§5.7.2), календарная
агрегация выходных (§5.7.3). Калибровочные ожидания — таблица §5.7.4.

Свёртка отключается флагом ``--no-collapse`` (§12, обратимость).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import yaml

from cashforensics.models import (
    AuditLogEntry,
    CalendarAggregation,
    Category,
    CategoryRecon,
    CollapseResult,
    Config,
    LagResult,
)

__all__ = [
    "REDATE_TOLERANCE",
    "collapse_pass1_cumulative",
    "collapse_pass2_pairwise",
    "collapse_pass3_redate",
    "collapse_timing",
    "detect_calendar_aggregation",
    "detect_lag",
    "lag_score",
    "load_holidays",
    "run_timing",
]

REDATE_TOLERANCE = Decimal("0.005")
"""Допуск прохода 3 — точное совпадение до копейки (§5.7.2)."""

_ZERO = Decimal("0.00")
_MONDAY = 0
_SATURDAY = 5


def _as_series(pairs: Sequence[tuple[date, Decimal]]) -> dict[date, Decimal]:
    return dict(pairs)


def lag_score(
    acc: dict[date, Decimal],
    ops: dict[date, Decimal],
    lag: int,
) -> Decimal:
    """``lagScore(L) = Σ_d |acc[d] − ops[d − L]|`` — §5.7.1.

    L1-метрика выбрана намеренно: робастна и объяснима (§15).
    """
    shift = timedelta(days=lag)
    days = set(acc) | {day + shift for day in ops}
    return sum(
        (abs(acc.get(day, _ZERO) - ops.get(day - shift, _ZERO)) for day in sorted(days)),
        _ZERO,
    )


def detect_lag(
    acc: dict[date, Decimal],
    ops: dict[date, Decimal],
    config: Config,
) -> LagResult:
    """Найти лучший лаг ``L = 0..MAX_LAG`` — §5.7.1.

    Лаг значим при ``lagScore(best) < LAG_SIGNIFICANT_RATIO · lagScore(0)``.
    Результат диагностический: свёртку не меняет, объясняет её пользователю.

    Эмпирика Кассы 3: lag0 = 475 575, lag1 = 326 177 → сдвиг +1 день.
    """
    scores = tuple(lag_score(acc, ops, lag) for lag in range(config.thresholds.MAX_LAG + 1))
    best = min(range(len(scores)), key=lambda lag: (scores[lag], lag))
    threshold = scores[0] * Decimal(str(config.thresholds.LAG_SIGNIFICANT_RATIO))
    return LagResult(
        best_lag=best,
        scores=scores,
        significant=best != 0 and scores[best] < threshold,
    )


def collapse_pass1_cumulative(
    diffs: Sequence[tuple[date, Decimal]],
    eps_floor: Decimal,
) -> frozenset[int]:
    """Проход 1 — кумулятивная сегментация (§5.7.2).

    Накапливает ``c``; как только ``|c| < EPS_FLOOR``, весь сегмент
    ``last+1..k`` помечается погашенным. Накопитель намеренно не сбрасывается:
    так гасятся длинные цепочки взаимно компенсирующихся сдвигов.

    Returns:
        Индексы погашенных элементов.
    """
    settled: set[int] = set()
    cumulative = _ZERO
    last = -1
    for index, (_, diff) in enumerate(diffs):
        cumulative += diff
        if abs(cumulative) < eps_floor:
            settled.update(range(last + 1, index + 1))
            last = index
    return frozenset(settled)


def _by_magnitude(diffs: Sequence[tuple[date, Decimal]]) -> list[int]:
    """Порядок обхода: по убыванию ``|diff|``, при равенстве — дата, затем индекс.

    Полный явный ключ (§12): без него порядок обхода зависел бы от порядка
    вставки, и свёртка перестала бы быть воспроизводимой.
    """
    return sorted(
        range(len(diffs)),
        key=lambda index: (-abs(diffs[index][1]), diffs[index][0], index),
    )


def collapse_pass2_pairwise(
    diffs: Sequence[tuple[date, Decimal]],
    settled: frozenset[int],
    config: Config,
) -> frozenset[int]:
    """Проход 2 — парное гашение в окне ``DATE_WIN`` (§5.7.2).

    Обход по убыванию ``|diff[k]|``; при равенстве — по дате, затем по индексу.
    Пара засчитывается при ``|diff[k] + diff[j]| < EPS_SUM``. Из нескольких
    подходящих ``j`` берётся ближайший по дате, при равенстве — меньший индекс.
    """
    result = set(settled)
    window = config.thresholds.DATE_WIN
    for k in _by_magnitude(diffs):
        if k in result:
            continue
        day_k, diff_k = diffs[k]
        partners = [
            j
            for j in range(len(diffs))
            if j != k
            and j not in result
            and abs((diffs[j][0] - day_k).days) <= window
            and abs(diff_k + diffs[j][1]) < config.thresholds.EPS_SUM
        ]
        if partners:
            best = min(partners, key=lambda j: (abs((diffs[j][0] - day_k).days), j))
            result.update({k, best})
    return frozenset(result)


def collapse_pass3_redate(
    diffs: Sequence[tuple[date, Decimal]],
    settled: frozenset[int],
    config: Config,
) -> frozenset[int]:
    """Проход 3 — перенос даты, точное совпадение (§5.7.2).

    Окно ``LONG_WIN``, допуск :data:`REDATE_TOLERANCE` (до копейки).

    Проход намеренно консервативен, но всё же может свести две разные операции,
    случайно равные по сумме. Поэтому свёрнутые им дни считаются отдельно
    (``redated``) и показываются в отчёте, а остаток маркируется «для разбора»,
    а не «ошибка».

    Returns:
        Только индексы, погашенные этим проходом (без входных ``settled``).
    """
    result = set(settled)
    redated: set[int] = set()
    window = config.thresholds.LONG_WIN
    for k in _by_magnitude(diffs):
        if k in result:
            continue
        day_k, diff_k = diffs[k]
        partners = [
            j
            for j in range(len(diffs))
            if j != k
            and j not in result
            and abs((diffs[j][0] - day_k).days) <= window
            and abs(diff_k + diffs[j][1]) < REDATE_TOLERANCE
        ]
        if partners:
            best = min(partners, key=lambda j: (abs((diffs[j][0] - day_k).days), j))
            result.update({k, best})
            redated.update({k, best})
    return frozenset(redated)


def load_holidays(path: Path) -> frozenset[date]:
    """Загрузить справочник праздников РБ — §5.7.3, ``config/holidays_by.yaml``.

    Пустой файл-заготовка не является ошибкой: агрегация тогда работает только
    по календарным выходным.
    """
    if not path.exists():
        return frozenset()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    days = raw.get("holidays") or []
    transferred = raw.get("transferred_days_off") or []
    return frozenset(day for day in (*days, *transferred) if isinstance(day, date))


def _preceding_block(day: date, holidays: frozenset[date]) -> tuple[date, ...]:
    """Нерабочий блок перед понедельником плюс последний рабочий день — §5.7.3.

    Для обычного понедельника даёт ``(вс, сб, пт)`` — ровно паттерн ТЗ.
    Праздники удлиняют блок: после трёхдневных выходных агрегируется больше дней.
    """
    block: list[date] = []
    cursor = day - timedelta(days=1)
    while cursor.weekday() >= _SATURDAY or cursor in holidays:
        block.append(cursor)
        cursor -= timedelta(days=1)
    block.append(cursor)
    return tuple(block)


def detect_calendar_aggregation(
    acc: dict[date, Decimal],
    ops: dict[date, Decimal],
    holidays: frozenset[date],
    config: Config,
) -> tuple[CalendarAggregation, ...]:
    """Паттерн «понедельник агрегирует выходные» — §5.7.3.

    ``acc[пн] ≈ ops[пт] + ops[сб] + ops[вс]`` с допуском ``EPS_SUM``.
    Найденные агрегации логируются как объяснение, а не как расхождение.
    """
    found: list[CalendarAggregation] = []
    for day in sorted(acc):
        if day.weekday() != _MONDAY:
            continue
        sources = _preceding_block(day, holidays)
        ops_sum = sum((ops.get(source, _ZERO) for source in sources), _ZERO)
        acc_value = acc[day]
        if _ZERO in (ops_sum, acc_value):
            continue
        matches_block = abs(acc_value - ops_sum) < config.thresholds.EPS_SUM
        # Если сумма и так стоит на самом понедельнике, агрегации нет.
        already_same_day = acc_value == ops.get(day, _ZERO)
        if matches_block and not already_same_day:
            found.append(
                CalendarAggregation(
                    posting_date=day,
                    source_dates=tuple(sorted(sources)),
                    acc_amount=acc_value,
                    ops_amount=ops_sum,
                ),
            )
    return tuple(found)


def collapse_timing(
    diffs: Sequence[tuple[date, Decimal]],
    config: Config,
    *,
    enabled: bool = True,
) -> CollapseResult:
    """Свёртка тайминга целиком — §5.7.2.

    Вход: дни с любой ненулевой разницей; внутри отбрасываются те, у кого
    ``|разница| < EPS_FLOOR`` — это шум округления, а не расхождение.
    Выход: ``{residual, collapsed, redated, total}`` плюс журнал гашений (§12).

    Ожидаемые остатки на калибровочных кассах — таблица §5.7.4.

    Args:
        diffs: пары ``(дата, разница)``, упорядоченные по дате.
        config: конфигурация §6.
        enabled: ``False`` соответствует флагу ``--no-collapse`` (§12).
    """
    significant = tuple(
        (day, diff) for day, diff in diffs if abs(diff) >= config.thresholds.EPS_FLOOR
    )
    total = len(significant)

    if not enabled or total == 0:
        return CollapseResult(
            residual=sum((diff for _, diff in significant), _ZERO),
            collapsed=0,
            redated=0,
            total=total,
            residual_days=significant,
            lag=None,
            calendar_aggregations=(),
            audit_log=(),
        )

    after_pass1 = collapse_pass1_cumulative(significant, config.thresholds.EPS_FLOOR)
    after_pass2 = collapse_pass2_pairwise(significant, after_pass1, config)
    redated = collapse_pass3_redate(significant, after_pass2, config)
    settled = after_pass2 | redated

    audit = tuple(
        AuditLogEntry(
            stage="§5.7.2 collapse_timing",
            rule=(
                "проход 1 — кумулятивная сегментация"
                if index in after_pass1
                else "проход 2 — парное гашение в окне"
                if index in after_pass2
                else "проход 3 — перенос даты, точное совпадение"
            ),
            subject_rows=(),
            counterpart_rows=(),
            amount=significant[index][1],
            note=f"день {significant[index][0]:%d.%m.%Y} признан таймингом",
        )
        for index in sorted(settled)
    )

    residual_days = tuple(pair for index, pair in enumerate(significant) if index not in settled)
    return CollapseResult(
        residual=sum((diff for _, diff in residual_days), _ZERO),
        collapsed=len(settled),
        redated=len(redated),
        total=total,
        residual_days=residual_days,
        lag=None,
        calendar_aggregations=(),
        audit_log=audit,
    )


def run_timing(
    reconciliation: dict[Category, CategoryRecon],
    config: Config,
    *,
    enabled: bool = True,
) -> dict[Category, CollapseResult]:
    """Стадия COLLAPSE_TIMING по всем категориям — §5.7.

    Дополняет свёртку диагностикой: лаг §5.7.1 и календарная агрегация §5.7.3.
    Ни то, ни другое свёртку не меняет — они объясняют её пользователю.
    """
    holidays = load_holidays(config.calendar.holidays_file)
    result: dict[Category, CollapseResult] = {}

    for category, recon in reconciliation.items():
        acc = _as_series(recon.acc_series)
        ops = _as_series(recon.ops_series)
        collapse = collapse_timing(recon.daily_differences, config, enabled=enabled)
        result[category] = collapse.model_copy(
            update={
                "lag": detect_lag(acc, ops, config),
                "calendar_aggregations": detect_calendar_aggregation(
                    acc,
                    ops,
                    holidays,
                    config,
                ),
            },
        )

    return result
