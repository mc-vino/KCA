"""Сигнатуры риска — §8.1–8.2 ТЗ.

Ловят то, что сверка принципиально не ловит: повторные выдачи внутри дневного
агрегата, документы вне рабочих часов, разрывы нумерации, дубликаты.

Сигнатура — не улика (§16)
--------------------------
Базовая частота повторов в этих данных высока. Формулировка обязана быть
«повтор может быть законным (возврат нескольких одинаковых позиций); требует
точечной проверки», а не «двойная выдача» (§8.1). Квалификация — за человеком
(§1.2).
"""

from __future__ import annotations

import random
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal
from itertools import pairwise

from cashforensics.models import (
    ClassifyResult,
    Config,
    FindingCode,
    LedgerEntry,
    OpsClass,
    OpsEntry,
    OpsKind,
    Severity,
    Signature,
)

__all__ = [
    "REPEAT_DISCLAIMER",
    "collect_signatures",
    "count_repeat_groups",
    "duplicate_baseline",
    "duplicate_documents",
    "iqr_bounds",
    "late_time_documents",
    "modified_z_scores",
    "repeat_baseline_pko",
    "repeat_payouts",
    "repeated_documents",
    "round_number_bias",
    "sequence_gaps",
]

REPEAT_DISCLAIMER = (
    "Повтор может быть законным (возврат нескольких одинаковых позиций); требует точечной проверки."
)
"""Обязательная формулировка §8.1. Не «двойная выдача» — это было бы утверждением."""

_ZERO = Decimal("0.00")
_MIN_DUPLICATES = 2
"""Задвоение — это две проводки; §8 говорит «две проводки одной суммы»."""

_ROUND_STEP = Decimal("10.00")
"""Шаг «круглости» суммы — §8, SHIFT_ROUNDING."""

_MAD_SCALE = Decimal("0.6745")
"""Константа модифицированного z-score: MAD → оценка σ для нормального закона."""

_DIGITS_RE = re.compile(r"(\D*)(\d+)$")
_SEQUENCE_SHOWN = 10
"""Сколько пропущенных номеров показывать в объяснении, остальные — многоточием."""

_SEQUENCE_MIN_NUMBERS = 3
"""Ниже трёх номеров о непрерывности говорить нечего."""

_SEQUENCE_MAX_GAP = 1000
"""Разрыв, выше которого номера считаются **разными рядами**, а не пропуском.

Пары «префикс + разрядность» из §8.2 недостаточно: на PAX_119049688 в одну
группу из 11 цифр попали и сквозной номер 1С (``000000223359``), и штрихкод
вида ``12258438561``. Разность между ними — 12 258 215 202, и наивный подсчёт
объявлял ровно столько «пропущенных документов». Такое число не является
находкой: оно означает, что ряд не один.

Поэтому ряд режется по разрывам больше этого порога, пропуски считаются
внутри сегментов, а число самих границ выносится в отчёт как оговорка — по
одной выгрузке отличить «другой ряд» от «удалённой тысячи документов» нельзя
(§8.2, §15).
"""

_SEQUENCE_DENSE_MIN = 0.5
"""Доля занятых номеров, ниже которой ряд не считается нумерацией этой кассы.

§8.2: «нумерация в 1С может быть сквозной по организации, а не по кассе — тогда
пропуски ожидаемы; в этом случае тест понижается до информационного».
Плотность и есть измеримый признак этого случая: на PAX_119049688 250
документов занимают 21 000 номеров (плотность 0,012), и перечислять 20 893
«пропуска» — значит выдавать за находку то, что документы просто выписаны
другими кассами.

Ниже порога группа заменяется одной информационной строкой: непрерывность по
этой выгрузке непроверяема, и сказать об этом честнее, чем показать число.
"""


def _repeat_groups(
    entries: Sequence[OpsEntry],
    config: Config,
) -> list[tuple[str, Decimal, tuple[OpsEntry, ...]]]:
    """Группы «одна сумма одному получателю в окне» — §8.1.

    Группировка по паре ``(получатель, сумма)``; внутри группы ищется окно
    ``repeat_window_minutes``, в которое попадает не меньше
    ``repeat_min_count`` записей.
    """
    window = config.signatures.repeat_window_minutes * 60
    minimum = config.signatures.repeat_min_count

    buckets: dict[tuple[str, Decimal], list[OpsEntry]] = defaultdict(list)
    for entry in entries:
        if not entry.counterparty:
            continue
        buckets[(entry.counterparty, entry.amount)].append(entry)

    groups: list[tuple[str, Decimal, tuple[OpsEntry, ...]]] = []
    for (counterparty, amount), bucket in buckets.items():
        ordered = sorted(bucket, key=lambda item: (item.dt, item.row))
        start = 0
        for end in range(len(ordered)):
            while (ordered[end].dt - ordered[start].dt).total_seconds() > window:
                start += 1
            if end - start + 1 >= minimum and (
                end + 1 == len(ordered)
                or (ordered[end + 1].dt - ordered[start].dt).total_seconds() > window
            ):
                groups.append((counterparty, amount, tuple(ordered[start : end + 1])))
    groups.sort(key=lambda item: (item[2][0].dt, item[2][0].row))
    return groups


def count_repeat_groups(entries: Sequence[OpsEntry], config: Config) -> int:
    """Число групп повторов — §8.1, используется для базовой частоты."""
    return len(_repeat_groups(entries, config))


def repeat_baseline_pko(ops: Sequence[OpsEntry], config: Config) -> str:
    """Базовая частота повторов по ПКО — §8.1, обязательный контекст отчёта.

    В ПКО повторы — норма: клиент забирает несколько одинаковых заказов. На
    PAX_119049688 в ПКО было 15 таких случаев против 1 в РКО; на Солигорске —
    183 против 35. Без этого числа сигнатура читается как обвинение.
    """
    incoming = count_repeat_groups(
        [entry for entry in ops if entry.kind is OpsKind.PKO],
        config,
    )
    outgoing = count_repeat_groups(
        [entry for entry in ops if entry.kind is OpsKind.RKO],
        config,
    )
    return (
        f"базовая частота: {incoming} таких случаев в ПКО против {outgoing} в РКО. "
        "В ПКО повтор — норма (клиент забирает несколько одинаковых заказов)"
    )


def repeat_payouts(ops: Sequence[OpsEntry], config: Config) -> tuple[Signature, ...]:
    """Повторная выдача одной суммы одному получателю — §8.1.

    **Сигнатура выдаётся только по РКО.** Записи ПКО в неё не попадают: там
    повтор — штатное поведение, и его частота идёт в отчёт только как контекст.

    Самая заметная находка класса: 14.05 — четыре РКО по 164,99 одному
    получателю за 22 секунды (13:26:55 → 13:27:17); 1С провела агрегат
    1 358,96, поэтому сверка расхождения не даёт вовсе.
    """
    payouts = [
        entry
        for entry in ops
        if entry.kind is OpsKind.RKO and entry.classification is not OpsClass.SERVICE
    ]
    baseline = repeat_baseline_pko(ops, config)

    signatures: list[Signature] = []
    for counterparty, amount, group in _repeat_groups(payouts, config):
        span = (group[-1].dt - group[0].dt).total_seconds()
        signatures.append(
            Signature(
                code=FindingCode.REPEAT_PAYOUT,
                title=f"Повтор выдачи {amount} × {len(group)}",
                date=group[0].dt.date(),
                amount=amount * len(group),
                rows=tuple(entry.row for entry in group),
                baseline=baseline,
                explanation=(
                    f"{len(group)} выдач по {amount} получателю «{counterparty}» за "
                    f"{span:.0f} с ({group[0].dt:%H:%M:%S} → {group[-1].dt:%H:%M:%S}). "
                    f"{REPEAT_DISCLAIMER} Сверка такого повтора не ловит: 1С проводит "
                    "дневной агрегат."
                ),
            ),
        )
    return tuple(signatures)


def late_time_documents(
    ops: Sequence[OpsEntry],
    config: Config,
) -> tuple[Signature, ...]:
    """Документы в 23:59:59 и вне рабочих часов — §8, ``LATE_TIME_DOC``.

    Записи с временем ``00:00:00`` исключены: это метка дневного агрегата
    (§3.3), а не операция глубокой ночью.
    """
    late = time.fromisoformat(config.signatures.late_time)
    opens = time.fromisoformat(config.signatures.business_hours[0])
    closes = time.fromisoformat(config.signatures.business_hours[1])

    signatures: list[Signature] = []
    for entry in sorted(ops, key=lambda item: (item.dt, item.row)):
        moment = entry.dt.time()
        if moment == time.min:
            continue
        if moment != late and opens <= moment <= closes:
            continue
        reason = (
            "ровно 23:59:59 — типичная отметка автоматического закрытия смены"
            if moment == late
            else f"вне рабочих часов {opens:%H:%M}–{closes:%H:%M}"
        )
        signatures.append(
            Signature(
                code=FindingCode.LATE_TIME_DOC,
                title=f"Документ в {moment:%H:%M:%S}",
                date=entry.dt.date(),
                amount=entry.amount,
                rows=(entry.row,),
                baseline=None,
                explanation=(
                    f"Запись {entry.kind.value} на {entry.amount} от "
                    f"{entry.dt:%d.%m.%Y %H:%M:%S}: {reason}. Требует проверки."
                ),
            ),
        )
    return tuple(signatures)


def _split_runs(numbers: Sequence[int], max_gap: int) -> list[list[int]]:
    """Разрезать отсортированный ряд по разрывам больше ``max_gap`` — §8.2.

    Каждый сегмент трактуется как отдельный ряд нумерации: см.
    :data:`_SEQUENCE_MAX_GAP`.
    """
    runs: list[list[int]] = [[numbers[0]]] if numbers else []
    for previous, current in pairwise(numbers):
        if current - previous > max_gap:
            runs.append([current])
        else:
            runs[-1].append(current)
    return runs


def _missing_in_run(run: Sequence[int], limit: int) -> tuple[int, list[int]]:
    """Число пропусков сегмента и первые ``limit`` из них — §8.2.

    Счёт арифметический, перечисление ограничено: даже внутри одного ряда
    разрыв достигает сотен номеров, и материализация ``range()`` целиком
    съедала память до OOM.
    """
    missing = sum(current - previous - 1 for previous, current in pairwise(run))
    examples: list[int] = []
    for previous, current in pairwise(run):
        stop = min(current, previous + 1 + limit - len(examples))
        examples.extend(range(previous + 1, stop))
        if len(examples) >= limit:
            break
    return missing, examples


def _sparse_signature(
    prefix: str,
    width: int,
    numbers: Sequence[int],
    rows: tuple[int, ...],
) -> Signature:
    """Информационная строка вместо подсчёта пропусков — §8.2.

    Плотность ниже :data:`_SEQUENCE_DENSE_MIN` означает, что ряд принадлежит не
    этой кассе. Число «пропусков» в таком ряду измеряет активность соседних
    касс, а не пробел в документах, и приводить его как находку нельзя.
    """
    span = numbers[-1] - numbers[0] + 1
    return Signature(
        code=FindingCode.SEQUENCE_GAP,
        title=f"Нумерация «{prefix or '—'}» сквозная, непрерывность непроверяема",
        date=None,
        amount=None,
        rows=rows,
        baseline=(
            "нумерация в 1С может быть сквозной по организации, а не по кассе — "
            "тогда пропуски ожидаемы"
        ),
        explanation=(
            f"{len(numbers)} документов разрядности {width} занимают {span} номеров "
            f"({numbers[0]}–{numbers[-1]}), плотность {len(numbers) / span:.3f}. "
            "Ряд заведомо не принадлежит одной кассе, поэтому пропуски не "
            "подсчитываются: их число измеряло бы активность других касс. "
            "Проверка непрерывности требует выгрузки по всей организации (§8.2)."
        ),
        severity=Severity.INFO,
    )


def _run_signature(
    prefix: str,
    width: int,
    run: Sequence[int],
    rows: tuple[int, ...],
    run_count: int,
) -> Signature | None:
    """Пропуски внутри одного плотного ряда — §8.2. ``None``, если пропусков нет."""
    missing_count, examples = _missing_in_run(run, _SEQUENCE_SHOWN)
    if missing_count == 0:
        return None
    shown = ", ".join(str(number) for number in examples)
    tail = " …" if missing_count > len(examples) else ""
    boundary = (
        f" Ряд разрезан на {run_count} по разрывам больше {_SEQUENCE_MAX_GAP}: "
        "такие скачки означают другой ряд нумерации, а не пропуск, и в счёт "
        "не входят."
        if run_count > 1
        else ""
    )
    return Signature(
        code=FindingCode.SEQUENCE_GAP,
        title=(f"Пропуски в нумерации «{prefix or '—'}» {run[0]}–{run[-1]}, {missing_count} шт."),
        date=None,
        amount=None,
        rows=rows,
        baseline=(
            "нумерация в 1С может быть сквозной по организации, а не по кассе — "
            "тогда пропуски ожидаемы"
        ),
        explanation=(
            f"В ряду из {len(run)} номеров разрядности {width} "
            f"({run[0]}–{run[-1]}) не хватает {missing_count}: {shown}{tail}. "
            "Пропуск может означать удалённый или непроведённый документ; "
            f"при сквозной нумерации по организации — ожидаемое поведение.{boundary}"
        ),
    )


def _number_groups(
    ledger: Sequence[LedgerEntry],
) -> dict[tuple[str, int], list[tuple[int, LedgerEntry]]]:
    """Разложить проводки по паре «префикс + разрядность» номера — §8.2."""
    groups: dict[tuple[str, int], list[tuple[int, LedgerEntry]]] = defaultdict(list)
    for entry in ledger:
        if not entry.doc_number:
            continue
        match = _DIGITS_RE.match(entry.doc_number)
        if match is None:
            continue
        prefix, digits = match.groups()
        groups[(prefix, len(digits))].append((int(digits), entry))
    return groups


def _group_signatures(
    prefix: str,
    width: int,
    items: Sequence[tuple[int, LedgerEntry]],
) -> list[Signature]:
    """Сигнатуры одной группы номеров — §8.2.

    Разреженная группа даёт одну информационную строку вместо подсчёта
    пропусков (:data:`_SEQUENCE_DENSE_MIN`), плотная — по строке на ряд.
    """
    numbers = sorted({number for number, _ in items})
    if len(numbers) < _SEQUENCE_MIN_NUMBERS:
        return []

    group_rows = tuple(sorted(entry.row for _, entry in items))
    span = numbers[-1] - numbers[0] + 1
    if len(numbers) / span < _SEQUENCE_DENSE_MIN:
        return [_sparse_signature(prefix, width, numbers, group_rows)]

    rows_by_number: dict[int, list[int]] = defaultdict(list)
    for number, entry in items:
        rows_by_number[number].append(entry.row)

    runs = _split_runs(numbers, _SEQUENCE_MAX_GAP)
    signatures = []
    for run in runs:
        if len(run) < _SEQUENCE_MIN_NUMBERS:
            continue
        rows = tuple(sorted(row for number in run for row in rows_by_number[number]))
        signature = _run_signature(prefix, width, run, rows, len(runs))
        if signature is not None:
            signatures.append(signature)
    return signatures


def sequence_gaps(ledger: Sequence[LedgerEntry]) -> tuple[Signature, ...]:
    """Пропуски в нумерации документов — §8.2, ``SEQUENCE_GAP``.

    Номера группируются по префиксу и разрядности, режутся на ряды по
    :data:`_SEQUENCE_MAX_GAP`, внутри ряда ищутся пропуски. Пропуск может
    означать удалённый или непроведённый документ.

    Нумерация в 1С может быть сквозной по организации, а не по кассе — тогда
    пропуски ожидаемы. Признак этого случая — плотность ниже
    :data:`_SEQUENCE_DENSE_MIN`; тогда тест понижается до информационного и
    пропуски не подсчитываются вовсе (§8.2, §15).
    """
    signatures: list[Signature] = []
    for (prefix, width), items in sorted(_number_groups(ledger).items()):
        signatures.extend(_group_signatures(prefix, width, items))
    return tuple(signatures)


def repeated_documents(ledger: Sequence[LedgerEntry]) -> tuple[Signature, ...]:
    """Дубликаты документов — §8, ``DUPLICATE_DOC``.

    Оборотная сторона :func:`duplicate_documents`: там признаком задвоения
    служат **разные** номера, а совпадение номеров оттуда явно исключено. Тот
    случай и есть ``DUPLICATE_DOC`` — один и тот же документ в выгрузке дважды.

    Различать их обязательно, потому что §8 даёт им разные severity и разное
    влияние на сальдо: задвоенный приход — ``ОШИБКА`` и влияет, дубликат —
    ``ПРОВЕРИТЬ`` и «зависит». Чаще всего дубликат означает дефект выгрузки, а
    не учёта, поэтому формулировка не утверждает задвоения.
    """
    buckets: dict[tuple[object, str], list[LedgerEntry]] = defaultdict(list)
    for entry in ledger:
        if not entry.doc_number:
            continue
        buckets[(entry.date, entry.doc_number)].append(entry)

    signatures: list[Signature] = []
    for (day, number), bucket in sorted(buckets.items(), key=lambda item: item[0]):
        if len(bucket) < _MIN_DUPLICATES:
            continue
        amounts = {entry.debit + entry.credit for entry in bucket}
        exact = len(amounts) == 1
        amount = next(iter(sorted(amounts)))
        kind = "точный" if exact else "нечёткий"
        signatures.append(
            Signature(
                code=FindingCode.DUPLICATE_DOC,
                title=f"Дубликат документа {number} ({kind})",
                date=day,  # type: ignore[arg-type]
                amount=amount if exact else None,
                rows=tuple(sorted(entry.row for entry in bucket)),
                baseline=(
                    "повтор одного номера чаще означает дефект выгрузки, а не "
                    "учёта: одна проводка может занимать несколько строк карточки"
                ),
                explanation=(
                    f"Документ {number} за {day:%d.%m.%Y} встречается "
                    f"{len(bucket)} раза"
                    + (
                        f" одной суммой {amount}."
                        if exact
                        else f" с разными суммами ({', '.join(str(x) for x in sorted(amounts))})."
                    )
                    + " Требует проверки: возможен дубликат выгрузки."
                ),
            ),
        )
    return tuple(signatures)


def _same_day_collisions(days: Sequence[date], amounts: Sequence[Decimal]) -> int:
    """Сколько корзин «день + сумма» содержат больше одной проводки."""
    counts: Counter[tuple[date, Decimal]] = Counter(zip(days, amounts, strict=True))
    return sum(1 for value in counts.values() if value >= _MIN_DUPLICATES)


def duplicate_baseline(
    entries: Sequence[LedgerEntry],
    config: Config,
) -> tuple[float, float]:
    """Базовая частота задвоений по счёту — §8.1, перестановочный тест.

    §8.1 требует сопровождать сигнатуру повтора базовой частотой: «повтор может
    быть законным… требует точечной проверки». Для задвоенного ПКО базовая
    частота — это ответ на вопрос «а сколько таких совпадений даёт случай?».

    Нуль-модель: те же суммы, те же дни, случайная приписка сумм к проводкам
    внутри счёта. Перестановки берут ``config.seed`` и ``PERMUTATION_B`` —
    отдельного порога для этого теста §6 не вводит, и заводить его значило бы
    подгонять под кассу.

    Returns:
        ``(ожидаемое число совпадений, p)``. ``p`` — доля перестановок, где
        совпадений не меньше наблюдённого.

    Что это меряет на калибровочных кассах. Солигорск, счёт 62.4.1: 971
    проводка на 789 дней, наблюдалось 2 совпадения при ожидаемых 0,61 —
    p = 0,12, то есть случай объясняет их без остатка, и §11.3 задвоения для
    этой кассы не называет. `PAX_119023531`, тот же счёт: 81 проводка на 78
    дней, наблюдалось 1 при ожидаемых 0,05 — p = 0,05, в двадцать раз реже
    случайного, и §11.3 называет эту пару поимённо (R87/R101 на 1 400,00).
    Порогом эта величина не служит: §8 оставляет уровень находки за собой, а
    базовая частота идёт в отчёт контекстом, как и велит §8.1.
    """
    days = [entry.date for entry in entries]
    amounts = [entry.debit for entry in entries]
    observed = _same_day_collisions(days, amounts)
    rounds = config.subset_sum.PERMUTATION_B
    rng = random.Random(config.seed)  # noqa: S311  # не криптография: нуль-модель §8.1
    pool = list(amounts)
    total = 0
    at_least = 0
    for _ in range(rounds):
        rng.shuffle(pool)
        collisions = _same_day_collisions(days, pool)
        total += collisions
        at_least += collisions >= observed
    return (total / rounds, (at_least + 1) / (rounds + 1))


def duplicate_documents(
    ledger: Sequence[LedgerEntry],
    config: Config,
) -> tuple[Signature, ...]:
    """Задвоенные приходные ордера — §8, ``PKO_DOUBLE_BOOKED``.

    Признак §8: две проводки одной суммы, один день, один счёт, **разные
    номера**. Совпадение номеров означало бы дубликат выгрузки, а не задвоение
    проведения — этот случай разбирает :func:`repeated_documents`.

    Базовая частота §8.1 обязательна и считается по счёту —
    :func:`duplicate_baseline`. Без неё находка читалась как утверждение: на
    Солигорске две такие пары (+1 822,12 и +24,87) объясняются случаем при 971
    авансовой проводке на 789 дней, и §11.3 их не называет.
    """
    buckets: dict[tuple[object, str, Decimal], list[LedgerEntry]] = defaultdict(list)
    by_account: dict[str, list[LedgerEntry]] = defaultdict(list)
    for entry in ledger:
        if entry.debit <= _ZERO:
            continue
        buckets[(entry.date, entry.counter_account, entry.debit)].append(entry)
        by_account[entry.counter_account].append(entry)

    baselines: dict[str, tuple[float, float]] = {}
    signatures: list[Signature] = []
    for (day, account, amount), bucket in sorted(
        buckets.items(),
        key=lambda item: (item[0][0], item[0][1], item[0][2]),
    ):
        numbers = {entry.doc_number for entry in bucket if entry.doc_number}
        if len(bucket) < _MIN_DUPLICATES or len(numbers) < _MIN_DUPLICATES:
            continue
        if account not in baselines:
            baselines[account] = duplicate_baseline(by_account[account], config)
        expected, p_value = baselines[account]
        signatures.append(
            Signature(
                code=FindingCode.PKO_DOUBLE_BOOKED,
                title=f"Задвоенный приход {amount}",
                date=day,  # type: ignore[arg-type]
                amount=amount,
                rows=tuple(sorted(entry.row for entry in bucket)),
                baseline=(
                    f"счёт {account} за период — проводок: {len(by_account[account])}, "
                    f"дней: {len({entry.date for entry in by_account[account]})}. Случайная "
                    f"приписка тех же сумм к тем же дням даёт {expected:.2f} таких совпадений "
                    f"(p = {p_value:.4f}). Чем ближе p к единице, тем меньше повод считать "
                    "совпадение задвоением"
                ),
                explanation=(
                    f"{len(bucket)} проводки одной суммы {amount} по счёту {account} "
                    f"за один день под разными номерами ({', '.join(sorted(numbers))}). "
                    "Требует проверки: возможно задвоение проведения."
                ),
            ),
        )
    return tuple(signatures)


def modified_z_scores(values: Sequence[Decimal]) -> tuple[float, ...]:
    """Модифицированный z-score (медиана + MAD) — §6, §15.

    ``0,6745·(x − медиана)/MAD``; порог ``statistics.mod_z_threshold`` = 3,5.
    Робастная статистика, объяснима — в отличие от Isolation Forest / LOF,
    прямо запрещённых §15.

    При нулевом MAD (все значения равны) возвращаются нули: разброса нет, и
    выбросов быть не может.
    """
    if not values:
        return ()
    median = Decimal(str(statistics.median(values)))
    deviations = [abs(value - median) for value in values]
    mad = Decimal(str(statistics.median(deviations)))
    if mad == _ZERO:
        return tuple(0.0 for _ in values)
    return tuple(float(_MAD_SCALE * (value - median) / mad) for value in values)


def iqr_bounds(values: Sequence[Decimal], multiplier: float) -> tuple[Decimal, Decimal]:
    """Границы IQR (1.5 — мягкая, 3.0 — экстремальная) — §6, §15."""
    if not values:
        return (_ZERO, _ZERO)
    ordered = sorted(values)
    quartiles = statistics.quantiles([float(value) for value in ordered], n=4)
    q1 = Decimal(str(quartiles[0]))
    q3 = Decimal(str(quartiles[2]))
    spread = (q3 - q1) * Decimal(str(multiplier))
    return (q1 - spread, q3 + spread)


def round_number_bias(
    ledger: Sequence[LedgerEntry],
    config: Config,
) -> tuple[Signature, ...]:
    """Округление смены — §8, ``SHIFT_ROUNDING``.

    Круглая сумма ниже ``ROUND_MAX``, один знак. §15 велит применять
    round-number bias **только как слабый признак** и только в связке: сам по
    себе он даёт много ложных срабатываний, поэтому severity у находки —
    «НОРМА», и самостоятельной уликой она не является.
    """
    limit = config.thresholds.ROUND_MAX
    signatures: list[Signature] = []
    for entry in sorted(ledger, key=lambda item: (item.date, item.row)):
        amount = entry.debit + entry.credit
        if amount <= _ZERO or amount >= limit:
            continue
        if amount % _ROUND_STEP != _ZERO:
            continue
        signatures.append(
            Signature(
                code=FindingCode.SHIFT_ROUNDING,
                title=f"Округление смены {amount}",
                date=entry.date,
                amount=amount,
                rows=(entry.row,),
                baseline=(
                    "признак слабый: круглые суммы встречаются и в обычных "
                    "операциях; учитывать только в связке с другими (§15)"
                ),
                explanation=(
                    f"Круглая сумма {amount} ниже порога {limit} за "
                    f"{entry.date:%d.%m.%Y} — типичное округление или недостача смены."
                ),
            ),
        )
    return tuple(signatures)


def collect_signatures(
    classified: ClassifyResult,
    config: Config,
) -> tuple[Signature, ...]:
    """Собрать все сигнатуры — §8.1–8.2.

    Закон Бенфорда не реализуется: §15 запрещает его при N < ~1700, а на этих
    данных пороги и лимиты транзакций искажают распределение первой цифры —
    условие «применять» практически недостижимо, и реализация была бы
    заготовкой под запрещённый метод.

    Порядок результата фиксирован ``(код, дата, строки)`` — §12.
    """
    signatures = (
        *repeat_payouts(classified.ops, config),
        *late_time_documents(classified.ops, config),
        *sequence_gaps(classified.ledger),
        *duplicate_documents(classified.ledger, config),
        *repeated_documents(classified.ledger),
        *round_number_bias(classified.ledger, config),
    )
    return tuple(
        sorted(
            signatures,
            key=lambda item: (item.code.value, item.date or _EPOCH, item.rows),
        ),
    )


_EPOCH = datetime(1, 1, 1).date()
"""Заглушка сортировки для сигнатур без даты (разрывы нумерации, §8.2)."""
