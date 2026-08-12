"""Регрессия на девяти калибровочных кассах — §11.3 ТЗ.

Уровень выше синтетики §11.2: там дефект внедряется и ищется, здесь конвейер
целиком сверяется с зафиксированным поведением на настоящих выгрузках. Ловит то,
что синтетика поймать не может, — правку, которая формально проходит все
юнит-тесты, но меняет разбор реальных данных.

Снапшоты `syrupy` лежат в `__snapshots__/`. Обновляются осознанно:
``uv run pytest tests/regression --snapshot-update`` — и каждое изменение
снимка обязано быть объяснено в коммите. Молчаливое обновление снапшота
превращает регрессию в тавтологию.

Обязательные критерии §13, закреплённые здесь:

* §13.1 — V1–V3 проходят на всех девяти;
* §13.2 — ``|unresolved| < EPS_TIE`` на всех девяти;
* §13.5 — повторный прогон даёт побитово идентичный JSON.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cashforensics.cli import run_pipeline
from cashforensics.report.json_out import render_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import Any

    from cashforensics.models import AnalysisResult, Config

pytestmark = pytest.mark.regression

_HARD_CHECKS = frozenset({"V1", "V2", "V3"})
"""Контроли, нарушение которых §5.3 велит считать остановкой, а не замечанием."""


class TestCalibration:
    """Девять касс §11.3: поведение конвейера зафиксировано снимком."""

    def test_matches_snapshot(
        self,
        analysis: AnalysisResult,
        make_digest: Callable[[AnalysisResult], dict[str, Any]],
        snapshot: Any,
    ) -> None:
        """Снимок покрывает сальдо, сверку, свёртку, раскладку и находки.

        Свободного текста в снимке нет: объяснение находки §8.1 цитирует
        получателя выдачи поимённо, и снапшот с ним стал бы способом
        закоммитить ФИО в обход `.gitignore`.
        """
        assert make_digest(analysis) == snapshot

    def test_hard_validations_pass(self, analysis: AnalysisResult) -> None:
        """§13.1: V1–V3 проходят на всех девяти кассах.

        Именно этот контроль поймал чтение сальдо не из той колонки на Щучине
        (§3.2) и подтвердил, что все кассы распарсены полностью.
        """
        result = analysis

        failed = [
            check.code
            for check in result.validation.checks
            if check.code in _HARD_CHECKS and not check.skipped and not check.passed
        ]
        assert failed == [], result.validation.checks

    def test_waterfall_ties(self, analysis: AnalysisResult, config: Config) -> None:
        """§13.2: раскладка §5.10 сходится без остатка.

        Превышение ``EPS_TIE`` — дефект приложения, а не свойство данных.
        """
        assert abs(analysis.waterfall.unresolved) < config.thresholds.EPS_TIE

    def test_causal_lines_cover_the_deviation(self, analysis: AnalysisResult) -> None:
        """Причинная раскладка обязана покрывать отклонение целиком — §5.10."""
        result = analysis

        total = sum(
            (line.amount for line in result.waterfall.causal_lines),
            result.waterfall.target - result.waterfall.target,
        )
        assert total == result.waterfall.closing - result.waterfall.target

    def test_second_run_is_byte_identical(
        self,
        register_file: Path,
        config: Config,
        tmp_path: Path,
    ) -> None:
        """§13.5: один вход при одной версии правил — побитово тот же выход.

        Сравниваются **байты** JSON, а не разобранный объект: недетерминизм
        порядка ключей или итерации по множеству разбор скрыл бы. Кэш фикстуры
        ``analysis`` здесь намеренно не используется: он бы сравнил результат
        сам с собой.
        """
        first = run_pipeline(register_file, config)
        second = run_pipeline(register_file, config)
        meta = second.meta.model_copy(update={"run_timestamp": first.meta.run_timestamp})
        stamped = second.model_copy(update={"meta": meta})

        assert render_json(first, tmp_path / "1.json").read_bytes() == (
            render_json(stamped, tmp_path / "2.json").read_bytes()
        )

    def test_no_report_qualifies_the_finding(self, analysis: AnalysisResult) -> None:
        """§1.2, §13.10: квалификация находки инструментом запрещена.

        Проверяется на настоящих данных, а не на синтетике: формулировки
        §5.9 подставляют в текст реальные суммы и номера, и запрещённое слово
        может прийти из шаблона, который синтетика не задевает.
        """
        result = analysis
        forbidden = ("фрод", "кража", "виновен", "хищен", "мошенн", "двойная выдача")

        texts = [item.explanation for item in result.localizations]
        texts += [item.explanation for item in result.findings]
        texts += [line.title for line in result.waterfall.causal_lines]
        for text in texts:
            lowered = text.lower()
            assert not [word for word in forbidden if word in lowered], text
