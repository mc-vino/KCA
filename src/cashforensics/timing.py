"""Стадия COLLAPSE_TIMING — §5.7 ТЗ.

Устраняет мнимые расхождения. Без неё инструмент показывает сотни ложных строк:
на Солигорске инкассация давала 1 325 «расхождений» при нетто 0,00.

Состав: детектор лага (§5.7.1), свёртка в три прохода (§5.7.2), календарная
агрегация выходных (§5.7.3). Калибровочные ожидания — таблица §5.7.4.

Свёртка отключается флагом ``--no-collapse`` (§12, обратимость).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from cashforensics.models import (
    CalendarAggregation,
    Category,
    CategoryRecon,
    CollapseResult,
    Config,
    LagResult,
)

__all__ = [
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


def lag_score(
    acc: dict[date, Decimal],
    ops: dict[date, Decimal],
    lag: int,
) -> Decimal:
    """``lagScore(L) = Σ_d |acc[d] − ops[d − L]|`` — §5.7.1.

    L1-метрика выбрана намеренно: робастна и объяснима (§15).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def detect_lag(
    acc: dict[date, Decimal],
    ops: dict[date, Decimal],
    config: Config,
) -> LagResult:
    """Найти лучший лаг ``L = 0..MAX_LAG`` — §5.7.1.

    Лаг значим при ``lagScore(best) < LAG_SIGNIFICANT_RATIO · lagScore(0)``.
    Результат диагностический: свёртку не меняет, объясняет её пользователю.

    Эмпирика Кассы 3: lag0 = 475 575, lag1 = 326 177 → сдвиг +1 день.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def collapse_pass1_cumulative(
    diffs: tuple[tuple[date, Decimal], ...],
    eps_floor: Decimal,
) -> frozenset[int]:
    """Проход 1 — кумулятивная сегментация (§5.7.2).

    Накапливает ``c``; как только ``|c| < EPS_FLOOR``, весь сегмент
    ``last+1..k`` помечается погашенным.

    Returns:
        Индексы погашенных элементов.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def collapse_pass2_pairwise(
    diffs: tuple[tuple[date, Decimal], ...],
    settled: frozenset[int],
    config: Config,
) -> frozenset[int]:
    """Проход 2 — парное гашение в окне ``DATE_WIN`` (§5.7.2).

    Обход по убыванию ``|diff[k]|``; при равенстве — по дате, затем по индексу
    (полный явный ключ, §12). Пара засчитывается при
    ``|diff[k] + diff[j]| < EPS_SUM``.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def collapse_pass3_redate(
    diffs: tuple[tuple[date, Decimal], ...],
    settled: frozenset[int],
    config: Config,
) -> frozenset[int]:
    """Проход 3 — перенос даты, точное совпадение (§5.7.2).

    Окно ``LONG_WIN``, допуск :data:`REDATE_TOLERANCE` (до копейки).

    Проход намеренно консервативен, но всё же может свести две разные операции,
    случайно равные по сумме. Поэтому свёрнутые им дни считаются отдельно
    (``redated``) и показываются в отчёте, а остаток маркируется «для разбора»,
    а не «ошибка».

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def load_holidays(path: Path) -> frozenset[date]:
    """Загрузить справочник праздников РБ — §5.7.3, ``config/holidays_by.yaml``.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def detect_calendar_aggregation(
    acc: dict[date, Decimal],
    ops: dict[date, Decimal],
    holidays: frozenset[date],
    config: Config,
) -> tuple[CalendarAggregation, ...]:
    """Паттерн «понедельник агрегирует выходные» — §5.7.3.

    ``acc[пн] ≈ ops[пт] + ops[сб] + ops[вс]`` с допуском ``EPS_SUM``.
    Найденные агрегации логируются как объяснение, а не как расхождение.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def collapse_timing(
    diffs: tuple[tuple[date, Decimal], ...],
    config: Config,
) -> CollapseResult:
    """Свёртка тайминга целиком — §5.7.2.

    Вход: только дни с ``|разница| ≥ EPS_FLOOR``.
    Выход: ``{residual, collapsed, redated, total}`` плюс журнал гашений (§12).

    Ожидаемые остатки на калибровочных кассах — таблица §5.7.4.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def run_timing(
    reconciliation: dict[Category, CategoryRecon],
    config: Config,
) -> dict[Category, CollapseResult]:
    """Стадия COLLAPSE_TIMING по всем категориям — §5.7.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError
