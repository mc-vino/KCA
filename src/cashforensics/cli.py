"""CLI — §10 ТЗ. Четыре команды: ``analyze``, ``batch``, ``verify``, ``explain``.

Пакетный режим обязателен: сеть ПВЗ — десятки касс, нужна сводная таблица с
ранжированием по величине отклонения и числу находок (peer comparison, §15).

Флаги обратимости (§12): ``--no-collapse`` и ``--no-reversal-neutralization``
отключают любое автогашение и показывают сырую картину.
"""

from __future__ import annotations

from pathlib import Path

import typer

from cashforensics.ingest import ingest
from cashforensics.models import AnalysisResult, Config, load_config
from cashforensics.normalize import actual_period, normalize
from cashforensics.validate import ValidationFailed, validate

__all__ = ["analyze", "app", "batch", "explain", "main", "run_pipeline", "verify"]

app = typer.Typer(
    name="cashforensics",
    help="Форензик-анализ касс ПВЗ: сверка 1С с опер-логом и локализация причин отклонения сальдо.",
    no_args_is_help=True,
)

DEFAULT_CONFIG = Path("config/default.yaml")
"""Конфиг по умолчанию — §6."""


def run_pipeline(
    path: Path,
    config: Config,
    collapse: bool = True,
    neutralize_reversals: bool = True,
) -> AnalysisResult:
    """Прогнать все 12 стадий конвейера §5.

    ``ingest → normalize → validate → classify → neutralize_reversals →
    reconcile → collapse_timing → balance_trace → localize → decompose →
    rank → report``.

    Каждая стадия — чистая функция; вход не мутируется, промежуточный результат
    сериализуем (§5).

    Raises:
        NotImplementedError: каркас, реализация — этапы 1–4 (§14).
    """
    raise NotImplementedError


@app.command()
def analyze(
    file: Path = typer.Argument(..., help="Выгрузка 1С «Карточка счёта 50.2» (.xlsx)"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Путь к YAML-конфигу §6"),
    target: str = typer.Option("0.00", "--target", help="Целевое сальдо T (§5.8.2)"),
    out: Path = typer.Option(Path(), "--out", help="Каталог для отчётов"),
    output_format: str = typer.Option(
        "excel,json", "--format", help="Форматы через запятую: excel,json,html (§9)"
    ),
    audit_log: bool = typer.Option(False, "--audit-log", help="Лист журнала гашений (§12)"),
    no_collapse: bool = typer.Option(False, "--no-collapse", help="Отключить свёртку §5.7"),
    no_reversal_neutralization: bool = typer.Option(
        False,
        "--no-reversal-neutralization",
        help="Отключить нейтрализацию сторно §5.5",
    ),
) -> None:
    """Полный анализ одной кассы — §10.

    Raises:
        NotImplementedError: каркас, реализация — этапы 1–4 (§14).
    """
    raise NotImplementedError


@app.command()
def batch(
    directory: Path = typer.Argument(..., help="Каталог с выгрузками .xlsx"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Путь к YAML-конфигу §6"),
    summary: Path = typer.Option(
        Path("сводка.xlsx"), "--summary", help="Файл сводной таблицы по сети"
    ),
) -> None:
    """Пакетный прогон по директории — §10, §13.9.

    Формирует сводную таблицу с ранжированием по величине отклонения и числу
    находок. Файлы обрабатываются параллельно (§12), но порядок строк сводки
    детерминирован.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


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

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def main() -> None:
    """Точка входа консольного скрипта ``cashforensics``."""
    app()
