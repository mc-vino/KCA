"""Фикстуры регрессии §11.3 — поиск калибровочных выгрузок и снимок результата.

Сами `.xlsx` в репозиторий не попадают: блок РКО содержит ФИО получателей
(§3.6). Поэтому путь к ним берётся из переменной окружения
``CASHFORENSICS_FIXTURES`` либо из каталога ``fixtures/`` рядом с тестом, а при
отсутствии файла тест **пропускается с явной причиной** — не падает и не
подменяется синтетикой: подмена эталона синтетикой превращает регрессию в
самоподтверждающийся тест.

Из той же причины следует состав снимка. В него идут только величины, коды,
номера документов и номера строк — то, что §11.3 называет критерием
(«совпадение сальдо, состава причинной раскладки (коды, суммы, документы) и
остатков свёртки»). Свободный текст — объяснения находок, титулы сигнатур — не
идёт **никогда**: объяснение §8.1 цитирует получателя выдачи поимённо, и снимок
с ним стал бы способом закоммитить ФИО в обход `.gitignore`.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from cashforensics.cli import run_pipeline
from cashforensics.models import AnalysisResult, Config

if TYPE_CHECKING:
    from collections.abc import Callable

FIXTURE_DIR_ENV = "CASHFORENSICS_FIXTURES"
"""Переменная окружения с каталогом калибровочных выгрузок §11.3."""

REGISTERS: tuple[str, ...] = (
    "PAX_119011650",
    "PAX_119023531",
    "PAX_119049688",
    "Кса_норма",
    "Кса_с_отклонением",
    "Максиму_3",
    "Максиму_касса_2",
    "Щучин",
    "горновых",
)
"""Девять калибровочных касс §11.3 в детерминированном порядке (§12)."""


def fixture_dir() -> Path:
    """Каталог калибровочных выгрузок — из окружения либо рядом с тестом."""
    override = os.environ.get(FIXTURE_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(params=REGISTERS)
def register_name(request: pytest.FixtureRequest) -> str:
    """Имя калибровочной кассы §11.3."""
    return str(request.param)


@pytest.fixture
def register_file(register_name: str) -> Path:
    """Путь к выгрузке; пропуск с причиной, если её нет на диске."""
    path = fixture_dir() / f"{register_name}.xlsx"
    if not path.exists():
        pytest.skip(
            f"калибровочная выгрузка {register_name}.xlsx не найдена в {fixture_dir()}; "
            f"положите её туда или укажите каталог через {FIXTURE_DIR_ENV}. "
            "Синтетикой эталон §11.3 не подменяется",
        )
    return path


_CACHE: dict[tuple[Path, str | None], AnalysisResult] = {}


@pytest.fixture
def analysis(register_file: Path, config: Config) -> AnalysisResult:
    """Результат конвейера, посчитанный один раз на кассу.

    Солигорск — 82 611 строк, и шесть прогонов на кассу давали пять с половиной
    минут на весь §11.3. Кэш безопасен ровно потому, что §13.5 требует
    детерминированности: если два прогона расходятся, это ловит отдельный тест,
    который кэш намеренно **не** использует.
    """
    key = (register_file, config.source_sha256)
    if key not in _CACHE:
        _CACHE[key] = run_pipeline(register_file, config)
    return _CACHE[key]


def _validation(result: AnalysisResult) -> dict[str, Any]:
    return {
        check.code: ("пропущен" if check.skipped else "прошёл" if check.passed else "НЕ ПРОШЁЛ")
        for check in sorted(result.validation.checks, key=lambda item: item.code)
    }


def _reconciliation(result: AnalysisResult) -> dict[str, Any]:
    return {
        category.value: {
            "1С": str(recon.acc_total),
            "лог": str(recon.ops_total),
            "нетто": str(recon.net),
            "брутто": str(recon.gross),
            "ratio": None if recon.ratio is None else f"{recon.ratio:.6f}",
            "верифицируется": recon.verifiable,
            "дней_с_расхождением": recon.days_with_difference,
        }
        for category, recon in sorted(result.reconciliation.items(), key=lambda item: item[0].value)
    }


def _timing(result: AnalysisResult) -> dict[str, Any]:
    return {
        category.value: {
            "остаток": str(collapse.residual),
            "снято": collapse.collapsed,
            "передатировано": collapse.redated,
            "дней_всего": collapse.total,
            "дней_в_остатке": len(collapse.residual_days),
            "лаг": None if collapse.lag is None else collapse.lag.best_lag,
        }
        for category, collapse in sorted(result.timing.items(), key=lambda item: item[0].value)
    }


def _causal(result: AnalysisResult) -> list[dict[str, Any]]:
    """Состав раскладки: суммы, уровень, коды и номера документов — §11.3."""
    return [
        {
            "сумма": str(line.amount),
            "уровень": line.level.value,
            "код": (
                None
                if line.finding_index is None
                else result.findings[line.finding_index].code.value
            ),
            "документы": list(line.doc_numbers),
        }
        for line in result.waterfall.causal_lines
    ]


def _findings(result: AnalysisResult) -> dict[str, Any]:
    """Находки — по кодам §8, без свободного текста (в нём ФИО получателя)."""
    counts: dict[str, int] = {}
    impacts: dict[str, Decimal] = {}
    severities: dict[str, str] = {}
    for finding in result.findings:
        code = finding.code.value
        counts[code] = counts.get(code, 0) + 1
        impacts[code] = impacts.get(code, Decimal("0.00")) + finding.balance_impact
        severities.setdefault(code, finding.severity.value)
    return {
        code: {
            "штук": counts[code],
            "уровень": severities[code],
            "на_сальдо": str(impacts[code]),
        }
        for code in sorted(counts)
    }


def _localizations(result: AnalysisResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in result.localizations:
        counts[item.status.value] = counts.get(item.status.value, 0) + 1
    return dict(sorted(counts.items()))


def digest(result: AnalysisResult) -> dict[str, Any]:
    """Обезличенный снимок результата — то, что сравнивает регрессия §11.3.

    ``meta.run_timestamp`` исключён намеренно: он и есть отметка прогона (§9.2),
    единственное законное различие между двумя запусками.
    """
    floor = result.balance_trace.nonnegativity
    return {
        "сальдо": str(result.waterfall.closing),
        "целевое": str(result.waterfall.target),
        "несведённый": str(result.unresolved),
        "период": [str(day) for day in result.meta.actual_period]
        if result.meta.actual_period
        else None,
        "первый_минус": (
            None if floor.first_below_target is None else str(floor.first_below_target)
        ),
        "минимум_сальдо": str(floor.minimum),
        "валидация": _validation(result),
        "сверка": _reconciliation(result),
        "свёртка": _timing(result),
        "раскладка": _causal(result),
        "находки": _findings(result),
        "локализации": _localizations(result),
    }


@pytest.fixture
def make_digest() -> Callable[[AnalysisResult], dict[str, Any]]:
    """Обезличенный снимок результата для сравнения со снапшотом."""
    return digest


__all__ = [
    "FIXTURE_DIR_ENV",
    "REGISTERS",
    "analysis",
    "digest",
    "fixture_dir",
    "make_digest",
    "register_file",
    "register_name",
]
