"""Точка входа конвейера в браузере — Pyodide.

Здесь **нет** анализа. Вся логика — тот же пакет `cashforensics`, что работает
в CLI: страница вызывает :func:`analyze_bytes`, а он — :func:`run_pipeline`.
Второй реализации не существует, поэтому и расходиться нечему.

Предыдущая версия страницы содержала конвейер, переписанный на JavaScript
(`locateBlocks`, `reconcile`, `collapseTiming`, Левенштейн вместо
Jaro-Winkler). У неё не было ни гейтов §7.3, ни локализации §5.9, ни раскладки
§5.10, ни калибровки §11.3 — то есть ровно того, ради чего инструмент и
существует. Параллельная реализация неизбежно расходится с эталоном, и
единственный способ этого избежать — не иметь её.

Файл выгрузки не покидает браузер: Pyodide кладёт его в свою файловую систему
в памяти, отчёты собираются там же и отдаются на скачивание. Ни одного сетевого
запроса с данными кассы страница не делает — это обязательное свойство, потому
что блок РКО содержит ФИО получателей (§3.6).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cashforensics.cli import STAGES, run_pipeline
from cashforensics.models import AnalysisResult, Config, load_config
from cashforensics.report.excel import render_excel
from cashforensics.report.html import render_html
from cashforensics.report.json_out import render_json

if TYPE_CHECKING:
    from collections.abc import Callable

WORK = Path("/work")
"""Рабочий каталог в памяти Pyodide."""

TOTAL_STAGES = len(STAGES) + 1
"""Стадии §5 плюс сборка отчётов §9 — знаменатель полосы хода."""


def _silent(_number: int, _title: str) -> None:
    """Индикатор хода по умолчанию — не делает ничего."""


def _causal(result: AnalysisResult) -> list[dict[str, Any]]:
    """Причинная раскладка §5.10 — главный ответ инструмента."""
    return [
        {
            "amount": str(line.amount),
            "level": line.level.value,
            "title": line.title,
            "docs": ", ".join(line.doc_numbers),
            "residual": line.is_residual,
            "structure": not line.is_deviation and not line.is_residual,
        }
        for line in result.waterfall.causal_lines
    ]


def _findings(result: AnalysisResult) -> list[dict[str, Any]]:
    """Находки §8 в порядке ранжирования §5.11."""
    return [
        {
            "code": finding.code.value,
            "severity": finding.severity.value,
            "date": str(finding.date[0] if isinstance(finding.date, tuple) else finding.date),
            "amount": str(finding.amount),
            "impact": str(finding.balance_impact),
            "explanation": finding.explanation,
        }
        for finding in result.findings
    ]


def _reconciliation(result: AnalysisResult) -> list[dict[str, Any]]:
    """Сверка §5.6 по категориям."""
    return [
        {
            "category": category.value,
            "ledger": str(recon.acc_total),
            "ops": str(recon.ops_total),
            "net": str(recon.net),
            "ratio": "—" if recon.ratio is None else f"{recon.ratio:.3f}",
            "verifiable": recon.verifiable,
            "outside": str(recon.outside_period),
        }
        for category, recon in sorted(result.reconciliation.items(), key=lambda i: i[0].value)
    ]


def analyze_bytes(
    name: str,
    data: bytes,
    target: str = "",
    on_stage: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Разобрать выгрузку и вернуть сводку вместе с отчётами §9.

    Args:
        name: имя файла — попадает в метаданные отчёта (§12).
        data: содержимое ``.xlsx``.
        target: целевое сальдо ``T`` строкой; пусто — взять из конфига (§5.8.2).
        on_stage: обратный вызов ``(номер, название)`` — стадии §5 и сборка
            отчётов §9. Страница рисует по нему полосу хода: на Солигорске
            разбор идёт больше минуты.

    Returns:
        Словарь для страницы: сводка, раскладка, находки, сверка и три отчёта
        §9 в base64. ``base64`` потому, что через границу Python↔JS удобнее
        передать строку, чем буфер, а размер отчётов измеряется сотнями
        килобайт, не мегабайтами.
    """
    stage = on_stage if on_stage is not None else _silent
    config = _config(target)
    WORK.mkdir(parents=True, exist_ok=True)
    register = WORK / name
    register.write_bytes(data)

    result = run_pipeline(register, config, on_stage=stage)

    stage(len(STAGES) + 1, "Сборка отчётов §9")
    excel = render_excel(result, WORK / "отчёт.xlsx")
    payload = render_json(result, WORK / "отчёт.json")
    page = render_html(result, WORK / "отчёт.html")

    waterfall = result.waterfall
    localized = sum(1 for item in result.localizations if item.code is not None)
    return {
        "pvz": result.meta.pvz_id or name,
        "sha256": result.meta.sha256,
        "period": [str(day) for day in result.meta.actual_period]
        if result.meta.actual_period
        else None,
        "closing": str(waterfall.closing),
        "target": str(waterfall.target),
        "deviation": str(waterfall.closing - waterfall.target),
        "unresolved": str(result.unresolved),
        "overstated": str(waterfall.overstated()),
        "understated": str(waterfall.understated()),
        "structural": str(waterfall.structural()),
        "findings_total": len(result.findings),
        "signatures_total": len(result.signatures),
        "localized": localized,
        "localizations_total": len(result.localizations),
        "causal": _causal(result),
        "findings": _findings(result),
        "reconciliation": _reconciliation(result),
        "reports": {
            "xlsx": base64.b64encode(excel.read_bytes()).decode("ascii"),
            "json": base64.b64encode(payload.read_bytes()).decode("ascii"),
            "html": base64.b64encode(page.read_bytes()).decode("ascii"),
        },
    }


def _config(target: str) -> Config:
    """Конфиг §6 из ``/config/default.yaml`` с необязательной заменой ``T``.

    Файлы конфигурации страница кладёт в ту же файловую систему до запуска:
    их хеш попадает в каждый отчёт (§12), и подменять их «на лету» нельзя —
    иначе отчёт перестанет соответствовать заявленной версии правил.
    """
    config = load_config(Path("/config/default.yaml"))
    if not target.strip():
        return config
    from decimal import Decimal, InvalidOperation  # noqa: PLC0415  # только для этой ветки

    try:
        value = Decimal(target.strip().replace(",", "."))
    except InvalidOperation as error:
        message = f"целевое сальдо «{target}» не является числом"
        raise ValueError(message) from error
    return config.model_copy(update={"target_balance": value})
