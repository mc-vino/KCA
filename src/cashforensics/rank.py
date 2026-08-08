"""Стадия RANK — §5.11 ТЗ, материальность §7.5, confidence §7.6.

Сортировка находок: ``severity → materiality → |balance_impact| → confidence
→ дата``. Ключ полный и явный (§12): порядок обязан быть побитово
воспроизводимым между прогонами (§13.5).

Находки ниже тривиального порога агрегируются в одну строку «мелкие
расхождения», а не выводятся поштучно (§5.11).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from cashforensics.models import (
    ClassifyResult,
    Config,
    Finding,
    FindingCode,
    LedgerEntry,
    LocalizationResult,
    Materiality,
    MaterialityThresholds,
    OpsClass,
    Severity,
    Signature,
    ValidationReport,
    Waterfall,
)

__all__ = [
    "CODE_SEVERITY",
    "CONFIDENCE_LOCALIZED",
    "CONFIDENCE_PROBABLE",
    "CONFIDENCE_SIGNATURE",
    "CONFIDENCE_WEIGHTS",
    "MATERIALITY_ORDER",
    "SEVERITY_ORDER",
    "aggregate_trivial",
    "classify_materiality",
    "collect_findings",
    "confidence_label",
    "confidence_score",
    "finding_materiality",
    "materiality_thresholds",
    "rank_findings",
    "sort_key",
]

CONFIDENCE_LOCALIZED = 0.90
"""≥ 0,90 — «локализовано»; порог автовключения в причинную раскладку (§7.6)."""

CONFIDENCE_PROBABLE = 0.72
"""0,72–0,90 — «вероятно»; ниже — «требует ручной проверки» (§7.6)."""

CONFIDENCE_WEIGHTS = (0.25, 0.25, 0.25, 0.25)
"""Веса ``(w1, w2, w3, w4)`` формулы §7.6.

§7.6 объявляет их конфигурируемыми, но §6 их не задаёт. Равные веса — самое
слабое из возможных предположений: они не отдают предпочтения ни одному из
четырёх признаков. Менять их следует здесь, а не в конфиге кассы: иначе
одинаковые данные дадут разный состав причинной раскладки.
"""

CONFIDENCE_SIGNATURE = 0.50
"""Уверенность сигнатуры §8 — ниже :data:`CONFIDENCE_PROBABLE` намеренно.

Сигнатура не проходит формулу §7.6: у неё нет ни меры уникальности, ни
p-value — это флаг похожести, а не сведённое расхождение. Единственная
корректная её интерпретация задана самим ТЗ: «требует точечной проверки»
(§8.1). Значение подобрано так, чтобы :func:`confidence_label` выдавал именно
эту формулировку, и не должно подниматься ради «красивого» отчёта.
"""

CODE_SEVERITY: dict[FindingCode, Severity] = {
    FindingCode.RKO_WITHOUT_PAYOUT: Severity.ERROR,
    FindingCode.RKO_OVERSTATED: Severity.ERROR,
    FindingCode.PKO_DOUBLE_BOOKED: Severity.ERROR,
    FindingCode.PAYOUT_NOT_BOOKED: Severity.REVIEW,
    FindingCode.REVERSAL_PAIR: Severity.INFO,
    FindingCode.REVERSAL_UNMATCHED: Severity.REVIEW,
    FindingCode.REVERSAL_WITHOUT_REBOOK: Severity.REVIEW,
    FindingCode.SERVICE_MISCLASSIFIED: Severity.INFO,
    FindingCode.POSTING_DELAY: Severity.REVIEW,
    FindingCode.SHIFT_ROUNDING: Severity.NORMAL,
    FindingCode.PERIOD_CUTOFF: Severity.NORMAL,
    FindingCode.LOG_IMBALANCE: Severity.INFO,
    FindingCode.REPEAT_PAYOUT: Severity.REVIEW,
    FindingCode.LATE_TIME_DOC: Severity.REVIEW,
    FindingCode.SEQUENCE_GAP: Severity.REVIEW,
    FindingCode.DUPLICATE_DOC: Severity.REVIEW,
    FindingCode.UNKNOWN_ACCOUNT: Severity.INFO,
}
"""Severity по коду — колонка «Severity» таблицы §8, без исключений."""

_BALANCE_AFFECTING: frozenset[FindingCode] = frozenset(
    {
        FindingCode.SHIFT_ROUNDING,
        FindingCode.PERIOD_CUTOFF,
        FindingCode.LOG_IMBALANCE,
        FindingCode.UNKNOWN_ACCOUNT,
    },
)
"""Коды сигнатурного происхождения, у которых ``balance_impact`` ≠ 0 (§8).

Остальные сигнатуры (``REPEAT_PAYOUT``, ``LATE_TIME_DOC``, ``SEQUENCE_GAP``)
по таблице §8 на сальдо не влияют: повтор выдачи проведён 1С агрегатом, а
пропуск номера — это отсутствие документа, а не проводки.
"""

SEVERITY_ORDER: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.REVIEW: 1,
    Severity.NORMAL: 2,
    Severity.INFO: 3,
}
"""Порядок severity в сортировке §5.11: ошибки первыми."""

MATERIALITY_ORDER: dict[Materiality, int] = {
    Materiality.MATERIAL: 0,
    Materiality.IMMATERIAL: 1,
    Materiality.TRIVIAL: 2,
}
"""Порядок материальности в сортировке §5.11."""

_ZERO = Decimal("0.00")
_MIN_TO_AGGREGATE = 2
"""Одну тривиальную находку сворачивать не во что."""

_MAX_SUPPORTING = 4
"""Нормировка числа подтверждающих признаков в §7.6."""


def materiality_thresholds(benchmark: Decimal, config: Config) -> MaterialityThresholds:
    """Пороги материальности от бенчмарка — §7.5.

    ``overall = overall_pct × бенчмарк`` (оборот периода),
    ``performance = performance_pct × overall`` (практика: 50–75 % от overall),
    ``тривиальное = trivial_pct × overall`` (практика: 3–5 % от overall).
    """
    overall = benchmark * Decimal(str(config.materiality.overall_pct))
    return MaterialityThresholds(
        benchmark=benchmark,
        overall=overall,
        performance=overall * Decimal(str(config.materiality.performance_pct)),
        trivial=overall * Decimal(str(config.materiality.trivial_pct)),
    )


def classify_materiality(
    amount: Decimal,
    thresholds: MaterialityThresholds,
) -> Materiality:
    """Отнести сумму к уровню материальности — §7.5.

    Ниже «явно тривиального» — ``ТРИВИАЛЬНО``; от него до performance —
    ``НЕСУЩЕСТВЕННО``; выше — ``СУЩЕСТВЕННО``.
    """
    magnitude = abs(amount)
    if magnitude < thresholds.trivial:
        return Materiality.TRIVIAL
    if magnitude < thresholds.performance:
        return Materiality.IMMATERIAL
    return Materiality.MATERIAL


def finding_materiality(
    amount: Decimal,
    balance_impact: Decimal,
    thresholds: MaterialityThresholds,
) -> Materiality:
    """Материальность находки — §7.5 с поправкой на находки без суммы.

    ``SEQUENCE_GAP`` и ``LATE_TIME_DOC`` денежной величины не имеют вовсе:
    пропуск номера — это отсутствие документа, а не сумма. Нулевая сумма
    формально ниже любого порога, и §5.11 свернул бы такую находку в строку
    «мелкие расхождения» — то есть спрятал бы «ПРОВЕРИТЬ» под «НОРМА».
    Агрегация §5.11 меряет деньги, поэтому находки без денежной величины в неё
    не попадают и получают ``НЕСУЩЕСТВЕННО``: на отчётность они не влияют, но
    остаются в списке.
    """
    if amount == _ZERO and balance_impact == _ZERO:
        return Materiality.IMMATERIAL
    return classify_materiality(balance_impact or amount, thresholds)


def confidence_score(
    uniqueness: float,
    p_value: float,
    materiality_norm: float,
    supporting_signals: int,
    weights: tuple[float, float, float, float] = CONFIDENCE_WEIGHTS,
) -> float:
    """Оценка уверенности — §7.6.

    ``confidence = w1·уникальность + w2·(1 − p_value) + w3·материальность_норм
    + w4·число_подтверждающих_признаков_норм``.

    Интерпретация: ≥ :data:`CONFIDENCE_LOCALIZED` — «локализовано»;
    ≥ :data:`CONFIDENCE_PROBABLE` — «вероятно»; ниже — «требует ручной
    проверки». Результат зажимается в ``[0, 1]``.
    """
    w1, w2, w3, w4 = weights
    supporting = min(supporting_signals, _MAX_SUPPORTING) / _MAX_SUPPORTING
    score = w1 * uniqueness + w2 * (1.0 - p_value) + w3 * materiality_norm + w4 * supporting
    return max(0.0, min(1.0, score))


def confidence_label(confidence: float) -> str:
    """Словесная интерпретация уверенности для отчёта — §7.6."""
    if confidence >= CONFIDENCE_LOCALIZED:
        return "локализовано"
    if confidence >= CONFIDENCE_PROBABLE:
        return "вероятно"
    return "требует ручной проверки"


def _finding_date(finding: Finding) -> date:
    """Первая дата находки: у периода берётся начало — §5.11, ключ сортировки."""
    return finding.date[0] if isinstance(finding.date, tuple) else finding.date


def sort_key(finding: Finding) -> tuple[int, int, Decimal, float, date, str]:
    """Полный явный ключ сортировки — §5.11, §12.

    Порядок: ``severity → materiality → |balance_impact| → confidence → дата``.
    Хвостом добавлен код находки: без него две находки, совпавшие по всем пяти
    признакам, могли бы менять порядок между прогонами (§13.5).
    """
    return (
        SEVERITY_ORDER[finding.severity],
        MATERIALITY_ORDER[finding.materiality],
        -abs(finding.balance_impact),
        -finding.confidence,
        _finding_date(finding),
        finding.code.value,
    )


def aggregate_trivial(
    findings: Sequence[Finding],
    thresholds: MaterialityThresholds,
) -> tuple[Finding, ...]:
    """Свернуть находки ниже тривиального порога в одну строку — §5.11.

    Поштучный вывод мелочи топит существенное: на кассе с тысячами операций
    тривиальных расхождений сотни. Свёрнутая строка сохраняет и сумму, и
    номера строк, поэтому трассировка §12 не теряется.

    Сворачиваются только ``НОРМА`` и ``ИНФО``. Порог тривиального берётся от
    оборота периода (§7.5), и на Солигорске он равен 2 812,74 при полном
    отклонении сальдо 1 224,80 — под него попадает вообще всё, включая
    ``RKO_OVERSTATED``. Свернуть ошибку в строку уровня ``НОРМА`` значит
    понизить её уровень, тогда как §5.11 сортирует по severity первым ключом
    именно чтобы ошибки оставались наверху. Вдобавок эти же суммы названы
    поимённо в причинной раскладке §5.10 — отчёт противоречил бы сам себе.
    Агрегация сжимает хвост, а не переклассифицирует находки.
    """
    foldable = {Severity.NORMAL, Severity.INFO}
    trivial = [
        item
        for item in findings
        if item.materiality is Materiality.TRIVIAL and item.severity in foldable
    ]
    if len(trivial) < _MIN_TO_AGGREGATE:
        return tuple(findings)

    folded = {id(item) for item in trivial}
    rest = [item for item in findings if id(item) not in folded]
    total = sum((item.balance_impact for item in trivial), _ZERO)
    aggregated = Finding(
        code=FindingCode.SHIFT_ROUNDING,
        severity=Severity.NORMAL,
        date=min(_finding_date(item) for item in trivial),
        amount=sum((abs(item.amount) for item in trivial), _ZERO),
        ledger_rows=sorted({row for item in trivial for row in item.ledger_rows}),
        ops_rows=sorted({row for item in trivial for row in item.ops_rows}),
        doc_numbers=sorted({number for item in trivial for number in item.doc_numbers}),
        title=f"Мелкие расхождения, {len(trivial)} шт.",
        explanation=(
            f"{len(trivial)} находок ниже порога тривиального ({thresholds.trivial}) "
            f"собраны в одну строку; суммарный вклад в отклонение {total}. "
            "Поштучный разбор не требуется."
        ),
        evidence={
            "rule": "§5.11 агрегация тривиального",
            "trivial_threshold": str(thresholds.trivial),
            "codes": sorted({item.code.value for item in trivial}),
        },
        confidence=1.0,
        materiality=Materiality.TRIVIAL,
        balance_impact=total,
    )
    return (*rest, aggregated)


_LEDGER_SOURCED: frozenset[FindingCode] = frozenset(
    {FindingCode.SEQUENCE_GAP, FindingCode.DUPLICATE_DOC, FindingCode.SHIFT_ROUNDING},
)
"""Сигнатуры, чьи ``rows`` — строки карточки счёта, а не опер-лога (§8)."""


def _signature_finding(
    signature: Signature,
    period: tuple[date, date],
    thresholds: MaterialityThresholds,
) -> Finding:
    """Перевести сигнатуру §8 в находку таксономии §4.3."""
    amount = signature.amount if signature.amount is not None else _ZERO
    impact = amount if signature.code in _BALANCE_AFFECTING else _ZERO
    rows = list(signature.rows)
    ledger_sourced = signature.code in _LEDGER_SOURCED
    explanation = signature.explanation
    if signature.baseline:
        explanation = f"{explanation} Базовая частота: {signature.baseline}."
    return Finding(
        code=signature.code,
        severity=signature.severity or CODE_SEVERITY[signature.code],
        date=signature.date if signature.date is not None else period,
        amount=amount,
        ledger_rows=rows if ledger_sourced else [],
        ops_rows=[] if ledger_sourced else rows,
        doc_numbers=[],
        title=signature.title,
        explanation=explanation,
        evidence={"rule": "§8 сигнатура", "baseline": signature.baseline},
        confidence=CONFIDENCE_SIGNATURE,
        materiality=finding_materiality(amount, impact, thresholds),
        balance_impact=impact,
    )


def _localization_finding(
    item: LocalizationResult,
    thresholds: MaterialityThresholds,
) -> Finding:
    """Перевести локализованное расхождение §5.9 в находку §4.3.

    Вызывается только для ``item.code is not None``: расхождение с отказом
    (§7.3) находкой таксономии §8 не является — для него нет кода, и его место
    в разделе ограничений отчёта (§16), а не в списке находок.
    """
    if item.code is None:  # pragma: no cover - защищено вызывающим кодом
        message = "локализация без кода не переводится в находку §8"
        raise ValueError(message)
    return Finding(
        code=item.code,
        severity=CODE_SEVERITY[item.code],
        date=item.date,
        amount=item.amount,
        ledger_rows=list(item.ledger_rows),
        ops_rows=list(item.ops_rows),
        doc_numbers=list(item.doc_numbers),
        title=f"{item.code.value} за {item.date:%d.%m.%Y}",
        explanation=item.explanation,
        evidence={
            "rule": "§5.9 локализация",
            "status": item.status.value,
            "category": item.category.value,
            "mode": item.mode.value,
            "gates": item.gates.model_dump(mode="json") if item.gates else None,
        },
        confidence=item.confidence,
        materiality=finding_materiality(item.amount, item.balance_impact, thresholds),
        balance_impact=item.balance_impact,
    )


def _context_findings(
    classified: ClassifyResult,
    validation: ValidationReport,
    waterfall: Waterfall,
    period: tuple[date, date],
    thresholds: MaterialityThresholds,
) -> list[Finding]:
    """Находки уровня выгрузки — ``UNKNOWN_ACCOUNT``, ``LOG_IMBALANCE``, срез.

    Эти три кода §8 не рождаются ни из сопоставления, ни из сигнатур: они
    относятся к выгрузке целиком. Без них список находок молчал бы о фактах,
    которые ТЗ требует показывать (§5.4 «счёт вне справочника не поглощается
    молча», §5.10 дисбаланс логов, §5.3 срез периода).
    """
    findings: list[Finding] = []

    for account in classified.unknown_accounts:
        rows = sorted(entry.row for entry in classified.ledger if entry.counter_account == account)
        amount = sum(
            (
                entry.debit + entry.credit
                for entry in classified.ledger
                if entry.counter_account == account
            ),
            _ZERO,
        )
        findings.append(
            Finding(
                code=FindingCode.UNKNOWN_ACCOUNT,
                severity=CODE_SEVERITY[FindingCode.UNKNOWN_ACCOUNT],
                date=period,
                amount=amount,
                ledger_rows=rows,
                title=f"Счёт вне справочника: {account}",
                explanation=(
                    f"Счёт {account} не описан в `accounts` конфигурации (§6): "
                    f"{len(rows)} проводок на {amount}. Категория операции не "
                    "определена, поэтому в сверку §5.6 они не попали."
                ),
                evidence={"rule": "§5.4 неизвестный счёт", "account": account},
                confidence=CONFIDENCE_LOCALIZED,
                materiality=finding_materiality(amount, amount, thresholds),
                balance_impact=amount,
            ),
        )

    service = [entry for entry in classified.ops if entry.classification is OpsClass.SERVICE]
    if service:
        total = sum((entry.amount for entry in service), _ZERO)
        findings.append(
            Finding(
                code=FindingCode.SERVICE_MISCLASSIFIED,
                severity=CODE_SEVERITY[FindingCode.SERVICE_MISCLASSIFIED],
                date=period,
                amount=total,
                ops_rows=sorted(entry.row for entry in service),
                title=f"Служебных выдач в блоке РКО: {len(service)} на {total}",
                explanation=(
                    f"{len(service)} записей опер-лога на {total} физически лежат в "
                    "блоке РКО и в варианте «как есть» считаются возвратами, хотя "
                    "проводок возврата в 1С им не соответствует (§3.6). Из сверки "
                    "они исключены; на сальдо не влияют — это мера мнимого "
                    "расхождения, а не расхождение. В дисбаланс логов §5.10 они "
                    "входят: наличные из ящика они выносят наравне с возвратом."
                ),
                evidence={
                    "rule": "§3.6 служебные операции",
                    "counterparties": sorted({entry.counterparty for entry in service}),
                },
                confidence=CONFIDENCE_LOCALIZED,
                materiality=finding_materiality(total, _ZERO, thresholds),
                balance_impact=_ZERO,
            ),
        )

    if waterfall.log_imbalance != _ZERO:
        findings.append(
            Finding(
                code=FindingCode.LOG_IMBALANCE,
                severity=CODE_SEVERITY[FindingCode.LOG_IMBALANCE],
                date=period,
                amount=abs(waterfall.log_imbalance),
                title=f"Опер-лог не сходится на {waterfall.log_imbalance}",
                explanation=(
                    f"ПКО минус все РКО за период дают {waterfall.log_imbalance}, "
                    "а не ноль. Причина дисбаланса лежит вне обоих файлов и по "
                    "этой выгрузке не устанавливается (§5.10, §16)."
                ),
                evidence={"rule": "§5.10 дисбаланс логов"},
                confidence=CONFIDENCE_LOCALIZED,
                materiality=finding_materiality(
                    abs(waterfall.log_imbalance),
                    waterfall.log_imbalance,
                    thresholds,
                ),
                balance_impact=waterfall.log_imbalance,
            ),
        )

    if validation.cutoff_suspected:
        findings.append(
            Finding(
                code=FindingCode.PERIOD_CUTOFF,
                severity=CODE_SEVERITY[FindingCode.PERIOD_CUTOFF],
                date=period,
                amount=abs(waterfall.closing - waterfall.target),
                title="Подозрение на срез периода",
                explanation=(
                    "Последняя инкассация или приход, вероятно, не попали в "
                    "выгрузку: сальдо на конец объясняется границей периода, а не "
                    "расхождением (§5.3). Проверяется расширением периода выгрузки."
                ),
                evidence={"rule": "§5.3 срез периода"},
                confidence=CONFIDENCE_PROBABLE,
                materiality=finding_materiality(
                    abs(waterfall.closing - waterfall.target),
                    _ZERO,
                    thresholds,
                ),
                balance_impact=_ZERO,
            ),
        )

    return findings


def _posted_amount(posting: LedgerEntry | None) -> Decimal:
    """Сумма проводки независимо от стороны — §4.1. ``None`` даёт ноль."""
    return _ZERO if posting is None else posting.debit + posting.credit


def _posting_delay_findings(
    localizations: Sequence[LocalizationResult],
    classified: ClassifyResult,
    thresholds: MaterialityThresholds,
) -> list[Finding]:
    """Проведение задним числом — §8, ``POSTING_DELAY``.

    §8 задаёт способ обнаружения как «сопоставление дат документа»: выдача без
    проводки в свой день и проводка без выдачи в более поздний день, совпадающие
    по сумме до копейки, — это одна и та же операция, проведённая с задержкой, а
    не два независимых пробела контроля.

    Свёртка §5.7.2 такую пару не видит: перенос даты ограничен ``LONG_WIN``
    (31 день), а здесь задержка достигает 175 дней. Расширять окно нельзя —
    §5.7.2 держит его узким именно потому, что точное совпадение сумм на большом
    горизонте начинает сводить случайные операции. Поэтому находка не заменяет
    исходные две, а связывает их: читатель видит, что одни и те же рубли названы
    дважды, и не складывает их.

    Солигорск: 01.10.2023 проведены РКО 00289603 (38,27), 00289605 (329,26) и
    00290339 (57,66) — выдачи 09.04, 19.04 и 27.06.2023, задержка 96–175 дней.
    Признак ищется **по суммам, а не по номерам документов.** Номера говорят
    больше: все три документа отмечены временем 23:59:59, а их номера лежат в
    диапазоне начала ноября 2023 — проводки не только опоздали, но и датированы
    задним числом. Построить на нумерации правило не удалось: документы одной
    ретро-сессии идут подряд и маскируют друг друга (сосед по номеру у
    back-dated документа — такой же back-dated), а ряд ПКО этой кассы вообще не
    монотонен — 2022 и 2023 годы делят один диапазон номеров и дают 95
    инверсий. Правило, работающее на одной сессии и промахивающееся на соседнем
    ряду, — догадка, а не признак (§8.2, §15).

    Порядок обхода полный и явный (§12): по дате выдачи, затем по сумме, затем
    по первой строке лога; проводка расходуется не более одного раза.
    """
    entry_by_row = {entry.row: entry for entry in classified.ledger}
    unbooked = sorted(
        (item for item in localizations if item.code is FindingCode.PAYOUT_NOT_BOOKED),
        key=lambda item: (item.date, item.amount, item.ops_rows),
    )
    late_postings = sorted(
        (
            (item.date, row)
            for item in localizations
            if item.code is FindingCode.RKO_WITHOUT_PAYOUT
            for row in item.ledger_rows
        ),
        key=lambda pair: (pair[0], pair[1]),
    )

    taken: set[int] = set()
    findings: list[Finding] = []
    for payout in unbooked:
        match = next(
            (
                pair
                for pair in late_postings
                if pair[1] not in taken
                and pair[0] > payout.date
                and _posted_amount(entry_by_row.get(pair[1])) == payout.amount
            ),
            None,
        )
        if match is None:
            continue
        booked_on, row = match
        taken.add(row)
        posting = entry_by_row[row]
        amount = _posted_amount(posting)
        delay = (booked_on - payout.date).days
        stamp = str(posting.doc_text)[-8:]
        backdated = (
            f" Документ отмечен временем {stamp} — типичная метка ретро-сессии (§8)."
            if stamp == "23:59:59"
            else ""
        )
        findings.append(
            Finding(
                code=FindingCode.POSTING_DELAY,
                severity=CODE_SEVERITY[FindingCode.POSTING_DELAY],
                date=(payout.date, booked_on),
                amount=amount,
                ledger_rows=[row],
                ops_rows=list(payout.ops_rows),
                doc_numbers=[posting.doc_number] if posting.doc_number else [],
                title=f"Проводка на {amount} отстала от выдачи на {delay} дн.",
                explanation=(
                    f"Выдача {amount} от {payout.date:%d.%m.%Y} проведена в 1С только "
                    f"{booked_on:%d.%m.%Y} документом {posting.doc_number or '—'} "
                    f"(строка {row}) — задержка {delay} дней.{backdated} "
                    "Свёртка §5.7.2 такую пару не сводит: перенос даты ограничен "
                    "31 днём. Те же рубли поэтому названы в отчёте дважды — "
                    "«выдача без проводки» за день выдачи и «проводка без выдачи» за "
                    "день проведения; складывать их нельзя. На сальдо не влияет: "
                    "операция проведена, вопрос только в дате."
                ),
                evidence={
                    "rule": "§8 POSTING_DELAY, сопоставление дат документа",
                    "doc_time": stamp,
                    "paid_on": payout.date.isoformat(),
                    "booked_on": booked_on.isoformat(),
                    "delay_days": delay,
                },
                confidence=CONFIDENCE_LOCALIZED,
                materiality=finding_materiality(amount, _ZERO, thresholds),
                balance_impact=_ZERO,
            ),
        )
    return findings


def collect_findings(
    reversal_findings: Sequence[Finding],
    localizations: Sequence[LocalizationResult],
    signatures: Sequence[Signature],
    classified: ClassifyResult,
    validation: ValidationReport,
    waterfall: Waterfall,
    period: tuple[date, date] | None,
    benchmark: Decimal,
    config: Config,
) -> tuple[Finding, ...]:
    """Собрать единый список находок таксономии §8 из всех источников.

    Источники: сторно §5.5, локализация §5.9, сигнатуры §8.1–8.2 и факты
    уровня выгрузки (§5.3, §5.4, §5.10). Результат — вход стадии RANK §5.11.

    Локализации со статусом отказа (``code is None``) сюда **не** попадают:
    у отказа нет кода §8, и выдавать его находкой значило бы предъявить
    расхождение как установленное. Их место — раздел ограничений отчёта (§16).

    ``period is None`` означает пустую карточку счёта: датировать находки
    уровня выгрузки нечем, и такой файл уже остановлен инвариантом V1 (§5.3).
    """
    if period is None:
        return tuple(reversal_findings)
    thresholds = materiality_thresholds(benchmark, config)
    findings = [
        *reversal_findings,
        *(
            _localization_finding(item, thresholds)
            for item in localizations
            if item.code is not None
        ),
        *(_signature_finding(item, period, thresholds) for item in signatures),
        *_context_findings(classified, validation, waterfall, period, thresholds),
        *_posting_delay_findings(localizations, classified, thresholds),
    ]
    return tuple(findings)


def rank_findings(
    findings: Sequence[Finding],
    benchmark: Decimal,
    config: Config,
) -> tuple[Finding, ...]:
    """Стадия RANK целиком — §5.11.

    Сначала каждой находке присваивается материальность §7.5 (до этой стадии
    она не вычислима: нужен оборот периода), затем мелочь сворачивается, затем
    результат сортируется полным ключом.
    """
    thresholds = materiality_thresholds(benchmark, config)
    scored = tuple(
        item.model_copy(
            update={
                "materiality": finding_materiality(
                    item.amount,
                    item.balance_impact,
                    thresholds,
                ),
            },
        )
        for item in findings
    )
    return tuple(sorted(aggregate_trivial(scored, thresholds), key=sort_key))
