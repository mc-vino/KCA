"""Стадия INGEST — §5.1 ТЗ.

Читает `.xlsx` (`read_only=True`, `data_only=True`), считает SHA-256 файла,
определяет позиции блоков опер-лога по §3.3 и извлекает шапку.

Ключевое требование §3.3: блоки определяются **исключительно по заголовкам**,
никогда по фиксированным индексам — наблюдались четыре разные раскладки.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from cashforensics.models import BlockLayout, Config, FileMeta, IngestResult

__all__ = [
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


def file_sha256(path: Path) -> str:
    """SHA-256 входного файла для метаданных отчёта — §5.1, §12.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def load_sheet_rows(path: Path) -> tuple[tuple[object, ...], ...]:
    """Прочитать единственный лист книги в матрицу значений — §5.1.

    Открывать строго ``read_only=True, data_only=True``: файлы достигают
    82 тыс. строк (§12, требование < 60 с).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def find_header_row(rows: tuple[tuple[object, ...], ...]) -> int | None:
    """Найти строку-заголовок блоков опер-лога — §3.3.

    Ищет в первых :data:`HEADER_SCAN_ROWS` строках ячейку, начинающуюся с
    «Дата», и ячейку, содержащую «выдано» либо «принято».

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def locate_ops_blocks(rows: tuple[tuple[object, ...], ...]) -> BlockLayout:
    """Определить позиции блоков РКО и ПКО по заголовкам — §3.3.

    Алгоритм §3.3: для каждой колонки ``c`` с заголовком «Дата…» ищется колонка
    суммы среди ``(c+1, c+2)``, затем метка контрагента среди ``(amt+1, amt+2)``;
    ``/Кому|выдано/i`` → РКО, ``/От кого|принято/i`` → ПКО.

    Должно корректно отрабатывать все четыре варианта §3.3, включая вариант C
    (нет колонки «Кому выдано») и вариант D (блок ПКО отсутствует).

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def extract_pvz_id(rows: tuple[tuple[object, ...], ...]) -> str | None:
    """Извлечь идентификатор ПВЗ из шапки — §5.1.

    Строка вида ``Отбор: Кассы организации = PAX 119011650``.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def extract_stated_period(
    rows: tuple[tuple[object, ...], ...],
) -> tuple[date, date] | None:
    """Извлечь заявленный период из шапки — §5.1.

    **Не использовать для фильтрации.** Заявленный период регулярно не
    совпадает с фактическим: на Щучине шапка говорила «до 2025», данные шли до
    мая 2026. Значение идёт только в отчёт.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def build_meta(path: Path, rows: tuple[tuple[object, ...], ...], config: Config) -> FileMeta:
    """Собрать :class:`FileMeta` — §4.4, §12.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


def ingest(path: Path, config: Config) -> IngestResult:
    """Стадия INGEST целиком — §5.1.

    Args:
        path: путь к выгрузке `.xlsx`.
        config: конфигурация §6.

    Returns:
        :class:`IngestResult` с сырыми строками, раскладкой блоков и метаданными.

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError
