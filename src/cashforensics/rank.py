"""Стадия RANK — §5.11 ТЗ, материальность §7.5, confidence §7.6.

Сортировка находок: ``severity → materiality → |balance_impact| → confidence
→ дата``. Ключ полный и явный (§12): порядок обязан быть побитово
воспроизводимым между прогонами (§13.5).

Находки ниже тривиального порога агрегируются в одну строку «мелкие
расхождения», а не выводятся поштучно (§5.11).
"""

from __future__ import annotations

from decimal import Decimal

from cashforensics.models import (
    Config,
    Finding,
    Materiality,
    MaterialityThresholds,
)

__all__ = [
    "CONFIDENCE_LOCALIZED",
    "CONFIDENCE_PROBABLE",
    "aggregate_trivial",
    "classify_materiality",
    "confidence_score",
    "materiality_thresholds",
    "rank_findings",
    "sort_key",
]

CONFIDENCE_LOCALIZED = 0.90
"""≥ 0,90 — «локализовано»; порог автовключения в причинную раскладку (§7.6)."""

CONFIDENCE_PROBABLE = 0.72
"""0,72–0,90 — «вероятно»; ниже — «требует ручной проверки» (§7.6)."""


def materiality_thresholds(benchmark: Decimal, config: Config) -> MaterialityThresholds:
    """Пороги материальности от бенчмарка — §7.5.

    ``overall = overall_pct × бенчмарк`` (оборот периода),
    ``performance = performance_pct × overall`` (практика: 50–75 % от overall),
    ``тривиальное = trivial_pct × overall`` (практика: 3–5 % от overall).

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def classify_materiality(
    amount: Decimal,
    thresholds: MaterialityThresholds,
) -> Materiality:
    """Отнести сумму к уровню материальности — §7.5.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def confidence_score(
    uniqueness: float,
    p_value: float,
    materiality_norm: float,
    supporting_signals: int,
    weights: tuple[float, float, float, float],
) -> float:
    """Оценка уверенности — §7.6.

    ``confidence = w1·уникальность + w2·(1 − p_value) + w3·материальность_норм
    + w4·число_подтверждающих_признаков_норм``. Веса конфигурируемы.

    Интерпретация: ≥ :data:`CONFIDENCE_LOCALIZED` — «локализовано»;
    ≥ :data:`CONFIDENCE_PROBABLE` — «вероятно»; ниже — «требует ручной
    проверки».

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def sort_key(finding: Finding) -> tuple[int, int, Decimal, float, str]:
    """Полный явный ключ сортировки — §5.11, §12.

    Порядок: ``severity → materiality → |balance_impact| → confidence → дата``.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def aggregate_trivial(
    findings: tuple[Finding, ...],
    thresholds: MaterialityThresholds,
) -> tuple[Finding, ...]:
    """Свернуть находки ниже тривиального порога в одну строку — §5.11.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError


def rank_findings(
    findings: tuple[Finding, ...],
    benchmark: Decimal,
    config: Config,
) -> tuple[Finding, ...]:
    """Стадия RANK целиком — §5.11.

    Raises:
        NotImplementedError: каркас, реализация — этап 4 (§14).
    """
    raise NotImplementedError
