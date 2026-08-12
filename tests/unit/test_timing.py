"""Юнит-тесты стадии COLLAPSE_TIMING — §5.7."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from cashforensics.models import Config
from cashforensics.timing import (
    collapse_pass1_cumulative,
    collapse_pass2_pairwise,
    collapse_pass3_redate,
    collapse_timing,
    detect_calendar_aggregation,
    detect_lag,
    lag_score,
    load_holidays,
)

pytestmark = pytest.mark.unit

ZERO = Decimal("0.00")
START = date(2024, 2, 1)


def day(offset: int) -> date:
    """Дата со смещением от начала синтетического периода."""
    return START + timedelta(days=offset)


class TestLagScore:
    """§5.7.1: детектор лага."""

    def test_finds_known_lag_of_one_day(self, config: Config) -> None:
        """Опер-лог отстаёт от 1С ровно на день — §11.1 ТЗ."""
        acc = {day(index): Decimal("100.00") for index in range(1, 11)}
        ops = {day(index - 1): Decimal("100.00") for index in range(1, 11)}

        result = detect_lag(acc, ops, config)

        assert result.best_lag == 1
        assert result.significant

    def test_lag_zero_when_series_align(self, config: Config) -> None:
        acc = {day(index): Decimal("100.00") for index in range(10)}
        ops = dict(acc)

        result = detect_lag(acc, ops, config)

        assert result.best_lag == 0
        assert not result.significant

    def test_score_is_l1_distance(self) -> None:
        acc = {day(0): Decimal("100.00"), day(1): Decimal("50.00")}
        ops = {day(0): Decimal("90.00"), day(1): Decimal("70.00")}

        assert lag_score(acc, ops, 0) == Decimal("30.00")

    def test_score_is_decimal_not_float(self) -> None:
        """§10: наружу из вычисления идёт Decimal."""
        acc = {day(0): Decimal("100.00")}
        ops = {day(0): Decimal("99.99")}

        assert isinstance(lag_score(acc, ops, 0), Decimal)

    def test_insignificant_lag_is_not_reported(self, config: Config) -> None:
        """Порог §5.7.1: улучшение должно быть больше 30 %."""
        acc = {day(index): Decimal("100.00") for index in range(10)}
        ops = {day(index): Decimal("100.00") for index in range(10)}
        ops[day(3)] = Decimal("99.00")

        assert not detect_lag(acc, ops, config).significant


class TestCollapsePasses:
    """§5.7.2: свёртка в три прохода."""

    def test_pass1_settles_cumulative_segment(self, config: Config) -> None:
        diffs = (
            (day(0), Decimal("100.00")),
            (day(1), Decimal("-100.00")),
            (day(2), Decimal("50.00")),
            (day(3), Decimal("-50.00")),
        )

        settled = collapse_pass1_cumulative(diffs, config.thresholds.EPS_FLOOR)

        assert settled == frozenset({0, 1, 2, 3})

    def test_shift_by_one_day_collapses_to_zero(self, config: Config) -> None:
        """§11.1: сдвиг +1 на синтетике → остаток 0.

        Ровно ситуация Максиму_3 и Солигорска: инкассация 1С отстаёт от лога на
        день, «расхождений» много, нетто 0,00.
        """
        diffs = tuple(
            (day(index), Decimal("500.00") if index % 2 == 0 else Decimal("-500.00"))
            for index in range(20)
        )

        result = collapse_timing(diffs, config)

        assert result.residual == ZERO
        assert result.residual_days == ()
        assert result.collapsed == result.total

    def test_pass2_pairs_within_date_window(self, config: Config) -> None:
        """Парное гашение в окне DATE_WIN — §5.7.2."""
        diffs = (
            (day(0), Decimal("300.00")),
            (day(1), Decimal("17.00")),
            (day(2), Decimal("-300.20")),
        )

        result = collapse_timing(diffs, config)

        assert result.residual == Decimal("17.00")
        assert [pair[0] for pair in result.residual_days] == [day(1)]

    def test_pass2_does_not_pair_outside_window(self, config: Config) -> None:
        """За пределами DATE_WIN пара не засчитывается.

        Проход проверяется напрямую: через :func:`collapse_timing` эту пару
        успел бы погасить проход 1, который дат не смотрит вовсе.
        """
        diffs = ((day(0), Decimal("300.00")), (day(10), Decimal("-300.20")))

        assert collapse_pass2_pairwise(diffs, frozenset(), config) == frozenset()

    def test_pass1_ignores_dates_by_design(self, config: Config) -> None:
        """Проход 1 гасит по кумулятивной сумме, а не по близости дат — §5.7.2.

        Поэтому далеко разнесённые встречные разницы гасятся им, а не проходом
        3, и в ``redated`` не попадают.
        """
        diffs = ((day(0), Decimal("300.00")), (day(90), Decimal("-300.20")))

        settled = collapse_pass1_cumulative(diffs, config.thresholds.EPS_FLOOR)

        assert settled == frozenset({0, 1})

    def test_pass3_requires_exact_kopeck_match(self, config: Config) -> None:
        """§5.7.2: проход 3 — точное совпадение, допуск 0,005."""
        exact = ((day(0), Decimal("300.00")), (day(20), Decimal("-300.00")))
        approximate = ((day(0), Decimal("300.00")), (day(20), Decimal("-300.20")))

        assert collapse_pass3_redate(exact, frozenset(), config) == frozenset({0, 1})
        assert collapse_pass3_redate(approximate, frozenset(), config) == frozenset()

    def test_redated_counted_separately(self, config: Config) -> None:
        """Свёрнутое проходом 3 показывается отдельно — оно может быть ошибочным.

        Ряд подобран так, чтобы кумулятивная сумма ни разу не вернулась к нулю
        и проход 1 не сработал: иначе до прохода 3 дело не доходит.
        """
        diffs = (
            (day(0), Decimal("300.00")),
            (day(1), Decimal("50.00")),
            (day(20), Decimal("-300.00")),
        )

        result = collapse_timing(diffs, config)

        assert result.redated == 2
        assert result.residual == Decimal("50.00")
        assert [pair[0] for pair in result.residual_days] == [day(1)]

    def test_below_eps_floor_is_not_a_difference(self, config: Config) -> None:
        """§5.7.2: вход — только дни с |разница| ≥ EPS_FLOOR."""
        diffs = ((day(0), Decimal("0.40")), (day(1), Decimal("0.30")))

        result = collapse_timing(diffs, config)

        assert result.total == 0
        assert result.residual == ZERO

    def test_real_difference_survives_collapse(self, config: Config) -> None:
        """Односторонний сдвиг свёрткой не гасится — иначе она прятала бы находки."""
        diffs = tuple((day(index), Decimal("100.00")) for index in range(5))

        result = collapse_timing(diffs, config)

        assert result.residual == Decimal("500.00")
        assert len(result.residual_days) == 5

    def test_disabled_collapse_shows_raw_picture(self, config: Config) -> None:
        """§12, обратимость: ``--no-collapse`` ничего не гасит."""
        diffs = ((day(0), Decimal("100.00")), (day(1), Decimal("-100.00")))

        result = collapse_timing(diffs, config, enabled=False)

        assert result.collapsed == 0
        assert len(result.residual_days) == 2

    def test_audit_log_records_the_rule(self, config: Config) -> None:
        """§12: для каждого автогашения — что погашено, чем, каким правилом."""
        diffs = ((day(0), Decimal("100.00")), (day(1), Decimal("-100.00")))

        result = collapse_timing(diffs, config)

        assert len(result.audit_log) == 2
        assert all("§5.7.2" in record.stage for record in result.audit_log)
        assert all(record.rule for record in result.audit_log)

    def test_collapse_is_deterministic(self, config: Config) -> None:
        """§13.5: один вход → побитово одинаковый выход."""
        diffs = tuple(
            (day(index), Decimal("100.00") if index % 3 else Decimal("-200.00"))
            for index in range(30)
        )

        first = collapse_timing(diffs, config)
        second = collapse_timing(diffs, config)

        assert first.model_dump() == second.model_dump()


class TestCalendarAggregation:
    """§5.7.3: понедельник агрегирует выходные."""

    def test_monday_aggregates_friday_saturday_sunday(self, config: Config) -> None:
        """``acc[пн] ≈ ops[пт] + ops[сб] + ops[вс]`` — §11.1 ТЗ."""
        monday = date(2024, 2, 5)
        acc = {monday: Decimal("300.00")}
        ops = {
            date(2024, 2, 2): Decimal("100.00"),
            date(2024, 2, 3): Decimal("120.00"),
            date(2024, 2, 4): Decimal("80.00"),
        }

        found = detect_calendar_aggregation(acc, ops, frozenset(), config)

        assert len(found) == 1
        assert found[0].posting_date == monday
        assert found[0].source_dates == (
            date(2024, 2, 2),
            date(2024, 2, 3),
            date(2024, 2, 4),
        )
        assert found[0].ops_amount == Decimal("300.00")

    def test_no_aggregation_when_sums_disagree(self, config: Config) -> None:
        monday = date(2024, 2, 5)
        acc = {monday: Decimal("300.00")}
        ops = {date(2024, 2, 3): Decimal("10.00")}

        assert detect_calendar_aggregation(acc, ops, frozenset(), config) == ()

    def test_holiday_extends_the_block(self, config: Config) -> None:
        """Праздник перед выходными удлиняет агрегируемый блок — §5.7.3."""
        monday = date(2024, 2, 5)
        holiday = date(2024, 2, 2)
        acc = {monday: Decimal("400.00")}
        ops = {
            date(2024, 2, 1): Decimal("100.00"),
            holiday: Decimal("100.00"),
            date(2024, 2, 3): Decimal("120.00"),
            date(2024, 2, 4): Decimal("80.00"),
        }

        found = detect_calendar_aggregation(acc, ops, frozenset({holiday}), config)

        assert len(found) == 1
        assert date(2024, 2, 1) in found[0].source_dates

    def test_empty_holidays_file_is_not_an_error(self, config: Config) -> None:
        """Заготовка календаря пуста — агрегация работает по выходным (§5.7.3)."""
        assert load_holidays(config.calendar.holidays_file) == frozenset()

    def test_missing_holidays_file_is_not_an_error(self) -> None:
        from pathlib import Path

        assert load_holidays(Path("config/такого_файла_нет.yaml")) == frozenset()
