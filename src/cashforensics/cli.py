"""CLI — §10 ТЗ. Четыре команды: ``analyze``, ``batch``, ``verify``, ``explain``.

Пакетный режим обязателен: сеть ПВЗ — десятки касс, нужна сводная таблица с
ранжированием по величине отклонения и числу находок (peer comparison, §15).

Флаги обратимости (§12): ``--no-collapse`` и ``--no-reversal-neutralization``
отключают любое автогашение и показывают сырую картину.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import typer

from cashforensics.balance import balance_trace
from cashforensics.classify import BlockClassificationFailed, classify
from cashforensics.decompose import check_tie, decompose
from cashforensics.ingest import ingest
from cashforensics.localize import localize
from cashforensics.models import AnalysisResult, Config, load_config
from cashforensics.normalize import actual_period, normalize
from cashforensics.rank import collect_findings, rank_findings
from cashforensics.reconcile import reconcile
from cashforensics.report.excel import render_excel
from cashforensics.report.html import render_html
from cashforensics.report.json_out import render_json
from cashforensics.reversals import neutralize_reversals
from cashforensics.signatures import collect_signatures
from cashforensics.timing import run_timing
from cashforensics.validate import ValidationFailed, validate

__all__ = ["analyze", "app", "batch", "explain", "main", "run_pipeline", "verify"]

app = typer.Typer(
    name="cashforensics",
    help="Форензик-анализ касс ПВЗ: сверка 1С с опер-логом и локализация причин отклонения сальдо.",
    no_args_is_help=True,
)

DEFAULT_CONFIG = Path("config/default.yaml")
"""Конфиг по умолчанию — §6."""

_ZERO = Decimal("0.00")


def run_pipeline(
    path: Path,
    config: Config,
    *,
    collapse: bool = True,
    neutralize: bool = True,
) -> AnalysisResult:
    """Прогнать все 12 стадий конвейера §5.

    ``ingest → normalize → validate → classify → neutralize_reversals →
    reconcile → collapse_timing → balance_trace → localize → decompose →
    rank → report``.

    Каждая стадия — чистая функция; вход не мутируется, промежуточный результат
    сериализуем (§5).

    Args:
        path: выгрузка `.xlsx`.
        config: конфигурация §6.
        collapse: ``False`` соответствует ``--no-collapse`` (§12).
        neutralize: ``False`` соответствует ``--no-reversal-neutralization``.

    Raises:
        ValidationFailed: нарушен жёсткий инвариант V1–V3 (§5.3).
        BlockClassificationFailed: time-fallback §3.3 не верифицирован.
    """
    ingested = ingest(path, config)
    normalized = normalize(ingested, config)
    validation = validate(normalized, config)
    classified = classify(normalized, config)
    reversals = neutralize_reversals(classified, config, enabled=neutralize)
    reconciliation = reconcile(classified, reversals, config)
    timing = run_timing(reconciliation, config, enabled=collapse)
    localizations = localize(classified, reversals, timing, config)
    balance = balance_trace(classified, normalized.totals.opening, config)
    waterfall = decompose(
        reconciliation,
        balance,
        classified,
        reversals.findings,
        localizations,
    )

    benchmark = sum(
        (entry.debit for entry in classified.ledger),
        _ZERO,
    )
    period = actual_period(classified.ledger)
    signatures = collect_signatures(classified, config)
    findings = rank_findings(
        collect_findings(
            reversals.findings,
            localizations,
            signatures,
            classified,
            validation,
            waterfall,
            period,
            benchmark,
            config,
        ),
        benchmark,
        config,
    )

    meta = ingested.meta.model_copy(update={"actual_period": period})

    return AnalysisResult(
        meta=meta,
        validation=validation,
        reconciliation=reconciliation,
        timing=timing,
        balance_trace=balance,
        waterfall=waterfall,
        findings=list(findings),
        signatures=list(signatures),
        localizations=list(localizations),
        audit_log=[*reversals.audit_log, *timing[next(iter(timing))].audit_log],
        unresolved=check_tie(waterfall),
    )


def _write_reports(
    result: AnalysisResult,
    out: Path,
    formats: str,
    *,
    audit_log: bool,
) -> list[Path]:
    """Записать отчёты запрошенных форматов — §9."""
    out.mkdir(parents=True, exist_ok=True)
    stem = result.meta.path.stem
    written: list[Path] = []
    requested = {item.strip().lower() for item in formats.split(",") if item.strip()}

    if "excel" in requested:
        written.append(render_excel(result, out / f"{stem}.xlsx", audit_log=audit_log))
    if "json" in requested:
        written.append(render_json(result, out / f"{stem}.json"))
    if "html" in requested:
        written.append(render_html(result, out / f"{stem}.html"))
    return written


@app.command()
def analyze(
    file: Path = typer.Argument(..., help="Выгрузка 1С «Карточка счёта 50.2» (.xlsx)"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Путь к YAML-конфигу §6"),
    target: str = typer.Option("", "--target", help="Целевое сальдо T (§5.8.2)"),
    out: Path = typer.Option(Path(), "--out", help="Каталог для отчётов"),
    output_format: str = typer.Option(
        "excel,json",
        "--format",
        help="Форматы через запятую: excel,json,html (§9)",
    ),
    audit_log: bool = typer.Option(False, "--audit-log", help="Лист журнала гашений (§12)"),
    no_collapse: bool = typer.Option(False, "--no-collapse", help="Отключить свёртку §5.7"),
    no_reversal_neutralization: bool = typer.Option(
        False,
        "--no-reversal-neutralization",
        help="Отключить нейтрализацию сторно §5.5",
    ),
) -> None:
    """Полный анализ одной кассы — §10."""
    settings = load_config(config)
    if target:
        try:
            settings = settings.model_copy(update={"target_balance": Decimal(target)})
        except InvalidOperation:
            typer.echo(f"--target «{target}» не является числом", err=True)
            raise typer.Exit(code=2) from None

    try:
        result = run_pipeline(
            file,
            settings,
            collapse=not no_collapse,
            neutralize=not no_reversal_neutralization,
        )
    except (ValidationFailed, BlockClassificationFailed) as failure:
        typer.echo(f"ОСТАНОВКА: {failure}", err=True)
        raise typer.Exit(code=1) from failure

    written = _write_reports(result, out, output_format, audit_log=audit_log)

    typer.echo(f"Касса:  {result.meta.pvz_id or file.stem}")
    typer.echo(f"Сальдо: {result.waterfall.closing}  (целевое {result.waterfall.target})")
    typer.echo(f"Несведённый остаток: {result.unresolved}")
    typer.echo(f"Находок: {len(result.findings)}, сигнатур: {len(result.signatures)}")
    localized = sum(1 for item in result.localizations if item.code is not None)
    typer.echo(f"Локализовано: {localized} из {len(result.localizations)} расхождений")
    for path in written:
        typer.echo(f"Отчёт: {path}")


@app.command()
def batch(
    directory: Path = typer.Argument(..., help="Каталог с выгрузками .xlsx"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Путь к YAML-конфигу §6"),
    summary: Path = typer.Option(
        Path("сводка.xlsx"),
        "--summary",
        help="Файл сводной таблицы по сети",
    ),
) -> None:
    """Пакетный прогон по директории — §10, §13.9.

    Формирует сводную таблицу с ранжированием по величине отклонения и числу
    находок. Кассы, на которых конвейер остановился (V1–V3 или §3.3), попадают
    в сводку отдельной строкой с причиной: молчаливо пропустить их нельзя.
    """
    from openpyxl import Workbook  # noqa: PLC0415

    from cashforensics.report.excel import write_row  # noqa: PLC0415

    settings = load_config(config)
    files = sorted(directory.glob("*.xlsx"))
    if not files:
        typer.echo(f"В каталоге {directory} нет файлов .xlsx", err=True)
        raise typer.Exit(code=2)

    rows: list[tuple[str, Decimal, int, int, str]] = []
    for path in files:
        try:
            result = run_pipeline(path, settings)
        except (ValidationFailed, BlockClassificationFailed) as failure:
            rows.append((path.stem, _ZERO, 0, 0, f"ОСТАНОВКА: {failure}"))
            typer.echo(f"{path.name}: остановка — {failure}", err=True)
            continue
        rows.append(
            (
                result.meta.pvz_id or path.stem,
                result.waterfall.closing - result.waterfall.target,
                len(result.findings),
                len(result.signatures),
                "",
            ),
        )
        typer.echo(f"{path.name}: отклонение {result.waterfall.closing}")

    # Ранжирование по величине отклонения — §13.9, peer comparison §15.
    rows.sort(key=lambda item: (-abs(item[1]), item[0]))

    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = "Сводка по сети"
    sheet.sheet_view.showGridLines = False
    write_row(
        sheet,
        ["ПВЗ", "Отклонение от целевого", "Находок", "Сигнатур", "Примечание"],
        bold=True,
    )
    for name, deviation, findings, signatures, note in rows:
        write_row(sheet, [name, deviation, findings, signatures, note])
    summary.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(summary)
    workbook.close()
    typer.echo(f"Сводка: {summary}")


@app.command()
def verify(
    file: Path = typer.Argument(..., help="Выгрузка .xlsx"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Путь к YAML-конфигу §6"),
) -> None:
    """Только валидация §5.3 — контроли V1–V6 без остального конвейера.

    Печатает раскладку блоков опер-лога (§3.3), контрольные суммы карточки и
    результат каждого контроля. Возвращает код 1, если нарушен жёсткий
    инвариант V1–V3: разбор неполон, и дальнейший анализ дал бы правдоподобный,
    но неверный результат (§5.3).
    """
    settings = load_config(config)
    ingested = ingest(file, settings)
    normalized = normalize(ingested, settings)

    typer.echo(f"Файл:     {file}")
    typer.echo(f"ПВЗ:      {ingested.meta.pvz_id or '—'}")
    typer.echo(f"Раскладка блоков: вариант {ingested.layout.variant}")
    period = actual_period(normalized.ledger)
    if period is not None:
        typer.echo(f"Период фактический: {period[0]:%d.%m.%Y} — {period[1]:%d.%m.%Y}")
    if ingested.meta.stated_period is not None:
        stated = ingested.meta.stated_period
        typer.echo(f"Период заявленный:  {stated[0]:%d.%m.%Y} — {stated[1]:%d.%m.%Y}")
    typer.echo(f"Проводок 1С: {len(normalized.ledger)}, записей опер-лога: {len(normalized.ops)}")
    typer.echo(f"Сальдо на начало: {normalized.totals.opening}")
    typer.echo(f"Сальдо на конец:  {normalized.totals.closing_stated}")
    typer.echo("")

    try:
        report = validate(normalized, settings)
    except ValidationFailed as failure:
        typer.echo(f"ОСТАНОВКА: {failure}", err=True)
        raise typer.Exit(code=1) from failure

    for check in report.checks:
        mark = "пропущен" if check.skipped else ("ок" if check.passed else "НЕ ПРОЙДЕН")
        typer.echo(f"{check.code} [{mark}] {check.message}")

    if normalized.issues:
        typer.echo("")
        typer.echo(f"Не разобрано строк: {len(normalized.issues)}")
        for issue in normalized.issues:
            typer.echo(f"  строка {issue.row}: {issue.reason}")


@app.command()
def explain(
    file: Path = typer.Argument(..., help="Выгрузка .xlsx"),
    finding: str = typer.Option(..., "--finding", help="Код находки из таксономии §8"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Путь к YAML-конфигу §6"),
) -> None:
    """Трассировка одной находки — §10, принцип объяснимости §0.2.

    Показывает, какое правило сработало, на каких исходных строках, какой
    остаток и чем погашен.
    """
    settings = load_config(config)
    try:
        result = run_pipeline(file, settings)
    except (ValidationFailed, BlockClassificationFailed) as failure:
        typer.echo(f"ОСТАНОВКА: {failure}", err=True)
        raise typer.Exit(code=1) from failure

    code = finding.strip().upper()
    matched = [item for item in result.findings if item.code.value == code]
    localized = [item for item in result.localizations if item.code and item.code.value == code]
    signatures = [item for item in result.signatures if item.code.value == code]

    if not (matched or localized or signatures):
        typer.echo(f"Находок с кодом {code} не найдено", err=True)
        raise typer.Exit(code=1)

    for found in matched:
        typer.echo(f"[{found.severity.value}] {found.title}")
        typer.echo(f"  {found.explanation}")
        typer.echo(f"  строки 1С: {found.ledger_rows}  строки лога: {found.ops_rows}")
        typer.echo(f"  трассировка: {found.evidence}")
        typer.echo("")
    for place in localized:
        typer.echo(f"[{place.status.value}] {place.date:%d.%m.%Y} {place.category.value}")
        typer.echo(f"  {place.explanation}")
        if place.gates is not None:
            typer.echo(
                f"  гейты §7.3: кандидатов {place.gates.candidate_count}, "
                f"решений {place.gates.solutions_found}, seed {place.gates.seed}",
            )
        typer.echo("")
    for signature in signatures:
        typer.echo(f"[сигнатура] {signature.title}")
        typer.echo(f"  {signature.explanation}")
        if signature.baseline:
            typer.echo(f"  контекст: {signature.baseline}")
        typer.echo("")


def main() -> None:
    """Точка входа консольного скрипта ``cashforensics``."""
    app()
