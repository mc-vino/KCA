"""Стадия BALANCE_TRACE — §5.8 ТЗ. Ядро, ради которого пишется приложение.

Нарастающее сальдо (§5.8.1), инвариант неотрицательности относительно T
(§5.8.2), «пол кассы» с фильтром полноты выемки (§5.8.3), датирование смещения
через PELT/CUSUM/EWMA (§5.8.4) и локализация окна смещения (§5.8.5).

Граница float/Decimal
---------------------
``ruptures`` работает с ``float``. Конвертация допустима **только** на входе в
детектор разладки; наружу возвращаются индексы и даты, а не суммы. Все
денежные величины на границах модуля — :class:`~decimal.Decimal` (§10).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

import numpy as np
import ruptures

from cashforensics.models import (
    BalanceTrace,
    Category,
    ChangePointWindow,
    ClassifyResult,
    Config,
    LedgerEntry,
    NonNegativityReport,
    OpsClass,
    SweepPoint,
    WindowFlows,
)

__all__ = [
    "balance_trace",
    "cash_floor_points",
    "check_nonnegativity",
    "confirm_cusum",
    "confirm_ewma",
    "daily_closing_balances",
    "detect_level_shift_pelt",
    "is_full_sweep",
    "localize_shift_window",
    "quarterly_balances",
    "running_balance",
    "target_balance_at",
]

_ZERO = Decimal("0.00")
_MIN_SERIES_FOR_CHANGEPOINT = 4
"""Ниже этого числа точек разладку не ищем: окно было бы шире самого ряда."""


def running_balance(
    ledger: Sequence[LedgerEntry],
    opening: Decimal,
) -> tuple[LedgerEntry, ...]:
    """Нарастающее сальдо — §5.8.1.

    Порядок обхода строго ``(дата, row)`` — полный явный ключ (§12).
    Возвращает новый кортеж записей с заполненным ``running_balance``:
    стадии не мутируют вход (§5).
    """
    balance = opening
    result: list[LedgerEntry] = []
    for entry in sorted(ledger, key=lambda item: (item.date, item.row)):
        balance += entry.debit - entry.credit
        result.append(entry.model_copy(update={"running_balance": balance}))
    return tuple(result)


def daily_closing_balances(
    ledger: Sequence[LedgerEntry],
) -> tuple[tuple[date, Decimal], ...]:
    """Сальдо на конец каждого дня — §5.8.2, §5.8.3.

    Берётся ``running_balance`` последней проводки дня в порядке ``(дата, row)``.
    Вход обязан быть уже пропущен через :func:`running_balance`.
    """
    per_day: dict[date, Decimal] = {}
    for entry in sorted(ledger, key=lambda item: (item.date, item.row)):
        per_day[entry.date] = entry.running_balance
    return tuple((day, per_day[day]) for day in sorted(per_day))


def target_balance_at(day: date, config: Config) -> Decimal:
    """Целевое сальдо T на дату — §6, ``target_balance_schedule``.

    Фонд кассы мог меняться во времени; §13.8 требует работоспособности при
    ``T ≠ 0``. Действует последнее правило, чья дата не позже запрошенной.
    """
    value = config.target_balance
    for rule in sorted(config.target_balance_schedule, key=lambda item: item.from_):
        if rule.from_ <= day:
            value = rule.value
    return value


def check_nonnegativity(
    ledger: Sequence[LedgerEntry],
    config: Config,
) -> NonNegativityReport:
    """Инвариант неотрицательности — §5.8.2.

    Находит первый день с сальдо < T, первый день, после которого сальдо
    больше не поднималось до ≥ T, минимум за период с датой и долю дней ниже T.

    На PAX_119023531 сальдо впервые ушло в минус 09.08.2023 — ровно день
    проблемного документа R811: инвариант сработал как датировщик.
    """
    days = daily_closing_balances(ledger)
    if not days:
        return NonNegativityReport(
            first_below_target=None,
            never_recovered_after=None,
            minimum=_ZERO,
            minimum_date=None,
            share_of_days_below=0.0,
        )

    below = [(day, value) for day, value in days if value < target_balance_at(day, config)]
    first_below = below[0][0] if below else None

    never_recovered: date | None = None
    for index, (day, _value) in enumerate(days):
        rest = days[index:]
        if all(value < target_balance_at(current, config) for current, value in rest):
            never_recovered = day
            break

    minimum_day, minimum = min(days, key=lambda item: (item[1], item[0]))
    return NonNegativityReport(
        first_below_target=first_below,
        never_recovered_after=never_recovered,
        minimum=minimum,
        minimum_date=minimum_day,
        share_of_days_below=len(below) / len(days),
    )


def is_full_sweep(
    collection: Decimal,
    income: Decimal,
    median_daily_income: Decimal,
    config: Config,
) -> bool:
    """День полной выемки — §5.8.3.

    ``инкассация > 0 и приход == 0 и инкассация ≥ SWEEP_MIN_RATIO · медиана(приход)``.

    **Фильтр обязателен:** без него в список попадают дни с копеечной
    инкассацией, которые не опустошают кассу и дают бессмысленный «пол». На
    PAX_119023531 две из четырёх точек — именно такие (259,47 и 310,61), их
    нужно помечать «частичная выемка — не показатель».
    """
    if collection <= _ZERO or income != _ZERO:
        return False
    threshold = median_daily_income * Decimal(str(config.thresholds.SWEEP_MIN_RATIO))
    return collection >= threshold


def _median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return _ZERO
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def cash_floor_points(
    ledger: Sequence[LedgerEntry],
    config: Config,
) -> tuple[SweepPoint, ...]:
    """Ряд «пола кассы» — §5.8.3.

    Сальдо после дня полной выемки = «пол». Постоянство пола означает
    постоянное смещение, а не накопление мелочи.

    Возвращаются **все** дни инкассации без прихода, включая частичные выемки:
    они помечены ``is_full=False`` и обязаны показываться в отчёте с пометкой
    «частичная выемка — не показатель» (§9.1.3), но в ряд пола не входят.

    Солигорск: пол −1 224,80 в обе даты полной выемки. PAX_119023531:
    +50,00 → −1 129,00, сдвиг ровно −1 179,00.
    """
    collections: dict[date, Decimal] = {}
    incomes: dict[date, Decimal] = {}
    for entry in ledger:
        if entry.category is Category.COLLECTION:
            collections[entry.date] = collections.get(entry.date, _ZERO) + entry.credit
        elif entry.category is Category.INCOME:
            incomes[entry.date] = incomes.get(entry.date, _ZERO) + entry.debit

    median_income = _median([value for value in incomes.values() if value > _ZERO])
    closing = dict(daily_closing_balances(ledger))

    points: list[SweepPoint] = []
    for day in sorted(collections):
        collection = collections[day]
        income = incomes.get(day, _ZERO)
        if collection <= _ZERO or income != _ZERO:
            continue
        points.append(
            SweepPoint(
                date=day,
                floor=closing.get(day, _ZERO),
                collection=collection,
                income=income,
                is_full=is_full_sweep(collection, income, median_income, config),
            ),
        )
    return tuple(points)


def _bic_penalty(signal: np.ndarray) -> float:
    """Штраф BIC для PELT — §5.8.4.

    ``pen = ln(n) · σ²``: классический BIC для модели ``l2`` с одномерным
    сигналом. ``σ`` оценивается по самому ряду; при вырожденном ряде штраф
    делается положительным, иначе PELT разбивает ряд на каждую точку.
    """
    n = len(signal)
    sigma = float(np.std(signal))
    penalty = math.log(n) * sigma**2
    return penalty if penalty > 0 else 1.0


def detect_level_shift_pelt(
    series: Sequence[tuple[date, Decimal]],
    config: Config,
) -> tuple[ChangePointWindow, ...]:
    """Основной детектор разладки — PELT, ``ruptures`` (§5.8.4).

    Модель ``l2``, штраф BIC, ``min_size`` конфигурируем.

    Конвертация ``Decimal → float`` допустима только здесь, на входе в
    детектор; наружу уходят индексы и даты, не суммы. Результат выдаётся
    **окном**, а не точкой: ``[дата − min_size, дата + min_size]``. Точная дата
    разладки из ряда сальдо не выводима (§16).

    Окно обязательно и по второй причине: ``ruptures.Pelt`` по умолчанию берёт
    ``jump = 5`` и рассматривает точки разрыва только на индексах, кратных
    пяти. Индекс изначально огрублён, и выдавать его как дату нельзя. Ставить
    ``jump = 1`` ради «точности» бессмысленно — §16 всё равно запрещает
    называть дату, а перебор дорожает впятеро.
    """
    if len(series) < max(_MIN_SERIES_FOR_CHANGEPOINT, 2 * config.changepoint.min_size):
        return ()

    days = [day for day, _ in series]
    # Единственное место, где деньги становятся float (§10).
    signal = np.array([float(value) for _, value in series], dtype=float).reshape(-1, 1)

    algo = ruptures.Pelt(model=config.changepoint.model, min_size=config.changepoint.min_size)
    breakpoints = algo.fit(signal).predict(pen=_bic_penalty(signal))

    span = config.changepoint.min_size
    windows: list[ChangePointWindow] = []
    for index in breakpoints:
        if index >= len(days):
            continue  # последняя точка — конец ряда, не разладка
        low = days[max(0, index - span)]
        high = days[min(len(days) - 1, index + span)]
        windows.append(
            ChangePointWindow(
                method=config.changepoint.method,
                index=index,
                window=(low, high),
                confirmed_by=(),
            ),
        )
    return tuple(windows)


def confirm_cusum(
    series: Sequence[tuple[date, Decimal]],
    config: Config,
) -> tuple[int, ...]:
    """Подтверждающий детектор CUSUM (k = 0,5σ, h = 4–5σ) — §5.8.4."""
    if len(series) < _MIN_SERIES_FOR_CHANGEPOINT:
        return ()
    values = np.array([float(value) for _, value in series], dtype=float)
    mean = float(np.mean(values))
    sigma = float(np.std(values)) or 1.0
    slack = config.changepoint.cusum_k * sigma
    limit = config.changepoint.cusum_h * sigma

    high = low = 0.0
    hits: list[int] = []
    for index, value in enumerate(values):
        deviation = value - mean
        high = max(0.0, high + deviation - slack)
        low = min(0.0, low + deviation + slack)
        if high > limit or low < -limit:
            hits.append(index)
            high = low = 0.0
    return tuple(hits)


def confirm_ewma(
    series: Sequence[tuple[date, Decimal]],
    config: Config,
) -> tuple[int, ...]:
    """Подтверждающий детектор EWMA (λ = 0,2, L = 3) — §5.8.4."""
    if len(series) < _MIN_SERIES_FOR_CHANGEPOINT:
        return ()
    values = np.array([float(value) for _, value in series], dtype=float)
    mean = float(np.mean(values))
    sigma = float(np.std(values)) or 1.0
    lam = config.changepoint.ewma_lambda
    limit = config.changepoint.ewma_L * sigma * math.sqrt(lam / (2 - lam))

    smoothed = mean
    hits: list[int] = []
    for index, value in enumerate(values):
        smoothed = lam * value + (1 - lam) * smoothed
        if abs(smoothed - mean) > limit:
            hits.append(index)
    return tuple(hits)


def localize_shift_window(
    window: tuple[date, date],
    classified: ClassifyResult,
) -> WindowFlows:
    """Сравнить поток 1С с потоком опер-лога внутри окна — §5.8.5.

    ``поток_1С    = Σприход + Σпрочие_Дт − Σинкассация − Σвозвраты − Σпрочие_Кт``
    ``поток_логов = ΣПКО − ΣРКО_инкассация − ΣРКО_возвраты``

    Если поток логов ≈ 0, а поток 1С ≠ 0 — расхождение целиком в учёте, и
    ``dominant_category`` показывает, в какой именно категории оно сидит.

    Солигорск, окно 06.09–19.12.2025: логи 0,00, 1С −2 911,51, всё расхождение
    в возвратах; далее локализовано до четырёх расходных ордеров.
    """
    start, end = window
    ledger_flow = _ZERO
    per_category: dict[Category, Decimal] = {}
    for entry in classified.ledger:
        if not (start <= entry.date <= end):
            continue
        signed = entry.debit - entry.credit
        ledger_flow += signed
        per_category[entry.category] = per_category.get(entry.category, _ZERO) + signed

    ops_flow = _ZERO
    for operation in classified.ops:
        if not (start <= operation.dt.date() <= end):
            continue
        if operation.classification is OpsClass.INCOME:
            ops_flow += operation.amount
        elif operation.classification in (OpsClass.COLLECTION, OpsClass.REFUND):
            ops_flow -= operation.amount

    dominant = (
        max(per_category.items(), key=lambda item: (abs(item[1]), item[0].value))[0]
        if per_category
        else None
    )
    return WindowFlows(
        window=window,
        ledger_flow=ledger_flow,
        ops_flow=ops_flow,
        dominant_category=dominant,
    )


def quarterly_balances(
    ledger: Sequence[LedgerEntry],
) -> tuple[tuple[str, Decimal], ...]:
    """Поквартальные остатки для листа «Динамика сальдо» — §9.1.3."""
    per_quarter: dict[str, Decimal] = {}
    for day, value in daily_closing_balances(ledger):
        per_quarter[f"{day.year}-Q{(day.month - 1) // 3 + 1}"] = value
    return tuple((label, per_quarter[label]) for label in sorted(per_quarter))


def balance_trace(
    classified: ClassifyResult,
    opening: Decimal,
    config: Config,
) -> BalanceTrace:
    """Стадия BALANCE_TRACE целиком — §5.8.

    Разладка ищется по ряду «пола кассы», а не по всему ряду сальдо: пол —
    это и есть смещённый ноль кассы, и его сдвиг заметен там, где дневные
    колебания выручки его прячут (§5.8.3). Если полных выемок мало, ряд пола
    короче ``2·min_size``, и детектор честно возвращает пусто — окна не будет.
    """
    ledger = running_balance(classified.ledger, opening)
    closing = ledger[-1].running_balance if ledger else opening
    sweeps = cash_floor_points(ledger, config)

    # §5.8.4 предписывает искать разладку «по ряду пола И по ряду сальдо».
    # Ряд пола короче и чище, ряд сальдо длиннее и шумнее; на кассах с малым
    # числом полных выемок работает только второй.
    balance_series = daily_closing_balances(ledger)
    floor_series = tuple((point.date, point.floor) for point in sweeps if point.is_full)

    change_points: list[ChangePointWindow] = []
    for label, series in (("пол", floor_series), ("сальдо", balance_series)):
        cusum = set(confirm_cusum(series, config))
        ewma = set(confirm_ewma(series, config))
        change_points.extend(
            window.model_copy(
                update={
                    "method": f"{config.changepoint.method}:{label}",
                    "confirmed_by": tuple(
                        name
                        for name, hits in (("cusum", cusum), ("ewma", ewma))
                        if window.index in hits
                    ),
                },
            )
            for window in detect_level_shift_pelt(series, config)
        )

    # Окно смещения строится между соседними точками выемки — §5.8.5.
    # Берутся ВСЕ точки, включая частичные: фильтр §5.8.3 отделяет полы,
    # годные как уровень, а границу окна задаёт сам факт выемки. На Солигорске
    # частичная выемка 05.09.2025 открывает эталонное окно 06.09–19.12.2025,
    # внутри которого логи дают ровно 0,00 при 1С −2 911,51.
    windows: list[WindowFlows] = []
    for previous, current in pairwise([point.date for point in sweeps]):
        windows.append(localize_shift_window((previous + timedelta(days=1), current), classified))

    return BalanceTrace(
        opening=opening,
        closing_computed=closing,
        target=target_balance_at(ledger[-1].date if ledger else date.min, config),
        nonnegativity=check_nonnegativity(ledger, config),
        sweep_points=sweeps,
        change_points=tuple(change_points),
        shift_windows=tuple(windows),
        quarterly_balances=quarterly_balances(ledger),
    )
