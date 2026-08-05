"""Smoke-тест окружения: все зависимости §10 ТЗ импортируются и работают.

Проверяет не факт установки, а работоспособность двух точек, на которых стоит
конвейер:

* ``ruptures.Pelt(model="l2")`` — основной детектор разладки §5.8.4;
* ``rapidfuzz.distance.JaroWinkler.similarity`` — сопоставление ФИО §5.9.2.

Тест намеренно не трогает бизнес-логику: он падает раньше остальных, если
окружение собрано неправильно.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_imports() -> None:
    """Все зависимости §10 ТЗ импортируются."""
    import numpy as np
    import openpyxl
    import pydantic
    import rapidfuzz
    import ruptures
    import scipy
    import typer
    import yaml

    for module in (np, openpyxl, pydantic, rapidfuzz, ruptures, scipy, typer, yaml):
        assert module is not None


def test_ruptures_pelt_constructs() -> None:
    """``ruptures.Pelt(model="l2")`` создаётся — §5.8.4 ТЗ.

    ``Pelt`` не хранит ``model`` как атрибут: строка разворачивается в объект
    стоимости, и проверять нужно ``algo.cost.model``.
    """
    import ruptures

    algo = ruptures.Pelt(model="l2")

    assert algo is not None
    assert algo.cost.model == "l2"


def test_ruptures_pelt_detects_level_shift() -> None:
    """PELT находит сдвиг уровня — §5.8.4 ТЗ, датирование смещения сальдо.

    Ряд из 50 нулей и 50 пятёрок — вырожденная модель «пола кассы», который
    скачком сместился (§5.8.3). PELT обязан вернуть точку разладки на границе.

    ``ruptures`` принимает ``float``; конвертация ``Decimal → float`` допустима
    только на входе в детектор, наружу возвращаются индексы, а не суммы (§10).
    """
    import numpy as np
    import ruptures

    signal = np.concatenate([np.zeros(50), np.full(50, 5.0)])

    breakpoints = ruptures.Pelt(model="l2", min_size=5).fit(signal).predict(pen=3)

    assert breakpoints[-1] == len(signal)
    assert 50 in breakpoints


def test_rapidfuzz_jaro_winkler_returns_number() -> None:
    """Jaro-Winkler возвращает число в [0, 1] — §5.9.2 ТЗ.

    Пара «Иванов» / «Ивaнов» содержит латинскую ``a`` в кириллическом слове:
    ровно тот случай смешанной раскладки, ради которого нужно нечёткое
    сравнение имён.
    """
    from rapidfuzz.distance import JaroWinkler

    similarity = JaroWinkler.similarity("Иванов", "Ивaнов")

    assert isinstance(similarity, float)
    assert 0.0 <= similarity <= 1.0
    assert similarity > 0.5


def test_scipy_linear_sum_assignment_available() -> None:
    """Венгерский алгоритм доступен — §5.9.2 ТЗ, проход 2."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    rows, cols = linear_sum_assignment(np.array([[1.0, 2.0], [2.0, 1.0]]))

    assert rows.tolist() == [0, 1]
    assert cols.tolist() == [0, 1]


def test_package_imports() -> None:
    """Пакет ``cashforensics`` импортируется и объявляет версию правил."""
    import cashforensics

    assert cashforensics.RULES_VERSION == "1.0"


def test_pipeline_modules_are_skeletons() -> None:
    """Все 12 стадий §5 присутствуют и честно не реализованы.

    Каркас обязан падать ``NotImplementedError``, а не возвращать
    правдоподобную заглушку: принцип «отказ вместо догадки» (§0.3 ТЗ)
    действует и на стадии разработки.
    """
    from cashforensics import (
        balance,
        classify,
        decompose,
        ingest,
        localize,
        normalize,
        rank,
        reconcile,
        reversals,
        signatures,
        timing,
        validate,
    )

    modules = (
        ingest,
        normalize,
        validate,
        classify,
        reversals,
        reconcile,
        timing,
        balance,
        localize,
        decompose,
        rank,
        signatures,
    )

    assert len(modules) == 12
    for module in modules:
        assert module.__doc__ is not None


def test_config_files_exist() -> None:
    """Конфигурация §6 и календарь §5.7.3 лежат на месте и парсятся."""
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parent.parent
    default = yaml.safe_load((root / "config" / "default.yaml").read_text(encoding="utf-8"))
    holidays = yaml.safe_load((root / "config" / "holidays_by.yaml").read_text(encoding="utf-8"))

    expected_sections = {
        "accounts",
        "patterns",
        "thresholds",
        "subset_sum",
        "changepoint",
        "statistics",
        "signatures",
        "materiality",
        "calendar",
    }

    assert expected_sections <= set(default)
    assert default["cash_account"] == "50.2"
    assert holidays["country"] == "BY"
