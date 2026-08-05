"""Синтетические кейсы этапа 1 — §11.2 ТЗ.

Проверяют сцепку стадий §5.1–5.7 на настоящих `.xlsx`, а не на собранных
вручную структурах: между ingest и collapse_timing семь стадий, и ошибка
раскладки колонок проявляется только на файле.

Обязательные негативные кейсы §11.2, относящиеся к этапу 1:

* чистая касса без дефектов → раскладка сходится, сальдо = T;
* касса только с таймингом → остаток свёртки 0.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cashforensics.classify import classify
from cashforensics.ingest import ingest
from cashforensics.models import Category, CategoryRecon, CollapseResult, Config
from cashforensics.normalize import normalize
from cashforensics.reconcile import reconcile
from cashforensics.reversals import neutralize_reversals
from cashforensics.timing import run_timing
from cashforensics.validate import validate
from tests.conftest import OpsRecord, Posting, SheetPlan

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.synthetic

ZERO = Decimal("0.00")
START = date(2024, 2, 1)


def _run(
    path: Path,
    config: Config,
) -> tuple[dict[Category, CategoryRecon], dict[Category, CollapseResult]]:
    """Прогнать стадии §5.1–5.7 и вернуть сверку и свёртку по категориям."""
    normalized = normalize(ingest(path, config), config)
    validate(normalized, config)
    classified = classify(normalized, config)
    reversals = neutralize_reversals(classified, config)
    reconciliation = reconcile(classified, reversals, config)
    return reconciliation, run_timing(reconciliation, config)


def _sale(row_day: date, amount: Decimal, index: int) -> Posting:
    return Posting(row_day, f"Приходный кассовый ордер 0001{index:05d}", "50.2", amount, "90.1.1")


def _collection(row_day: date, amount: Decimal, index: int) -> Posting:
    return Posting(
        row_day,
        f"Расходный кассовый ордер 0002{index:05d}",
        "51",
        None,
        "50.2",
        amount,
    )


class TestCleanRegister:
    """§11.2: чистая касса без дефектов."""

    def test_no_differences_and_balance_matches_target(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Приход и инкассация сходятся день в день, сальдо = 0."""
        days = [START + timedelta(days=index) for index in range(10)]
        plan = SheetPlan(
            postings=[
                item
                for index, current in enumerate(days)
                for item in (
                    _sale(current, Decimal("500.00"), index),
                    _collection(current, Decimal("500.00"), index),
                )
            ],
            pko=[
                OpsRecord(
                    datetime.combine(current, datetime.min.time()).replace(hour=12),
                    Decimal("500.00"),
                    "Клиент",
                )
                for current in days
            ],
            rko=[
                OpsRecord(
                    datetime.combine(current, datetime.min.time()),
                    Decimal("500.00"),
                    "Центральная касса",
                )
                for current in days
            ],
        )

        reconciliation, timing = _run(make_workbook(plan), config)

        for category in (Category.INCOME, Category.COLLECTION):
            assert reconciliation[category].net == ZERO
            assert reconciliation[category].days_with_difference == 0
            assert timing[category].residual == ZERO
            assert timing[category].residual_days == ()


class TestTimingOnlyRegister:
    """§11.2: касса только с таймингом → остаток свёртки 0."""

    def test_one_day_shift_collapses_completely(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Калибровочная ситуация §5.7.4: инкассация 1С отстаёт на день.

        Максиму_3 — 59 дней «расхождения», остаток 0; Солигорск — 1 325 → 0.
        """
        days = [START + timedelta(days=index) for index in range(12)]
        plan = SheetPlan(
            postings=[
                _collection(current, Decimal("500.00"), index)
                for index, current in enumerate(days[1:], start=1)
            ],
            rko=[
                OpsRecord(
                    datetime.combine(current, datetime.min.time()),
                    Decimal("500.00"),
                    "Центральная касса",
                )
                for current in days[:-1]
            ],
            opening=Decimal("6000.00"),
        )

        reconciliation, timing = _run(make_workbook(plan), config)

        collection = timing[Category.COLLECTION]
        assert reconciliation[Category.COLLECTION].days_with_difference > 0
        assert collection.residual == ZERO
        assert collection.residual_days == ()

    def test_lag_is_detected_and_reported(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§5.7.1: лаг — диагностика для пользователя, а не изменение свёртки."""
        days = [START + timedelta(days=index) for index in range(12)]
        plan = SheetPlan(
            postings=[
                _collection(current, Decimal("500.00"), index)
                for index, current in enumerate(days[1:], start=1)
            ],
            rko=[
                OpsRecord(
                    datetime.combine(current, datetime.min.time()),
                    Decimal("500.00"),
                    "Центральная касса",
                )
                for current in days[:-1]
            ],
            opening=Decimal("6000.00"),
        )

        _, timing = _run(make_workbook(plan), config)

        lag = timing[Category.COLLECTION].lag
        assert lag is not None
        assert lag.best_lag == 1
        assert lag.significant


class TestRealDifferenceSurvives:
    """Свёртка не должна прятать настоящее расхождение."""

    def test_one_sided_shortfall_remains_in_residual(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Возврат проведён в 1С, выдачи в логе нет — остаток обязан остаться."""
        days = [START + timedelta(days=index) for index in range(6)]
        plan = SheetPlan(
            postings=[
                Posting(
                    current,
                    f"Расходный кассовый ордер 0003{index:05d}",
                    "76.9.1",
                    None,
                    "50.2",
                    Decimal("100.00"),
                )
                for index, current in enumerate(days)
            ],
            rko=[
                OpsRecord(
                    datetime.combine(current, datetime.min.time()).replace(hour=14),
                    Decimal("100.00"),
                    "Иванов Иван",
                )
                for current in days[:-1]
            ],
            opening=Decimal("600.00"),
        )

        _, timing = _run(make_workbook(plan), config)

        refunds = timing[Category.REFUND]
        assert refunds.residual == Decimal("100.00")
        assert len(refunds.residual_days) == 1


class TestServiceRecipientsAreNotRefunds:
    """§3.6: служебные записи дают мнимое расхождение — их надо отделять."""

    def test_adjusted_variant_closes_the_gap(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Кейс Солигорска: 11 310,00 + 150,00 + 150,00 = 11 610,00 мнимых."""
        plan = SheetPlan(
            postings=[
                Posting(
                    START,
                    "Расходный кассовый ордер 000300001",
                    "76.9.1",
                    None,
                    "50.2",
                    Decimal("203.93"),
                ),
            ],
            rko=[
                OpsRecord(datetime(2024, 2, 1, 14, 0, 0), Decimal("203.93"), "Правосуд Дмитрий"),
                OpsRecord(datetime(2024, 2, 1, 15, 0, 0), Decimal("11310.00"), "СУД г. Солигорска"),
                OpsRecord(datetime(2024, 2, 1, 16, 0, 0), Decimal("150.00"), "АРХИВ ПВЗ"),
                OpsRecord(datetime(2024, 2, 1, 17, 0, 0), Decimal("150.00"), "Финконтроль"),
            ],
            opening=Decimal("203.93"),
        )

        reconciliation, _ = _run(make_workbook(plan), config)

        refunds = reconciliation[Category.REFUND]
        assert refunds.net == Decimal("-11610.00")
        assert refunds.adjusted_net == ZERO


class TestDeterminism:
    """§13.5: повторный прогон даёт идентичный результат."""

    def test_second_run_matches_first(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        days = [START + timedelta(days=index) for index in range(8)]
        plan = SheetPlan(
            postings=[
                item
                for index, current in enumerate(days)
                for item in (
                    _sale(current, Decimal("500.00"), index),
                    _collection(current, Decimal("300.00"), index),
                )
            ],
            pko=[
                OpsRecord(
                    datetime.combine(current, datetime.min.time()).replace(hour=12),
                    Decimal("480.00"),
                    "Клиент",
                )
                for current in days
            ],
            rko=[
                OpsRecord(
                    datetime.combine(current, datetime.min.time()),
                    Decimal("300.00"),
                    "Центральная касса",
                )
                for current in days
            ],
        )
        path = make_workbook(plan)

        first_recon, first_timing = _run(path, config)
        second_recon, second_timing = _run(path, config)

        assert {k: v.model_dump() for k, v in first_recon.items()} == {
            k: v.model_dump() for k, v in second_recon.items()
        }
        assert {k: v.model_dump() for k, v in first_timing.items()} == {
            k: v.model_dump() for k, v in second_timing.items()
        }
