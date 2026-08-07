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

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
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

    ``Decimal`` обязан уходить **строкой**: ``float`` теряет копейки, и эталон
    §11.3 перестаёт сравниваться побитово (§10).

    Raises:
        TypeError: тип не сериализуем — молчаливая подмена на ``str`` скрыла бы
            дефект модели.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, frozenset | set):
        return sorted(value)
    message = f"тип {type(value).__name__} не сериализуем в JSON §9.2"
    raise TypeError(message)


def to_jsonable(result: AnalysisResult) -> dict[str, Any]:
    """Привести результат к сериализуемому виду — §9.2.

    Используется ``mode="python"``: pydantic отдаёт ``Decimal`` и ``date`` как
    есть, а превращает их в строки :func:`default_encoder` — так формат чисел
    задаётся в одном месте, а не двумя разными механизмами.
    """
    return result.model_dump(mode="python", by_alias=True)


def render_json(result: AnalysisResult, path: Path) -> Path:
    """Записать JSON-отчёт — §9.2.

    ``sort_keys=True`` обязателен: без него порядок ключей зависел бы от
    порядка объявления полей, и §13.5 держался бы на честном слове.
    """
    payload = json.dumps(
        to_jsonable(result),
        default=default_encoder,
        ensure_ascii=False,
        indent=JSON_INDENT,
        separators=JSON_SEPARATORS,
        sort_keys=True,
    )
    path.write_text(payload + "\n", encoding="utf-8")
    return path
