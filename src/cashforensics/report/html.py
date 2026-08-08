"""HTML-отчёт — §9.3 ТЗ. Опциональный формат.

Одностраничный отчёт для быстрого просмотра. Без внешних зависимостей, кроме
CDN-шрифтов. Палитра и формулировки — те же, что в Excel (§9.1): «расхождение»,
«требует проверки», «сигнатура», но не «фрод», «кража», «виновен» (§1.2).
"""

from __future__ import annotations

import html
from pathlib import Path

from cashforensics.models import AnalysisResult
from cashforensics.rank import confidence_label
from cashforensics.report.excel import COLORS

__all__ = [
    "render_html",
    "render_section_cause",
    "render_section_findings",
    "render_section_limitations",
]

_STYLE = f"""
body {{ font-family: Arial, sans-serif; color: #{COLORS["ink"]}; margin: 2rem auto;
        max-width: 60rem; line-height: 1.5; }}
h1, h2 {{ color: #{COLORS["steel"]}; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
th, td {{ border-bottom: 1px solid #{COLORS["hair"]}; padding: 0.4rem 0.6rem;
          text-align: left; vertical-align: top; }}
th {{ background: #{COLORS["hair"]}; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.error td {{ background: #{COLORS["red_bg"]}; }}
tr.review td {{ background: #{COLORS["amber_bg"]}; }}
tr.normal td {{ background: #{COLORS["lime_bg"]}; }}
.caveat {{ background: #{COLORS["amber_bg"]}; padding: 1rem; border-radius: 4px; }}
"""

_SEVERITY_CLASS = {"ОШИБКА": "error", "ПРОВЕРИТЬ": "review", "НОРМА": "normal"}


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _cause_rows(lines: object, caption: str, total: object) -> str:
    """Блок раскладки с подытогом — §5.6, §9.1.1."""
    body = "".join(
        f"<tr><td class='num'>{_esc(line.amount)}</td><td>{_esc(line.title)}</td>"
        f"<td>{_esc(', '.join(line.doc_numbers))}</td></tr>"
        for line in lines  # type: ignore[attr-defined]
    )
    if not body:
        return ""
    return (
        f"<tr class='normal'><td class='num'><strong>{_esc(total)}</strong></td>"
        f"<td colspan='2'><strong>{_esc(caption)}</strong></td></tr>{body}"
    )


def render_section_cause(result: AnalysisResult) -> str:
    """Секция «Причина» — причинная раскладка без остатка (§5.10, §9.1.1).

    Раскладка показывается **двумя сторонами**, как их называет §5.6:
    переучтённое и недоучтённое. Одной колонкой она нечитаема на кассах со
    встречными потоками: на Солигорске переучтено −10 946,54 при недоучтённых
    +2 893,74 и полном отклонении −1 224,80, и плоский список выглядел так,
    будто отклонение в девять раз больше, чем оно есть.
    """
    waterfall = result.waterfall
    named = [line for line in waterfall.causal_lines if not line.is_residual]
    residual = [line for line in waterfall.causal_lines if line.is_residual]
    rows = (
        _cause_rows(
            [line for line in named if line.amount < 0],
            "Переучтено в 1С — проведено больше факта",
            waterfall.overstated(),
        )
        + _cause_rows(
            [line for line in named if line.amount > 0],
            "Недоучтено в 1С — проведено меньше факта",
            waterfall.understated(),
        )
        + "".join(
            f"<tr class='review'><td class='num'>{_esc(line.amount)}</td>"
            f"<td colspan='2'>{_esc(line.title)}</td></tr>"
            for line in residual
        )
    )
    return (
        "<h2>Причина отклонения сальдо</h2>"
        "<table><tr><th>Сумма</th><th>Причина</th><th>Документы</th></tr>"
        f"{rows}</table>"
        f"<p><strong>Сальдо на конец:</strong> {_esc(waterfall.closing)}, "
        f"целевое {_esc(waterfall.target)}, "
        f"несведённый остаток {_esc(waterfall.unresolved)}.</p>"
    )


def render_section_findings(result: AnalysisResult) -> str:
    """Секция находок в порядке ранжирования §5.11."""
    rows = ""
    for finding in result.findings:
        day = finding.date[0] if isinstance(finding.date, tuple) else finding.date
        css = _SEVERITY_CLASS.get(finding.severity.value, "")
        rows += (
            f"<tr class='{css}'><td>{_esc(finding.code.value)}</td>"
            f"<td>{_esc(finding.severity.value)}</td>"
            f"<td>{_esc(day)}</td>"
            f"<td class='num'>{_esc(finding.amount)}</td>"
            f"<td class='num'>{_esc(finding.balance_impact)}</td>"
            f"<td>{_esc(confidence_label(finding.confidence))}</td>"
            f"<td>{_esc(finding.explanation)}</td></tr>"
        )
    return (
        "<h2>Находки</h2>"
        "<table><tr><th>Код</th><th>Уровень</th><th>Дата</th><th>Сумма</th>"
        "<th>На сальдо</th><th>Уверенность</th><th>Объяснение</th></tr>"
        f"{rows}</table>"
    )


def render_section_limitations(result: AnalysisResult) -> str:
    """Секция «Известные ограничения» — §16, обязательна в каждом отчёте.

    Включает границы доказуемости §1.3 и развилку «какая из систем права».
    """
    refused = sum(1 for item in result.localizations if item.code is None)
    unverifiable = "".join(
        f"<li>Категория «{category.value}» не верифицируется: блока опер-лога для неё "
        f"в выгрузке нет (§3.3). Обороты 1С по ней — {recon.acc_total} — приняты как "
        "есть, встречной проверки не было.</li>"
        for category, recon in sorted(
            result.reconciliation.items(),
            key=lambda item: item[0].value,
        )
        if not recon.verifiable
    )
    return (
        "<h2>Что проверить и чего инструмент не знает</h2>"
        "<div class='caveat'><ul>"
        f"{unverifiable}"
        "<li>Инструмент не может сказать, какая из двух систем права: 1С или опер-лог. "
        "Если суммы в проблемных ордерах подтвердятся подписями клиентов, ошибка "
        "окажется в выгрузке фронтальной системы, а не в 1С.</li>"
        "<li>Дисбаланс самих логов измеряется, но не объясняется: его причина лежит "
        "вне обоих файлов.</li>"
        "<li>Сигнатуры повторов не являются уликой: базовая частота повторов в этих "
        "данных высока.</li>"
        "<li>Датировка смещения даётся окном; точная дата из ряда сальдо не выводима."
        "</li>"
        f"<li>Расхождений, не сведённых до документа: {refused}. Для них локализация "
        "остаётся на уровне дня и категории — доказательная база недостаточна.</li>"
        "</ul></div>"
    )


def render_html(result: AnalysisResult, path: Path) -> Path:
    """Собрать HTML-отчёт целиком — §9.3."""
    meta = result.meta
    document = (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        f"<title>Форензик-анализ кассы {_esc(meta.pvz_id or '')}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f"<h1>Форензик-анализ кассы {_esc(meta.pvz_id or meta.path.name)}</h1>"
        f"<p>Файл: {_esc(meta.path.name)}<br>SHA-256: {_esc(meta.sha256)}<br>"
        f"Версия правил: {_esc(meta.rules_version)}, хеш конфига "
        f"{_esc(meta.config_sha256[:16])}<br>Прогон: {_esc(meta.run_timestamp)}</p>"
        f"{render_section_cause(result)}"
        f"{render_section_findings(result)}"
        f"{render_section_limitations(result)}"
        "</body></html>"
    )
    path.write_text(document, encoding="utf-8")
    return path
