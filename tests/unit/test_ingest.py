"""Юнит-тесты стадии INGEST — §5.1, локация блоков §3.3."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cashforensics.ingest import (
    extract_pvz_id,
    extract_stated_period,
    file_sha256,
    find_header_row,
    ingest,
    load_sheet_rows,
    locate_ops_blocks,
)
from tests.conftest import BLOCK_VARIANTS, OpsRecord, Posting, SheetPlan

if TYPE_CHECKING:
    from collections.abc import Callable

    from cashforensics.models import Config

pytestmark = pytest.mark.unit

DAY = date(2024, 2, 1)


def _plan(variant: str) -> SheetPlan:
    return SheetPlan(
        variant=variant,
        postings=[
            Posting(DAY, "Приходный кассовый ордер 000123456", "50.2", Decimal("100.00"), "90.1.1"),
        ],
        rko=[OpsRecord(datetime(2024, 2, 1, 10, 0, 0), Decimal("40.00"), "Иванов Иван")],
        pko=[OpsRecord(datetime(2024, 2, 1, 11, 0, 0), Decimal("100.00"), "Петров Пётр")],
    )


@pytest.mark.parametrize("variant", ["A", "B", "C", "D"])
def test_blocks_located_in_all_four_variants(
    variant: str,
    make_workbook: Callable[[SheetPlan], Path],
) -> None:
    """Локация блоков во всех четырёх вариантах §3.3 — §11.1 ТЗ.

    Блоки ищутся по заголовкам, никогда по фиксированным индексам: раскладка
    плавает от файла к файлу.
    """
    rows = load_sheet_rows(make_workbook(_plan(variant)))

    layout = locate_ops_blocks(rows)

    rko_start, pko_start = BLOCK_VARIANTS[variant]
    assert layout.variant == variant
    assert layout.rko is not None
    assert layout.rko[0] == rko_start
    if pko_start is None:
        assert layout.pko is None
    else:
        assert layout.pko is not None
        assert layout.pko[0] == pko_start


def test_variant_b_does_not_swap_blocks(make_workbook: Callable[[SheetPlan], Path]) -> None:
    """Вариант B: ПКО левее РКО, и блоки не должны меняться ролями.

    На Солигорске блоки перевёрнуты; чтение по фиксированным индексам дало бы
    инкассацию вместо прихода.
    """
    rows = load_sheet_rows(make_workbook(_plan("B")))

    layout = locate_ops_blocks(rows)

    assert layout.pko is not None
    assert layout.rko is not None
    assert layout.pko[0] < layout.rko[0]


def test_variant_c_has_no_recipient_column(make_workbook: Callable[[SheetPlan], Path]) -> None:
    """Вариант C: колонки «Кому выдано» нет — §3.3.

    Блок РКО всё равно обязан быть найден: он опознаётся как пара
    «дата + сумма» без распознанной метки.
    """
    rows = load_sheet_rows(make_workbook(_plan("C")))

    layout = locate_ops_blocks(rows)

    assert layout.rko is not None
    assert layout.rko[2] is None
    assert layout.pko is not None
    assert layout.pko[2] is not None


def test_variant_d_has_no_pko_block(make_workbook: Callable[[SheetPlan], Path]) -> None:
    """Вариант D: блок ПКО отсутствует — приход не верифицируется (§16)."""
    rows = load_sheet_rows(make_workbook(_plan("D")))

    layout = locate_ops_blocks(rows)

    assert layout.pko is None
    assert layout.rko is not None


def test_header_row_found_within_scan_window(
    make_workbook: Callable[[SheetPlan], Path],
) -> None:
    """Строка-заголовок ищется в первых 20 строках — §3.3."""
    rows = load_sheet_rows(make_workbook(_plan("A")))

    assert find_header_row(rows) == 2


def test_pvz_and_stated_period_extracted(make_workbook: Callable[[SheetPlan], Path]) -> None:
    """Идентификатор ПВЗ и заявленный период читаются из шапки — §5.1."""
    rows = load_sheet_rows(make_workbook(_plan("A")))

    assert extract_pvz_id(rows) == "PAX 119011650"
    assert extract_stated_period(rows) == (
        datetime(2023, 5, 19, 0, 0, 0),
        datetime(2026, 6, 30, 0, 0, 0),
    )


def test_stated_period_is_not_used_for_filtering(
    make_workbook: Callable[[SheetPlan], Path],
    config: Config,
) -> None:
    """Заявленный период не обрезает данные — §5.1.

    На Щучине шапка говорила «до 2025», данные шли до мая 2026. Проводка вне
    заявленного окна обязана остаться в выгрузке.
    """
    plan = _plan("A")
    plan.stated_period = "01.01.2020 - 31.12.2020"

    result = ingest(make_workbook(plan), config)

    assert result.meta.stated_period == (date(2020, 1, 1), date(2020, 12, 31))
    assert any("01.02.2024" in str(cell) for row in result.raw_rows for cell in row)


def test_missing_pko_block_is_reported_not_swallowed(
    make_workbook: Callable[[SheetPlan], Path],
    config: Config,
) -> None:
    """Отсутствие блока ПКО попадает в отчёт о разборе — §12, §16."""
    result = ingest(make_workbook(_plan("D")), config)

    assert any("ПКО отсутствует" in issue.reason for issue in result.issues)


def test_missing_recipient_column_is_reported(
    make_workbook: Callable[[SheetPlan], Path],
    config: Config,
) -> None:
    """Вариант C помечается как требующий верифицируемого time-fallback — §3.3."""
    result = ingest(make_workbook(_plan("C")), config)

    assert any("time-fallback" in issue.reason for issue in result.issues)


def test_sha256_is_stable_and_matches_file(
    make_workbook: Callable[[SheetPlan], Path],
    config: Config,
) -> None:
    """Хеш файла попадает в метаданные и воспроизводим — §5.1, §12."""
    path = make_workbook(_plan("A"))

    result = ingest(path, config)

    assert result.meta.sha256 == file_sha256(path)
    assert result.meta.rules_version == "1.0"
    assert result.meta.config_sha256 == config.source_sha256


def test_rows_are_padded_to_uniform_width(make_workbook: Callable[[SheetPlan], Path]) -> None:
    """Строки выравниваются по ширине — иначе индексы колонок «уезжают» (§3.1)."""
    rows = load_sheet_rows(make_workbook(_plan("B")))

    assert len({len(row) for row in rows}) == 1
