"""Стадия INGEST — §5.1 ТЗ.

Читает `.xlsx` (`read_only=True`, `data_only=True`), считает SHA-256 файла,
определяет позиции блоков опер-лога по §3.3 и извлекает шапку.

Ключевое требование §3.3: блоки определяются **исключительно по заголовкам**,
никогда по фиксированным индексам — наблюдались четыре разные раскладки.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import openpyxl

from cashforensics.models import (
    RULES_VERSION,
    BlockLayout,
    Config,
    FileMeta,
    IngestResult,
    ParseIssue,
)
from cashforensics.normalize import clean_text, parse_datetime

__all__ = [
    "HEADER_SCAN_ROWS",
    "build_meta",
    "extract_pvz_id",
    "extract_stated_period",
    "file_sha256",
    "find_header_row",
    "ingest",
    "load_sheet_rows",
    "locate_ops_blocks",
]

HEADER_SCAN_ROWS = 20
"""Глубина поиска строки-заголовка блоков — §3.3."""

_HASH_CHUNK = 1 << 20

_DATE_HEADER_PREFIX = "дата"
_AMOUNT_HEADER_PREFIX = "сумма"
_RKO_LABEL_RE = re.compile(r"кому|выдано", re.IGNORECASE)
_PKO_LABEL_RE = re.compile(r"от кого|принято", re.IGNORECASE)
_HEADER_MARKER_RE = re.compile(r"выдано|принято", re.IGNORECASE)

_PVZ_RE = re.compile(r"PAX\s*(\d{4,})", re.IGNORECASE)
_DATE_PATTERN = r"\d{1,2}[.\/-]\d{1,2}[.\/-]\d{4}"
_PERIOD_RE = re.compile(rf"({_DATE_PATTERN})\s*[-–—]\s*({_DATE_PATTERN})")

VARIANT_RKO_FIRST = "A"
VARIANT_PKO_FIRST = "B"
VARIANT_NO_RECIPIENT = "C"
VARIANT_NO_PKO = "D"
VARIANT_NO_BLOCKS = "НЕТ_БЛОКОВ"


def file_sha256(path: Path) -> str:
    """SHA-256 входного файла для метаданных отчёта — §5.1, §12."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def load_sheet_rows(path: Path) -> tuple[tuple[object, ...], ...]:
    """Прочитать единственный лист книги в матрицу значений — §5.1.

    Открывается строго ``read_only=True, data_only=True``: файлы достигают
    82 тыс. строк (§12, требование < 60 с).

    Строки выравниваются по ширине самой длинной: `openpyxl` обрезает хвостовые
    пустые ячейки, а блоки опер-лога стоят правее карточки, и без выравнивания
    индексы колонок «уезжают» от строки к строке.
    """
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        rows = [tuple(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()

    width = max((len(row) for row in rows), default=0)
    return tuple(row + (None,) * (width - len(row)) for row in rows)


def find_header_row(rows: Sequence[Sequence[object]]) -> int | None:
    """Найти строку-заголовок блоков опер-лога — §3.3.

    Ищет в первых :data:`HEADER_SCAN_ROWS` строках ячейку, начинающуюся с
    «Дата», и ячейку, содержащую «выдано» либо «принято».

    Returns:
        Индекс строки (0-based) либо ``None``, если блоков опер-лога нет.
    """
    for index in range(min(HEADER_SCAN_ROWS, len(rows))):
        texts = [clean_text(value) for value in rows[index]]
        has_date = any(text.lower().startswith(_DATE_HEADER_PREFIX) for text in texts)
        has_party = any(_HEADER_MARKER_RE.search(text) for text in texts)
        if has_date and has_party:
            return index
    return None


def _block_candidates(header: Sequence[object]) -> list[tuple[int, int, int | None, str]]:
    """Кандидаты «дата + сумма + метка» в строке заголовка — §3.3.

    Для каждой колонки с заголовком «Дата…» ищется колонка суммы среди
    ``(c+1, c+2)``, затем метка контрагента среди ``(amt+1, amt+2)``.

    Returns:
        Список ``(колонка_даты, колонка_суммы, колонка_метки, текст_метки)``.
        Колонка метки — ``None``, когда непустой метки рядом нет: это вариант C,
        где колонки «Кому выдано» не существует.
    """
    texts = [clean_text(value) for value in header]
    candidates: list[tuple[int, int, int | None, str]] = []

    for column, text in enumerate(texts):
        if not text.lower().startswith(_DATE_HEADER_PREFIX):
            continue

        amount_column = next(
            (
                index
                for index in (column + 1, column + 2)
                if index < len(texts) and texts[index].lower().startswith(_AMOUNT_HEADER_PREFIX)
            ),
            None,
        )
        if amount_column is None:
            continue

        label_column = next(
            (
                index
                for index in (amount_column + 1, amount_column + 2)
                if index < len(texts) and texts[index]
            ),
            None,
        )
        label = texts[label_column] if label_column is not None else ""
        candidates.append((column, amount_column, label_column, label))

    return candidates


def locate_ops_blocks(rows: Sequence[Sequence[object]]) -> BlockLayout:
    """Определить позиции блоков РКО и ПКО по заголовкам — §3.3.

    Отрабатывает все четыре наблюдавшихся варианта:

    * **A** — РКО левее ПКО, обе метки на месте;
    * **B** — блоки переставлены местами (Солигорск);
    * **C** — колонки «Кому выдано» нет: пара «дата + сумма» остаётся без
      распознанной метки, и она и есть блок РКО. Дальше §5.4 обязан применить
      time-fallback и **верифицировать** его;
    * **D** — блока ПКО в файле нет вовсе.

    Метка ищется среди ``(amt+1, amt+2)``, но колонкой контрагента становится
    ровно ``amt+1``, как задано псевдокодом §3.3.
    """
    header_row = find_header_row(rows)
    if header_row is None:
        return BlockLayout(header_row=-1, rko=None, pko=None, variant=VARIANT_NO_BLOCKS)

    rko: tuple[int, int, int | None] | None = None
    pko: tuple[int, int, int | None] | None = None
    unlabeled: list[tuple[int, int]] = []

    for date_column, amount_column, _label_column, label in _block_candidates(rows[header_row]):
        if _RKO_LABEL_RE.search(label):
            rko = (date_column, amount_column, amount_column + 1)
        elif _PKO_LABEL_RE.search(label):
            pko = (date_column, amount_column, amount_column + 1)
        else:
            unlabeled.append((date_column, amount_column))

    if rko is None and pko is not None and unlabeled:
        # Вариант C: у РКО нет колонки получателя, поэтому метка не распозналась.
        date_column, amount_column = unlabeled[0]
        rko = (date_column, amount_column, None)
        variant = VARIANT_NO_RECIPIENT
    elif rko is not None and pko is None:
        variant = VARIANT_NO_PKO
    elif rko is not None and pko is not None:
        variant = VARIANT_RKO_FIRST if rko[0] < pko[0] else VARIANT_PKO_FIRST
    else:
        variant = VARIANT_NO_BLOCKS

    return BlockLayout(header_row=header_row, rko=rko, pko=pko, variant=variant)


def extract_pvz_id(rows: Sequence[Sequence[object]]) -> str | None:
    """Извлечь идентификатор ПВЗ из шапки — §5.1.

    Строка вида ``Отбор: Кассы организации = PAX 119011650``.
    """
    for index in range(min(HEADER_SCAN_ROWS, len(rows))):
        for value in rows[index]:
            match = _PVZ_RE.search(clean_text(value))
            if match is not None:
                return f"PAX {match.group(1)}"
    return None


def extract_stated_period(
    rows: Sequence[Sequence[object]],
) -> tuple[datetime, datetime] | None:
    """Извлечь заявленный период из шапки — §5.1.

    **Не использовать для фильтрации.** Заявленный период регулярно не
    совпадает с фактическим: на Щучине шапка говорила «до 2025», данные шли до
    мая 2026. Значение идёт только в отчёт.
    """
    for index in range(min(HEADER_SCAN_ROWS, len(rows))):
        for value in rows[index]:
            match = _PERIOD_RE.search(clean_text(value))
            if match is None:
                continue
            start = parse_datetime(match.group(1))
            end = parse_datetime(match.group(2))
            if start is not None and end is not None:
                return (start, end)
    return None


def build_meta(path: Path, rows: Sequence[Sequence[object]], config: Config) -> FileMeta:
    """Собрать :class:`~cashforensics.models.FileMeta` — §4.4, §12.

    ``actual_period`` здесь не заполняется: он известен только после разбора
    проводок (§5.2) и проставляется конвейером.
    """
    stated = extract_stated_period(rows)
    return FileMeta(
        path=path,
        sha256=file_sha256(path),
        pvz_id=extract_pvz_id(rows),
        stated_period=(stated[0].date(), stated[1].date()) if stated is not None else None,
        actual_period=None,
        rules_version=RULES_VERSION,
        config_sha256=config.source_sha256 or "",
        run_timestamp=datetime.now(UTC),
    )


def ingest(path: Path, config: Config) -> IngestResult:
    """Стадия INGEST целиком — §5.1.

    Args:
        path: путь к выгрузке `.xlsx`.
        config: конфигурация §6.

    Returns:
        :class:`~cashforensics.models.IngestResult` с сырыми строками,
        раскладкой блоков и метаданными.
    """
    rows = load_sheet_rows(path)
    layout = locate_ops_blocks(rows)

    issues: list[ParseIssue] = []
    if layout.variant == VARIANT_NO_BLOCKS:
        issues.append(
            ParseIssue(
                row=0,
                column=None,
                reason=(
                    "блоки опер-лога не найдены по заголовкам: сверка с "
                    "фронтальной системой невозможна, приход и возвраты не "
                    "верифицируются"
                ),
                raw_value="",
            ),
        )
    elif layout.pko is None:
        issues.append(
            ParseIssue(
                row=layout.header_row + 1,
                column=None,
                reason=(
                    "блок ПКО отсутствует (вариант D): приход не верифицируется, "
                    "раскладка помечается «частично» (§16)"
                ),
                raw_value="",
            ),
        )
    elif layout.rko is not None and layout.rko[2] is None:
        issues.append(
            ParseIssue(
                row=layout.header_row + 1,
                column=layout.rko[0],
                reason=(
                    "колонка «Кому выдано» отсутствует (вариант C): требуется "
                    "time-fallback §3.3 с обязательной верификацией"
                ),
                raw_value="",
            ),
        )

    return IngestResult(
        meta=build_meta(path, rows, config),
        raw_rows=tuple(tuple(row) for row in rows),
        layout=layout,
        issues=tuple(issues),
    )
