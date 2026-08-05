"""Юнит-тесты стадии NORMALIZE — §5.2, правила разбора §3.2 и §3.4."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cashforensics.ingest import ingest, load_sheet_rows
from cashforensics.models import DocType
from cashforensics.normalize import (
    clean_account,
    clean_text,
    detect_doc_type,
    extract_doc_number,
    inherit_dates,
    normalize,
    parse_datetime,
    parse_decimal,
    posting_direction,
    read_totals,
)
from tests.conftest import OpsRecord, Posting, SheetPlan

if TYPE_CHECKING:
    from collections.abc import Callable

    from cashforensics.models import Config

pytestmark = pytest.mark.unit


class TestCleanText:
    """§3.4: неразрывные пробелы заменяются до любого парсинга."""

    def test_nbsp_replaced(self) -> None:
        assert clean_text("Иванов\xa0Иван") == "Иванов Иван"

    def test_nbsp_inside_number(self) -> None:
        assert clean_text("1\xa0234,56") == "1 234,56"

    def test_none_becomes_empty(self) -> None:
        assert clean_text(None) == ""


class TestParseDecimal:
    """§3.4: форматы чисел и §10: наружу только Decimal."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1 234,56", Decimal("1234.56")),
            ("1\xa0234,56", Decimal("1234.56")),
            ("1234.56", Decimal("1234.56")),
            ("1234,56", Decimal("1234.56")),
            ("-4 952,36", Decimal("-4952.36")),
            ("−4 952,36", Decimal("-4952.36")),
            (1234.56, Decimal("1234.56")),
            (1234, Decimal("1234.00")),
            (Decimal("1234.5"), Decimal("1234.50")),
        ],
    )
    def test_formats(self, raw: object, expected: Decimal) -> None:
        assert parse_decimal(raw) == expected

    def test_result_is_decimal_not_float(self) -> None:
        """§10: float в расчётах сумм запрещён."""
        assert isinstance(parse_decimal("1 234,56"), Decimal)

    def test_quantized_to_two_places(self) -> None:
        parsed = parse_decimal("10.005")
        assert parsed is not None
        assert parsed.as_tuple().exponent == -2

    def test_half_up_rounding(self) -> None:
        """§10: ROUND_HALF_UP, не банковское округление."""
        assert parse_decimal("0.125") == Decimal("0.13")
        assert parse_decimal("0.135") == Decimal("0.14")

    @pytest.mark.parametrize("raw", [None, "", "   ", "не число", True])
    def test_non_numbers_return_none(self, raw: object) -> None:
        assert parse_decimal(raw) is None


class TestParseDatetime:
    """§3.4: даты с временем и без; время обязано сохраняться."""

    def test_date_only(self) -> None:
        assert parse_datetime("01.02.2024") == datetime(2024, 2, 1, 0, 0, 0)

    def test_date_with_time_preserved(self) -> None:
        """Время нужно time-fallback §3.3 и сигнатурам §8 — терять его нельзя."""
        assert parse_datetime("01.02.2024 23:59:59") == datetime(2024, 2, 1, 23, 59, 59)

    def test_native_datetime_passes_through(self) -> None:
        moment = datetime(2024, 2, 1, 13, 26, 55)
        assert parse_datetime(moment) == moment

    def test_nbsp_in_date(self) -> None:
        assert parse_datetime("01.02.2024\xa010:00:00") == datetime(2024, 2, 1, 10, 0, 0)

    @pytest.mark.parametrize("raw", ["32.13.2024", "не дата", None, ""])
    def test_invalid_returns_none(self, raw: object) -> None:
        assert parse_datetime(raw) is None


class TestCleanAccount:
    """§3.5: счёт из Excel приходит числом и без нормализации не найдётся."""

    def test_float_integer_account(self) -> None:
        assert clean_account(51.0) == "51"

    def test_dotted_account_untouched(self) -> None:
        assert clean_account("57.1.1") == "57.1.1"

    def test_nbsp_stripped(self) -> None:
        assert clean_account("76.9.1\xa0") == "76.9.1"


class TestPostingDirection:
    """§3.2: корр. счёт из G для дебета и из E для кредита.

    Перепутанные местами счета дают полностью ложную классификацию прихода.
    """

    def test_debit_takes_counter_account_from_g(self) -> None:
        row = (None, None, "ПКО", None, "50.2", "100,00", "90.1.1", None, None, None)

        result = posting_direction(row, "50.2")

        assert result == (Decimal("100.00"), Decimal("0.00"), "90.1.1")

    def test_credit_takes_counter_account_from_e(self) -> None:
        row = (None, None, "РКО", None, "76.9.1", None, "50.2", "40,00", None, None)

        result = posting_direction(row, "50.2")

        assert result == (Decimal("0.00"), Decimal("40.00"), "76.9.1")

    def test_row_outside_cash_account_is_skipped(self) -> None:
        row = (None, None, "Прочее", None, "60.1", "100,00", "51", None, None, None)

        assert posting_direction(row, "50.2") is None

    def test_counter_account_is_not_the_cash_account(self) -> None:
        """Регресс на ловушку §3.2: корр. счёт не должен совпасть с 50.2."""
        debit_row = (None, None, "ПКО", None, "50.2", "100,00", "90.1.1", None, None, None)
        credit_row = (None, None, "РКО", None, "51", None, "50.2", "500,00", None, None)

        debit = posting_direction(debit_row, "50.2")
        credit = posting_direction(credit_row, "50.2")

        assert debit is not None
        assert credit is not None
        assert debit[2] != "50.2"
        assert credit[2] != "50.2"


class TestInheritDates:
    """§3.2: дата указывается один раз на блок строк за день."""

    def test_date_flows_down(self) -> None:
        rows = [
            (None, "01.02.2024", "ПКО", None, "50.2"),
            (None, None, "ПКО", None, "50.2"),
            (None, None, "РКО", None, "76.9.1"),
            (None, "02.02.2024", "ПКО", None, "50.2"),
            (None, None, "ПКО", None, "50.2"),
        ]

        assert inherit_dates(rows) == (
            date(2024, 2, 1),
            date(2024, 2, 1),
            date(2024, 2, 1),
            date(2024, 2, 2),
            date(2024, 2, 2),
        )

    def test_service_row_does_not_reset_date(self) -> None:
        """«Обороты за 05.02.2024» содержит дату в тексте и сбивал бы наследование."""
        rows = [
            (None, "01.02.2024", "ПКО"),
            (None, "Обороты за 05.02.2024", None),
            (None, None, "ПКО"),
        ]

        assert inherit_dates(rows)[2] == date(2024, 2, 1)

    def test_none_before_first_date(self) -> None:
        assert inherit_dates([(None, "Период", "Документ")])[0] is None


class TestDocumentText:
    """§3.2, §3.4: тип и номер документа."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Приходный кассовый ордер 000123456 от 01.02.2024", DocType.PKO),
            ("Расходный кассовый ордер 00284721 от 09.08.2023", DocType.RKO),
            ("Корректировка записей регистров 000000911 ", DocType.REVERSAL),
            ("Передача денег между кассами 000000042", DocType.TRANSFER),
            ("", DocType.OTHER),
        ],
    )
    def test_doc_type(self, text: str, expected: DocType) -> None:
        assert detect_doc_type(text, "корректировк") == expected

    def test_reversal_wins_over_order_words(self) -> None:
        """Сторно может нести в тексте слова исходного ордера — проверять первым."""
        text = "Корректировка записей регистров: Расходный кассовый ордер 00284721"

        assert detect_doc_type(text, "корректировк") == DocType.REVERSAL

    def test_doc_number_is_first_run_of_six_digits(self) -> None:
        assert extract_doc_number("Расходный кассовый ордер 00284721 от 09.08.2023") == "00284721"

    def test_no_number_is_empty_not_error(self) -> None:
        assert extract_doc_number("Расходный кассовый ордер") == ""


class TestReadTotals:
    """§3.2: сальдо читается из колонки 4 (E), не из 9."""

    def test_opening_and_closing_from_column_four(self) -> None:
        rows = [
            (None, "Сальдо на начало", None, None, "1 000,00", None, None, None, None, "0,00"),
            (None, "Обороты за период", None, None, "500,00", None, "300,00", None, None, None),
            (None, "Сальдо на конец", None, None, "1 200,00", None, None, None, "Д", "0,00"),
        ]

        totals = read_totals(rows)

        assert totals.opening == Decimal("1000.00")
        assert totals.closing_stated == Decimal("1200.00")
        assert totals.turnover_debit == Decimal("500.00")
        assert totals.turnover_credit == Decimal("300.00")

    def test_column_nine_is_ignored(self) -> None:
        """Регресс на ловушку §3.2: чтение из 9 дало 0 вместо −4 952,36."""
        rows = [
            (None, "Сальдо на конец", None, None, "-4 952,36", None, None, None, "Д", "0,00"),
        ]

        assert read_totals(rows).closing_stated == Decimal("-4952.36")

    def test_credit_side_makes_balance_negative(self) -> None:
        """Колонка 8 хранит сторону сальдо (§3.2): кредитовое — отрицательное."""
        rows = [
            (None, "Сальдо на конец", None, None, "4 952,36", None, None, None, "К", None),
        ]

        assert read_totals(rows).closing_stated == Decimal("-4952.36")

    def test_missing_turnovers_are_none(self) -> None:
        """Без «Оборотов за период» V1/V2 пропускаются, V3 остаётся (§5.3)."""
        rows = [(None, "Сальдо на начало", None, None, "0,00")]

        totals = read_totals(rows)

        assert totals.turnover_debit is None
        assert totals.turnover_credit is None

    def test_daily_turnover_row_is_not_period_turnover(self) -> None:
        """«Обороты за <дата>» — дневные итоги, их надо пропускать (§3.2)."""
        rows = [(None, "Обороты за 01.02.2024", None, None, "500,00", None, "300,00")]

        assert read_totals(rows).turnover_debit is None


class TestNormalizeStage:
    """Стадия целиком на синтетической выгрузке."""

    def test_reads_whole_period_without_truncation(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§5.2: читать весь период, никаких обрезаний."""
        plan = SheetPlan(
            postings=[
                Posting(
                    date(2024, 2, day),
                    f"Приходный кассовый ордер 00012345{day}",
                    "50.2",
                    Decimal("100.00"),
                    "90.1.1",
                )
                for day in range(1, 6)
            ],
        )

        result = normalize(ingest(make_workbook(plan), config), config)

        assert len(result.ledger) == 5
        assert {entry.date.day for entry in result.ledger} == {1, 2, 3, 4, 5}

    def test_ops_entries_carry_time_and_counterparty(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        plan = SheetPlan(
            postings=[
                Posting(date(2024, 2, 1), "ПКО 000123456", "50.2", Decimal("100.00"), "90.1.1"),
            ],
            rko=[
                OpsRecord(
                    datetime(2024, 2, 1, 13, 26, 55),
                    Decimal("164.99"),
                    "Правосуд Дмитрий",
                ),
            ],
            pko=[
                OpsRecord(datetime(2024, 2, 1, 11, 0, 0), Decimal("100.00"), "Петров Пётр"),
            ],
        )

        result = normalize(ingest(make_workbook(plan), config), config)

        rko = [entry for entry in result.ops if entry.kind.value == "РКО"]
        assert len(rko) == 1
        assert rko[0].dt.hour == 13
        assert rko[0].dt.second == 55
        assert rko[0].counterparty == "Правосуд Дмитрий"

    def test_unparsed_ledger_row_becomes_parse_issue(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§12: «тихих» пропусков нет — строка попадает в отчёт с номером."""
        plan = SheetPlan(
            postings=[
                Posting(date(2024, 2, 1), "ПКО 000123456", "50.2", Decimal("100.00"), "90.1.1"),
                Posting(date(2024, 2, 1), "Прочее 000999999", "60.1", Decimal("10.00"), "51"),
            ],
        )

        result = normalize(ingest(make_workbook(plan), config), config)

        assert len(result.ledger) == 1
        assert len(result.issues) == 1
        assert result.issues[0].row > 0
        assert "50.2" in result.issues[0].reason

    def test_ledger_rows_point_at_source_lines(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§12: трассировка до строк исходного файла, нумерация как в Excel."""
        plan = SheetPlan(
            postings=[
                Posting(date(2024, 2, 1), "ПКО 000123456", "50.2", Decimal("100.00"), "90.1.1"),
            ],
        )
        path = make_workbook(plan)

        result = normalize(ingest(path, config), config)
        rows = load_sheet_rows(path)

        row_number = result.ledger[0].row
        assert "ПКО 000123456" in str(rows[row_number - 1][2])
