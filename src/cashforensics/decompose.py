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
    CausalLevel,
    CausalLine,
    ClassifyResult,
    Finding,
    LocalizationResult,
    LocalizationStatus,
    Waterfall,
)
from cashforensics.reconcile import log_imbalance, within_ledger_period

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
    # Тот же срез периода, что и в §5.6: логовые слагаемые тождества обязаны
    # сокращаться, а для этого обе стороны должны считаться по одному ряду.
    imbalance = log_imbalance(within_ledger_period(classified.ops, classified.ledger))

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


def _finding_lines(findings: Sequence[Finding]) -> list[CausalLine]:
    """Строки уровня документа — находки §8 с трассировкой (§13.7)."""
    lines: list[CausalLine] = []
    for index, finding in enumerate(findings):
        if finding.balance_impact == _ZERO or finding.confidence < CAUSAL_CONFIDENCE_FLOOR:
            continue
        # §13.7: каждая строка причинной раскладки обязана прослеживаться до
        # строк исходного файла. Находка уровня выгрузки трассировки не имеет —
        # ``LOG_IMBALANCE`` §5.10 прямо назван «измеряется, но не объясняется»
        # (§16), а срез периода описывает границу выгрузки, а не документ.
        # Дисбаланс логов входит в раскладку структурной строкой ниже, как
        # того и требует §5.10 («выводится отдельной строкой»).
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
                level=CausalLevel.DOCUMENT,
            ),
        )
    return lines


def _claimed_here(
    item: LocalizationResult,
    claims: Sequence[tuple[frozenset[int], Decimal]],
) -> Decimal:
    """Сколько из дневного расхождения уже названо находкой §8.

    Отказ §7.4 меряет разницу дня целиком, и если часть этой разницы уже
    объяснена находкой по тем же строкам файла, вычесть её обязательно. На
    PAX_119023531 задвоенный ПКО 05.06.2023 (R87/R101, +1 400,00) и отказ §7.4
    за тот же день — это одни и те же рубли, и раскладка называла их дважды.
    """
    return sum(
        (impact for rows, impact in claims if rows & set(item.ledger_rows)),
        _ZERO,
    )


def _refusal_lines(
    localizations: Sequence[LocalizationResult],
    claims: Sequence[tuple[frozenset[int], Decimal]],
) -> list[CausalLine]:
    """Строки уровня дня и категории — отказы §7.4 и §5.6.

    В раскладку идут **не все** отказы, а только те, которые утверждают, до
    какого уровня расхождение доведено:

    * ``REFUSED_BELOW_Z_REPORT`` — §7.4 говорит буквально «расхождение
      локализовано до дня и до агрегата; ниже — требуется Z-отчёт». День,
      категория и величина известны точно, отказ касается только документа.
      Пока такие строки не попадали в раскладку, отчёт по Щучину показывал одну
      строку «не локализовано» на все −4 952,36, хотя §11.3 называет там
      остановку прихода 07–12.05.2026 на −15 440,69.
    * отказ по режиму встречных потоков §5.6 — то же самое уровнем выше: нетто
      категории известно из сверки, неизвестен разбор по дням. Это +8 301,10
      инкассации Щучина, которые §11.3 называет таймингом.

    Отказ гейтов §7.3 (``AMBIGUOUS`` и прочие ``REFUSED_*``) — не утверждение, а
    его отсутствие: доказательств не хватило. Такие дни остаются в строке «не
    локализовано», как и в эталонной раскладке §5.10 для Солигорска.

    Различие не косметическое. Гейтовые отказы односторонни по построению —
    §4.3 даёт непроведённой выдаче ``balance_impact = 0``, а завышенной проводке
    полную величину, — и их сумма меряет не расхождение, а перекос выборки: на
    Максиму_касса_2 (инкассация, ``ratio`` 0,052 — вплотную к гейту §5.6) 280
    таких дней давали −1 174 824,55 при нетто категории −217 581,09 и отклонении
    сальдо +2 617,79. §11.3 для этой кассы говорит «дискретных ошибок нет;
    расхождения распределены».

    Локализации с кодом сюда не идут: они уже стали находками §5.11 и учтены
    строкой уровня документа.
    """
    lines: list[CausalLine] = []
    for item in sorted(
        localizations,
        key=lambda result: (result.category.value, result.date, result.status.value),
    ):
        if item.code is not None or item.balance_impact == _ZERO:
            continue
        by_day = item.status is LocalizationStatus.REFUSED_BELOW_Z_REPORT
        # Отказ §5.6 — единственный без трассировки: он про категорию целиком.
        by_category = item.status is LocalizationStatus.NOT_LOCALIZED and not (
            item.ledger_rows or item.ops_rows
        )
        if not by_day and not by_category:
            continue
        amount = item.balance_impact - _claimed_here(item, claims)
        if amount == _ZERO:
            continue
        title = (
            f"{item.category.value} за {item.date:%d.%m.%Y}: сведено до дня и до агрегата, "
            f"ниже — требуется Z-отчёт за {item.date:%d.%m.%Y} (§7.4)"
            if by_day
            else (
                f"{item.category.value} за период: сведено до категории, разбор по дням "
                "неинформативен — режим встречных потоков (§5.6)"
            )
        )
        lines.append(
            CausalLine(
                amount=amount,
                title=title,
                finding_index=None,
                doc_numbers=tuple(item.doc_numbers),
                level=CausalLevel.DAY if by_day else CausalLevel.CATEGORY,
            ),
        )
    return lines


def _other_flow_line(
    classified: ClassifyResult,
    claimed_rows: frozenset[int],
) -> CausalLine | None:
    """Слагаемое «Прочие_Дт − Прочие_Кт» §5.10 отдельной строкой.

    Эталон §5.10 называет его прямо: «+112,67 размен между кассами + округления
    смены». Это не расхождение учёта, а поток вне трёх сверяемых категорий, и
    без него раскладка не сходится: на Максиму_3 те же рубли видны с двух
    сторон — пять ПКО по 76.9.1 (+119,00 здесь) и ровно те же пять дней прихода
    (−119,00), потому что в опер-логе эти ПКО лежат в блоке прихода, а §5.4
    держит дебет 76.9.1 вне прихода 1С. ТЗ требует «объяснять отдельной
    строкой, а не прятать».

    Строки, уже названные находкой (``UNKNOWN_ACCOUNT`` — тоже «прочее»),
    исключаются: иначе те же рубли попали бы в раскладку дважды.
    """
    entries = [
        entry
        for entry in classified.ledger
        if entry.category not in _RECONCILED and entry.row not in claimed_rows
    ]
    amount = sum((entry.debit - entry.credit for entry in entries), _ZERO)
    if amount == _ZERO:
        return None
    accounts = sorted({entry.counter_account for entry in entries if entry.counter_account})
    return CausalLine(
        amount=amount,
        title=(
            f"Прочие потоки вне сверки §5.6: {len(entries)} проводок "
            f"по счетам {', '.join(accounts)} — размен между кассами и прочие расчёты"
        ),
        finding_index=None,
        doc_numbers=tuple(
            entry.doc_number
            for entry in sorted(entries, key=lambda item: item.row)
            if entry.doc_number
        ),
        level=CausalLevel.STRUCTURE,
    )


def _unverified_categories(reconciliation: dict[Category, CategoryRecon]) -> tuple[Category, ...]:
    """Категории без блока опер-лога — вариант D §3.3, §11.3.

    Вариант D ломает два слагаемых §5.10 сразу: сверка §5.6 вычитает из
    оборотов 1С ноль, а «дисбаланс логов» вырождается в минус всю сумму РКО. Ни
    то, ни другое измерением не является — §11.3 говорит прямо: «нет ПКО →
    приход не верифицируется».

    Поэтому на таких кассах не выводится ни структурная строка дисбаланса, ни
    строка прихода: обе ушли бы в отчёт величинами, которых никто не измерял.
    Попытка показать их одной структурной строкой была не лучше — на Кса_норма
    получалось −335 397,43 «структуры» против +362 917,73 остатка при
    отклонении сальдо +10 632,25. Их место — строка «не проверено», и она
    называет причину.
    """
    return tuple(
        sorted(
            (category for category, recon in reconciliation.items() if not recon.verifiable),
            key=lambda category: category.value,
        ),
    )


_LEVEL_ORDER: dict[CausalLevel, int] = {
    CausalLevel.DOCUMENT: 0,
    CausalLevel.DAY: 1,
    CausalLevel.CATEGORY: 2,
    CausalLevel.STRUCTURE: 3,
    CausalLevel.RESIDUAL: 4,
}


def causal_decomposition(
    waterfall: Waterfall,
    findings: Sequence[Finding],
    localizations: Sequence[LocalizationResult],
    classified: ClassifyResult,
    reconciliation: dict[Category, CategoryRecon],
) -> tuple[CausalLine, ...]:
    """Перевести раскладку в причинную форму — §5.10.

    Вместо категорий — конкретные события. Строка уровня ``ДОКУМЕНТ`` ссылается
    на :class:`~cashforensics.models.Finding` с трассировкой; порог
    автоматического включения — ``confidence ≥ 0,90`` (§7.6).

    Ниже уровня документа раскладка не обрывается. §7.4 запрещает разложить
    дневной агрегат продаж на чеки — но день, категория и величина при этом
    известны точно, и прятать их в общий остаток значит терять ровно то, что
    §11.3 требует называть. Поэтому строки идут четырьмя уровнями (§4,
    :class:`~cashforensics.models.CausalLevel`), и «не локализовано» остаётся
    только за тем, чему носителя не нашлось вовсе.

    Эталон (PAX_119023531)::

        −2 579,00  R811 · РКО 00284721 от 09.08.2023 — возврат в 1С, выдачи нет
        +1 400,00  R87/R101 от 05.06.2023 — задвоенный ПКО на аванс
          +772,71  инкассация 30.06.2026 не проведена (срез периода)
          +112,67  размен между кассами + округления смены
        ─────────
          −293,62  = сальдо на конец
    """
    lines = _finding_lines(findings)
    claims = [
        (frozenset(_rows_of(findings, line)), line.amount)
        for line in lines
        if line.finding_index is not None
    ]
    claimed = frozenset(row for rows, _ in claims for row in rows)
    lines.extend(_refusal_lines(localizations, claims))

    other = _other_flow_line(classified, claimed)
    if other is not None:
        lines.append(other)

    unverified = _unverified_categories(reconciliation)
    if not unverified and waterfall.log_imbalance != _ZERO:
        lines.append(
            CausalLine(
                amount=waterfall.log_imbalance,
                title=(
                    f"Опер-лог не сходится сам с собой: ПКО минус все РКО дают "
                    f"{waterfall.log_imbalance} — дефект первички, причина вне обоих "
                    "файлов (§5.10, §16)"
                ),
                finding_index=None,
                doc_numbers=(),
                level=CausalLevel.STRUCTURE,
            ),
        )

    lines.sort(key=lambda line: (_LEVEL_ORDER[line.level], -abs(line.amount), line.title))

    explained = sum((line.amount for line in lines), _ZERO)
    remainder = (waterfall.closing - waterfall.target) - explained
    if remainder != _ZERO:
        names = ", ".join(category.value for category in unverified)
        lines.append(
            CausalLine(
                amount=remainder,
                title=(
                    f"не проверено: блока опер-лога для категории «{names}» в выгрузке "
                    "нет, обороты 1С по ней приняты как есть, дисбаланс логов §5.10 "
                    "не измерим (§3.3, §11.3)"
                )
                if unverified
                else (
                    "не отнесено ни к документу, ни ко дню, ни к категории — "
                    "доказательной базы в выгрузке нет"
                ),
                finding_index=None,
                doc_numbers=(),
                level=CausalLevel.RESIDUAL,
            ),
        )
    return tuple(lines)


def _rows_of(findings: Sequence[Finding], line: CausalLine) -> tuple[int, ...]:
    """Строки 1С, занятые причинной строкой уровня документа."""
    if line.finding_index is None:
        return ()
    return tuple(findings[line.finding_index].ledger_rows)


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
            "causal_lines": causal_decomposition(
                waterfall,
                findings,
                localizations,
                classified,
                reconciliation,
            ),
        },
    )
