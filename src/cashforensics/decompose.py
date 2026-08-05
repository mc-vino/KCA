"""Стадия DECOMPOSE — §5.10 ТЗ. Раскладка отклонения без остатка.

Тождество, которое обязано выполняться::

    Сальдо_конец − T
      = (Приход_1С − ПКО)
      − (Инкассация_1С − РКО_инкассация)
      − (Возвраты_1С − РКО_возвраты)
      + (Прочие_Дт − Прочие_Кт)
      + (ПКО − РКО_инкассация − РКО_возвраты)      ← дисбаланс самих логов
      − T

Последнее слагаемое выводится **отдельной строкой** и не смешивается с
расхождениями 1С: это дефект первички, а не учёта.

Требование приёмки (§13.2): ``|unresolved| < EPS_TIE`` (2,00 по умолчанию).
Если раскладка не сходится — это дефект приложения, а не свойство данных.
"""

from __future__ import annotations

from decimal import Decimal

from cashforensics.models import (
    BalanceTrace,
    Category,
    CategoryRecon,
    CausalLine,
    ClassifyResult,
    Config,
    Finding,
    LocalizationResult,
    Waterfall,
)

__all__ = [
    "build_waterfall",
    "causal_decomposition",
    "check_tie",
    "decompose",
]


def build_waterfall(
    reconciliation: dict[Category, CategoryRecon],
    balance: BalanceTrace,
    classified: ClassifyResult,
    config: Config,
) -> Waterfall:
    """Категорийная раскладка по тождеству §5.10.

    Raises:
        NotImplementedError: каркас, реализация — этап 3 (§14).
    """
    raise NotImplementedError


def causal_decomposition(
    waterfall: Waterfall,
    findings: tuple[Finding, ...],
    localizations: tuple[LocalizationResult, ...],
    config: Config,
) -> tuple[CausalLine, ...]:
    """Перевести раскладку в причинную форму — §5.10.

    Вместо категорий — конкретные события с документами. Каждая строка обязана
    ссылаться на :class:`~cashforensics.models.Finding` с трассировкой.
    Порог автоматического включения — ``confidence ≥ 0,90`` (§7.6).

    Эталон (PAX_119023531)::

        −2 579,00  R811 · РКО 00284721 от 09.08.2023 — возврат в 1С, выдачи нет
        +1 400,00  R87/R101 от 05.06.2023 — задвоенный ПКО на аванс
          +772,71  инкассация 30.06.2026 не проведена (срез периода)
          +112,67  размен между кассами + округления смены
        ─────────
          −293,62  = сальдо на конец

    Raises:
        NotImplementedError: каркас, реализация — этап 3 (§14).
    """
    raise NotImplementedError


def check_tie(waterfall: Waterfall, config: Config) -> Decimal:
    """Проверить сходимость раскладки — §5.10, §13.2.

    Returns:
        ``unresolved``; ``|unresolved| < EPS_TIE`` обязательно.

    Raises:
        NotImplementedError: каркас, реализация — этап 3 (§14).
    """
    raise NotImplementedError


def decompose(
    reconciliation: dict[Category, CategoryRecon],
    balance: BalanceTrace,
    classified: ClassifyResult,
    findings: tuple[Finding, ...],
    localizations: tuple[LocalizationResult, ...],
    config: Config,
) -> Waterfall:
    """Стадия DECOMPOSE целиком — §5.10.

    Raises:
        NotImplementedError: каркас, реализация — этап 3 (§14).
    """
    raise NotImplementedError
