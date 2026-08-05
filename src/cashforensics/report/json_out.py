"""JSON-отчёт — §9.2 ТЗ.

Полный :class:`~cashforensics.models.AnalysisResult` для интеграции и для
регрессионных тестов §11.3 (эталонные снимки).

Побитовая воспроизводимость (§13.5)
-----------------------------------
Повторный прогон одного файла при одной версии правил обязан давать **побитово
идентичный** JSON. Отсюда: сортированные ключи, фиксированный разделитель,
``ensure_ascii=False``, ``Decimal`` сериализуется строкой (не ``float``), даты —
ISO-8601. Никаких временных меток внутри тела, кроме явного ``meta.run_timestamp``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cashforensics.models import AnalysisResult

__all__ = [
    "JSON_INDENT",
    "JSON_SEPARATORS",
    "default_encoder",
    "render_json",
    "to_jsonable",
]

JSON_INDENT = 2
"""Отступ JSON — фиксирован ради стабильности диффа регрессии (§11.3)."""

JSON_SEPARATORS = (",", ": ")
"""Разделители — фиксированы ради побитовой воспроизводимости (§13.5)."""


def default_encoder(value: object) -> Any:
    """Кодировать ``Decimal``, ``date``, ``datetime``, ``Path``, ``Enum`` — §9.2.

    ``Decimal`` обязан уходить строкой: ``float`` теряет копейки и ломает
    сравнение с эталоном (§10).

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def to_jsonable(result: AnalysisResult) -> dict[str, Any]:
    """Привести результат к сериализуемому виду с детерминированным порядком — §9.2.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def render_json(result: AnalysisResult, path: Path) -> Path:
    """Записать JSON-отчёт — §9.2.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError
