"""HTML-отчёт — §9.3 ТЗ. Опциональный формат.

Одностраничный отчёт для быстрого просмотра. Без внешних зависимостей, кроме
CDN-шрифтов. Палитра и формулировки — те же, что в Excel (§9.1): «расхождение»,
«требует проверки», «сигнатура», но не «фрод», «кража», «виновен» (§1.2).
"""

from __future__ import annotations

from pathlib import Path

from cashforensics.models import AnalysisResult, Config

__all__ = [
    "render_html",
    "render_section_cause",
    "render_section_findings",
    "render_section_limitations",
]


def render_section_cause(result: AnalysisResult, config: Config) -> str:
    """Секция «Причина» — причинная раскладка без остатка (§5.10, §9.1.1).

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def render_section_findings(result: AnalysisResult, config: Config) -> str:
    """Секция находок в порядке ранжирования §5.11.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def render_section_limitations(result: AnalysisResult, config: Config) -> str:
    """Секция «Известные ограничения» — §16, обязательна в каждом отчёте.

    Включает границы доказуемости §1.3 и развилку «какая из систем права».

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def render_html(result: AnalysisResult, path: Path, config: Config) -> Path:
    """Собрать HTML-отчёт целиком — §9.3.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError
