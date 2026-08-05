"""CLI — §10 ТЗ. Четыре команды: ``analyze``, ``batch``, ``verify``, ``explain``.

Пакетный режим обязателен: сеть ПВЗ — десятки касс, нужна сводная таблица с
ранжированием по величине отклонения и числу находок (peer comparison, §15).

Флаги обратимости (§12): ``--no-collapse`` и ``--no-reversal-neutralization``
отключают любое автогашение и показывают сырую картину.
"""

from __future__ import annotations

from pathlib import Path

import typer

from cashforensics.models import AnalysisResult, Config

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

    Raises:
        NotImplementedError: каркас, реализация — этап 1 (§14).
    """
    raise NotImplementedError


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
