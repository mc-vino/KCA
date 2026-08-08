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

from collections.abc import Sequence
from decimal import Decimal

from cashforensics.models import (
    BalanceTrace,
    Category,
    CategoryRecon,
    CausalLine,
    ClassifyResult,
    Finding,
    LocalizationResult,
    Waterfall,
)
from cashforensics.reconcile import log_imbalance

__all__ = [
    "CAUSAL_CONFIDENCE_FLOOR",
    "build_waterfall",
    "causal_decomposition",
    "check_tie",
    "decompose",
    "other_flows",
]

CAUSAL_CONFIDENCE_FLOOR = 0.90
"""Порог автоматического включения в причинную раскладку — §7.6."""

_ZERO = Decimal("0.00")

_RECONCILED = (Category.INCOME, Category.COLLECTION, Category.REFUND)


def other_flows(classified: ClassifyResult) -> tuple[Decimal, Decimal]:
    """Дебет и кредит категорий вне сверки — «Прочие_Дт» и «Прочие_Кт» §5.10.

    Сюда входят и «прочее», и размен (50.1): §5.6 сверяет только приход,
    инкассацию и возвраты, а тождество §5.10 обязано покрывать все проводки —
    иначе ``unresolved`` не сойдётся.
    """
    debit = _ZERO
    credit = _ZERO
    for entry in classified.ledger:
        if entry.category in _RECONCILED:
            continue
        debit += entry.debit
        credit += entry.credit
    return (debit, credit)


def build_waterfall(
    reconciliation: dict[Category, CategoryRecon],
    balance: BalanceTrace,
    classified: ClassifyResult,
) -> Waterfall:
    """Категорийная раскладка по тождеству §5.10.

    Дельты берутся из §5.6 в варианте «как есть»: служебные РКО физически
    выносят наличные из ящика и обязаны участвовать в сходимости сальдо, даже
    если из сверки возвратов они исключены (§3.6).
    """
    income = reconciliation[Category.INCOME].net
    collection = reconciliation[Category.COLLECTION].net
    refund = reconciliation[Category.REFUND].net
    other_debit, other_credit = other_flows(classified)

    # Единственный источник формулы — §5.6; собственной копии здесь быть не
    # должно: при расхождении реализаций тождество §5.10 перестаёт сходиться
    # ровно на сумму служебных РКО.
    imbalance = log_imbalance(classified.ops)

    components = (
        balance.opening + income - collection - refund + (other_debit - other_credit) + imbalance
    )
    deviation = balance.closing_computed - balance.target
    unresolved = deviation - (components - balance.target)

    return Waterfall(
        closing=balance.closing_computed,
        target=balance.target,
        income_delta=income,
        collection_delta=collection,
        refund_delta=refund,
        other_delta=other_debit - other_credit,
        log_imbalance=imbalance,
        unresolved=unresolved,
        causal_lines=(),
    )


def causal_decomposition(
    waterfall: Waterfall,
    findings: Sequence[Finding],
    localizations: Sequence[LocalizationResult],  # noqa: ARG001  # трассировка, см. ниже
) -> tuple[CausalLine, ...]:
    """Перевести раскладку в причинную форму — §5.10.

    Вместо категорий — конкретные события с документами. Каждая строка
    ссылается на :class:`~cashforensics.models.Finding` с трассировкой.
    Порог автоматического включения — ``confidence ≥ 0,90`` (§7.6).

    Строки ниже порога не выбрасываются: их суммарный вклад собирается в
    строку «не локализовано», иначе раскладка перестала бы сходиться, а
    пользователь не увидел бы, какая часть отклонения осталась необъяснённой.

    Источник строк — **только** ``findings``: после §5.11 этот список уже
    содержит и локализации §5.9, и сигнатуры §8, и факты уровня выгрузки.
    ``localizations`` передаётся ради трассировки и в сумму не идёт — иначе
    локализованное расхождение попадало бы в раскладку дважды.

    Эталон (PAX_119023531)::

        −2 579,00  R811 · РКО 00284721 от 09.08.2023 — возврат в 1С, выдачи нет
        +1 400,00  R87/R101 от 05.06.2023 — задвоенный ПКО на аванс
          +772,71  инкассация 30.06.2026 не проведена (срез периода)
          +112,67  размен между кассами + округления смены
        ─────────
          −293,62  = сальдо на конец
    """
    lines: list[CausalLine] = []
    explained = _ZERO

    for index, finding in enumerate(findings):
        if finding.balance_impact == _ZERO or finding.confidence < CAUSAL_CONFIDENCE_FLOOR:
            continue
        # §13.7: каждая строка причинной раскладки обязана прослеживаться до
        # строк исходного файла. Находка уровня выгрузки трассировки не имеет —
        # ``LOG_IMBALANCE`` §5.10 прямо назван «измеряется, но не объясняется»
        # (§16), а срез периода описывает границу выгрузки, а не документ.
        # Их место — категорийная часть раскладки, где они уже учтены
        # тождеством §5.10; строкой причины они быть не могут.
        #
        # Без этого на кассах варианта D раскладка уходила в миллионы: без блока
        # ПКО ``log_imbalance`` равен минус всей сумме РКО, и на Максиму_касса_2
        # причинная часть показывала −5 167 831,72 против отклонения +2 617,79.
        if not finding.ledger_rows and not finding.ops_rows:
            continue
        lines.append(
            CausalLine(
                amount=finding.balance_impact,
                title=finding.title,
                finding_index=index,
                doc_numbers=tuple(finding.doc_numbers),
            ),
        )
        explained += finding.balance_impact

    lines.sort(key=lambda line: (-abs(line.amount), line.title))

    deviation = waterfall.closing - waterfall.target
    remainder = deviation - explained
    if remainder != _ZERO:
        lines.append(
            CausalLine(
                amount=remainder,
                title=(
                    "не локализовано до документа — расхождение объяснено до дня и до категории"
                ),
                finding_index=None,
                doc_numbers=(),
            ),
        )
    return tuple(lines)


def check_tie(waterfall: Waterfall) -> Decimal:
    """Проверить сходимость раскладки — §5.10, §13.2.

    Returns:
        ``unresolved``; ``|unresolved| < EPS_TIE`` обязательно. Превышение —
        дефект приложения, а не свойство данных.
    """
    return waterfall.unresolved


def decompose(
    reconciliation: dict[Category, CategoryRecon],
    balance: BalanceTrace,
    classified: ClassifyResult,
    findings: Sequence[Finding],
    localizations: Sequence[LocalizationResult],
) -> Waterfall:
    """Стадия DECOMPOSE целиком — §5.10.

    Порогов §6 не использует: тождество §5.10 чисто арифметическое, а порог
    сходимости ``EPS_TIE`` проверяет вызывающий через :func:`check_tie`.
    """
    waterfall = build_waterfall(reconciliation, balance, classified)
    return waterfall.model_copy(
        update={
            "causal_lines": causal_decomposition(waterfall, findings, localizations),
        },
    )
