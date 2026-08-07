"""Стадия LOCALIZE — §5.9 ТЗ, гейты доказательности §7.

Определяет режим проведения (§5.9.1), сопоставляет 1:1 в подокументном режиме
(§5.9.2), применяет правило единственной проводки (§5.9.3) и — только там, где
день им не покрыт — subset-sum с четырьмя гейтами (§5.9.4, §7.3).

Почему гейты обязательны (§7.1)
-------------------------------
Число подмножеств растёт как 2^N; при ограниченном диапазоне сумм столкновения
неизбежны, и при большом N **любая** цель окажется достижимой какой-нибудь
комбинацией. Локализация тогда указывает на случайного клиента.

Абсолютный запрет (§7.4)
------------------------
Локализация ниже дневного агрегата продаж запрещена независимо от гейтов. 1С
хранит свод Z-отчёта одной проводкой, опер-лог — поштучные чеки; при 80 чеках в
дне subset-sum спурьозен по определению. Инструмент обязан выдать: «расхождение
локализовано до дня и до агрегата; ниже — требуется Z-отчёт за <дата>».

Арифметика
----------
Subset-sum считается **в копейках** (``int``), не в ``float`` и не в
``Decimal`` — §10.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import numpy as np
from rapidfuzz.distance import JaroWinkler
from scipy.optimize import linear_sum_assignment

from cashforensics.models import (
    Category,
    ClassifyResult,
    CollapseResult,
    Config,
    FindingCode,
    LedgerEntry,
    LocalizationResult,
    LocalizationStatus,
    OpsEntry,
    PostingMode,
    ReversalResult,
    SubsetSumGateReport,
)
from cashforensics.normalize import quantize_money
from cashforensics.reconcile import RECONCILED_CATEGORIES, ops_classes_for

__all__ = [
    "BITMASK_LIMIT",
    "HUNGARIAN_WEIGHTS",
    "apply_gates",
    "day_index",
    "gate_candidate_count",
    "gate_density",
    "gate_permutation_test",
    "gate_uniqueness",
    "greedy_match",
    "hungarian_match",
    "localize",
    "name_similarity",
    "posting_mode",
    "subset_sum_solutions",
    "to_kopecks",
]

BITMASK_LIMIT = 20
"""Граница перебора битовыми масками — §7.3.

Выше §7.3 предписывает DP по копейкам, но гейт 1 отсекает ``N > HARD_MAX`` (15)
безусловно и **до** перебора, поэтому эта ветка недостижима. Вместо мёртвого
кода :func:`subset_sum_solutions` отказывается работать: молчаливая заглушка
хуже явного отказа.
"""

HUNGARIAN_WEIGHTS = (1.0, 1.0, 1.0)
"""Веса ``(w1, w2, w3)`` матрицы стоимостей §5.9.2.

В §6 не заданы; вынесены сюда, чтобы их можно было поменять в одном месте.
Влияют только на выбор пары внутри окна, не на суммы.
"""

_ZERO = Decimal("0.00")

_AMBIGUOUS_MIN_SOLUTIONS = 2
"""С двух решений расхождение перестаёт быть локализуемым — §7.3, гейт 2."""


def to_kopecks(amount: Decimal) -> int:
    """Перевести сумму в копейки — §10.

    Внутренние сравнения в subset-sum обязаны идти в целых копейках: на
    ``float`` подмножество из пятнадцати слагаемых накапливает ошибку больше
    допуска §7.3 (0,005).
    """
    return int(quantize_money(amount) * 100)


def posting_mode(
    ledger: Sequence[LedgerEntry],
    ops: Sequence[OpsEntry],
    category: Category,
    config: Config,
) -> PostingMode:
    """Режим проведения по категории — §5.9.1.

    ``ops_per_posting = число операций опер-лога / число проводок 1С``;
    ``≤ AGGREGATE_RATIO`` → подокументный, иначе — дневные агрегаты.

    Солигорск: 5 771 выдача на 1 811 проводок = 3,2 → агрегаты.
    PAX_119049688: подокументный.
    """
    classes = ops_classes_for(category, exclude_service=True)
    postings = sum(1 for entry in ledger if entry.category is category)
    operations = sum(1 for entry in ops if entry.classification in classes)
    if postings == 0:
        return PostingMode.DAILY_AGGREGATE
    ratio = operations / postings
    return (
        PostingMode.PER_DOCUMENT
        if ratio <= config.thresholds.AGGREGATE_RATIO
        else PostingMode.DAILY_AGGREGATE
    )


def name_similarity(left: str, right: str) -> float:
    """Схожесть ФИО — Jaro-Winkler, ``rapidfuzz`` (§5.9.2).

    Используется только как компонент стоимости сопоставления; порог —
    ``statistics.fuzzy_name_threshold`` (§6). Пустое имя (вариант C, §3.3) даёт
    0: сравнивать не с чем, и притворяться, что совпадение полное, нельзя.
    """
    if not left or not right:
        return 0.0
    return float(JaroWinkler.similarity(left, right))


def day_index(
    ledger: Sequence[LedgerEntry],
    ops: Sequence[OpsEntry],
    category: Category,
    neutralized: frozenset[int],
) -> tuple[dict[date, list[LedgerEntry]], dict[date, list[OpsEntry]]]:
    """Разложить проводки и записи лога по дням — §5.9.

    Внутри дня порядок строго по ``row``: он определяет выбор пары при равных
    прочих признаках (§5.9.2) и обязан быть воспроизводимым (§12).
    """
    classes = ops_classes_for(category, exclude_service=True)
    by_day_ledger: dict[date, list[LedgerEntry]] = defaultdict(list)
    by_day_ops: dict[date, list[OpsEntry]] = defaultdict(list)

    for posting in ledger:
        if posting.category is category and posting.row not in neutralized:
            by_day_ledger[posting.date].append(posting)
    for operation in ops:
        if operation.classification in classes:
            by_day_ops[operation.dt.date()].append(operation)

    for ledger_bucket in by_day_ledger.values():
        ledger_bucket.sort(key=lambda item: item.row)
    for ops_bucket in by_day_ops.values():
        ops_bucket.sort(key=lambda item: item.row)
    return dict(by_day_ledger), dict(by_day_ops)


# --------------------------------------------------------------------------- #
# §5.9.2 — подокументный режим
# --------------------------------------------------------------------------- #


def greedy_match(
    ledger: Sequence[LedgerEntry],
    ops: Sequence[OpsEntry],
    config: Config,
) -> tuple[tuple[int, int], ...]:
    """Проход 1 подокументного режима — жадное сопоставление (§5.9.2).

    Точная сумма в окне ``DATE_WIN``, детерминированный порядок (по дате, затем
    ``row``); при нескольких кандидатах — минимальная разница дат, затем
    меньший ``row``.

    Returns:
        Пары ``(ledger_row, ops_row)``.
    """
    window = config.thresholds.DATE_WIN
    taken: set[int] = set()
    pairs: list[tuple[int, int]] = []

    for posting in sorted(ledger, key=lambda entry: (entry.date, entry.row)):
        target = posting.debit + posting.credit
        candidates = [
            entry
            for entry in ops
            if entry.row not in taken
            and entry.amount == target
            and abs((entry.dt.date() - posting.date).days) <= window
        ]
        if not candidates:
            continue
        chosen = min(
            candidates,
            key=lambda entry: (abs((entry.dt.date() - posting.date).days), entry.row),
        )
        taken.add(chosen.row)
        pairs.append((posting.row, chosen.row))

    return tuple(pairs)


def hungarian_match(
    ledger: Sequence[LedgerEntry],
    ops: Sequence[OpsEntry],
    weights: tuple[float, float, float],
    config: Config,
) -> tuple[tuple[int, int], ...]:
    """Проход 2 подокументного режима — венгерский алгоритм (§5.9.2).

    ``cost(i,j) = w1·|Δсумма| + w2·|Δдней| + w3·(1 − similarity(имя_i, имя_j))``,
    решается ``scipy.optimize.linear_sum_assignment``.

    ``float`` живёт внутри матрицы стоимостей и наружу не выходит: возвращаются
    номера строк, а не суммы (§10).

    Непарные записи с обеих сторон и есть находки: «проводка без выдачи»
    (``RKO_WITHOUT_PAYOUT``) и «выдача без проводки» (``PAYOUT_NOT_BOOKED``).
    """
    if not ledger or not ops:
        return ()

    window = config.thresholds.DATE_WIN
    w1, w2, w3 = weights
    forbidden = 1e9

    cost = np.full((len(ledger), len(ops)), forbidden, dtype=float)
    for i, posting in enumerate(ledger):
        for j, operation in enumerate(ops):
            days = abs((operation.dt.date() - posting.date).days)
            if days > window:
                continue
            delta = abs(float(posting.debit + posting.credit - operation.amount))
            similarity = name_similarity(posting.doc_text, operation.counterparty)
            cost[i, j] = w1 * delta + w2 * days + w3 * (1.0 - similarity)

    rows, cols = linear_sum_assignment(cost)
    return tuple(
        (ledger[i].row, ops[j].row)
        for i, j in sorted(zip(rows.tolist(), cols.tolist(), strict=True))
        if cost[i, j] < forbidden
    )


# --------------------------------------------------------------------------- #
# §5.9.4 / §7 — subset-sum и гейты
# --------------------------------------------------------------------------- #


def subset_sum_solutions(
    amounts_kopecks: Sequence[int],
    target_kopecks: int,
    tolerance_kopecks: int,
    max_subset_size: int | None = None,
) -> tuple[tuple[int, ...], ...]:
    """Все подмножества, попадающие в допуск — §5.9.4.

    Перебор битовыми масками при ``N ≤ BITMASK_LIMIT``.

    Args:
        amounts_kopecks: суммы кандидатов в копейках.
        target_kopecks: цель в копейках.
        tolerance_kopecks: допуск в копейках.
        max_subset_size: ограничение размера подмножества либо ``None``.

    Returns:
        Кортеж решений; каждое — кортеж индексов по возрастанию
        (детерминированность §12).

    Raises:
        ValueError: ``N > BITMASK_LIMIT``. Такой вызов означает, что гейт 1
            (§7.3) не был применён: он отсекает ``N > HARD_MAX`` безусловно.
    """
    count = len(amounts_kopecks)
    if count > BITMASK_LIMIT:
        message = (
            f"перебор при N={count} не выполняется: §7.3 отсекает N > "
            f"{BITMASK_LIMIT} гейтом 1 до перебора"
        )
        raise ValueError(message)

    solutions: list[tuple[int, ...]] = []
    for mask in range(1, 1 << count):
        if max_subset_size is not None and mask.bit_count() > max_subset_size:
            continue
        total = sum(amounts_kopecks[i] for i in range(count) if mask >> i & 1)
        if abs(total - target_kopecks) <= tolerance_kopecks:
            solutions.append(tuple(i for i in range(count) if mask >> i & 1))
    return tuple(solutions)


def _reachable_bitset(amounts_kopecks: Sequence[int]) -> int:
    """Битовая маска достижимых сумм подмножеств — вспомогательное для §7.3.

    Бит ``k`` установлен, если сумма ``k`` копеек достижима. Даёт проверку
    достижимости за ``O(N)`` операций над длинным целым — этого достаточно
    перестановочному тесту, которому нужен факт попадания, а не сами решения.
    """
    reachable = 1
    for amount in amounts_kopecks:
        if amount > 0:
            reachable |= reachable << amount
    return reachable


def _hits_target(reachable: int, target_kopecks: int, tolerance_kopecks: int) -> bool:
    """Попадает ли хоть одна достижимая сумма в допуск вокруг цели."""
    low = max(0, target_kopecks - tolerance_kopecks)
    high = target_kopecks + tolerance_kopecks
    width = high - low + 1
    return (reachable >> low) & ((1 << width) - 1) != 0


def gate_candidate_count(candidate_count: int, config: Config) -> bool:
    """Гейт 1 — число кандидатов (§7.3).

    ``N ≤ MAX_CANDIDATES`` (10). При ``N > HARD_MAX`` (15) — безусловный отказ.
    """
    return candidate_count <= config.subset_sum.MAX_CANDIDATES


def gate_uniqueness(solutions: Sequence[tuple[int, ...]], config: Config) -> bool:
    """Гейт 2 — единственность (§7.3).

    Ровно одно подмножество попадает в допуск. При ≥ 2 — статус ``AMBIGUOUS``:
    любая из комбинаций указала бы на конкретного клиента, и выбирать между
    ними не на чем.
    """
    if not config.subset_sum.REQUIRE_UNIQUE:
        return bool(solutions)
    return len(solutions) == 1


def gate_density(
    candidate_count: int,
    tolerance_kopecks: int,
    reachable_width_kopecks: int,
) -> tuple[bool, float]:
    """Гейт 3 — плотность решений (§7.2, §7.3).

    ``ожидаемое_число_решений ≈ (2^N · 2ε) / W ≤ 1``, то есть
    ``N ≲ log₂(W / 2ε)``.

    Оценка оптимистична: реальные суммы кластеризуются (круглые числа,
    повторяющиеся заказы), плотность выше равномерной. Расчётный N — верхняя
    граница, рабочий предел жёстче (гейт 1).

    Returns:
        Пара ``(прошёл, ожидаемое_число_решений)``.
    """
    if reachable_width_kopecks <= 0:
        return (False, math.inf)
    expected = (2.0**candidate_count) * (2 * tolerance_kopecks + 1) / reachable_width_kopecks
    return (expected <= 1.0, expected)


def gate_permutation_test(
    amounts_kopecks: Sequence[int],
    target_kopecks: int,
    tolerance_kopecks: int,
    config: Config,
    pool_kopecks: Sequence[int] | None = None,
) -> tuple[bool, float]:
    """Гейт 4 — перестановочный тест (§7.3).

    ``p = (1 + #{перестановок с попаданием}) / (1 + B) < PERMUTATION_ALPHA``,
    ``B ≥ 1000``. Нуль-модель — ресэмплинг ``N`` сумм с возвращением из
    эмпирического распределения; проверяется, попадает ли хоть одно подмножество
    случайной выборки в допуск вокруг цели.

    **Пул берётся по периоду, а не по дню.** §7.3 допускает «дня/периода», но
    ресэмплинг из сумм самого дня вырождает тест: искомое подмножество лежит в
    пуле по построению, попадание случается почти всегда, и ни одна находка не
    проходит. Пул периода отвечает на осмысленный вопрос — насколько особенны
    именно эти выдачи по сравнению с типичными выдачами того же масштаба.

    Seed берётся из конфига и фиксируется в отчёте (§12): без этого повторный
    прогон дал бы другое ``p`` и другой состав находок.

    Args:
        amounts_kopecks: суммы кандидатов дня; задают размер выборки ``N``.
        target_kopecks: цель.
        tolerance_kopecks: допуск.
        config: конфигурация §6 — ``PERMUTATION_B``, ``PERMUTATION_ALPHA``, seed.
        pool_kopecks: эмпирическое распределение периода; ``None`` — использовать
            суммы дня (вырожденный случай, оставлен для прямых вызовов в тестах).

    Returns:
        Пара ``(прошёл, p_value)``.
    """
    trials = config.subset_sum.PERMUTATION_B
    rng = random.Random(config.seed)  # noqa: S311
    pool = list(pool_kopecks) if pool_kopecks else list(amounts_kopecks)
    size = len(amounts_kopecks)
    hits = 0
    for _ in range(trials):
        sample = [rng.choice(pool) for _ in range(size)]
        if _hits_target(_reachable_bitset(sample), target_kopecks, tolerance_kopecks):
            hits += 1
    p_value = (1 + hits) / (1 + trials)
    return (p_value < config.subset_sum.PERMUTATION_ALPHA, p_value)


def apply_gates(  # noqa: PLR0911
    amounts_kopecks: Sequence[int],
    target_kopecks: int,
    config: Config,
    pool_kopecks: Sequence[int] | None = None,
) -> tuple[SubsetSumGateReport, tuple[int, ...] | None]:
    """Применить все четыре гейта — §7.3.

    Находка принимается **только** при выполнении всех четырёх. Протокол
    возвращается всегда, включая отказы: пользователь обязан видеть, какой
    именно гейт закрылся (§0.3).

    Гейты идут в порядке возрастания стоимости: число кандидатов отсекает
    безусловно и до перебора, перестановочный тест считается последним.

    Args:
        amounts_kopecks: суммы кандидатов дня в копейках.
        target_kopecks: цель в копейках.
        config: конфигурация §6.
        pool_kopecks: эмпирическое распределение периода для гейта 4 (§7.3).

    Returns:
        Пара ``(протокол, решение)``; решение — кортеж индексов либо ``None``,
        если хоть один гейт не пройден.
    """
    count = len(amounts_kopecks)
    tolerance = to_kopecks(config.subset_sum.TOLERANCE)
    seed = config.seed

    def refuse(reason: str, **extra: object) -> tuple[SubsetSumGateReport, None]:
        found = extra.get("solutions_found", 0)
        return (
            SubsetSumGateReport(
                candidate_count=count,
                solutions_found=found if isinstance(found, int) else 0,
                gate_count_passed=bool(extra.get("gate_count_passed", False)),
                gate_unique_passed=bool(extra.get("gate_unique_passed", False)),
                gate_density_passed=bool(extra.get("gate_density_passed", False)),
                gate_permutation_passed=bool(extra.get("gate_permutation_passed", False)),
                expected_solutions=extra.get("expected_solutions"),  # type: ignore[arg-type]
                p_value=extra.get("p_value"),  # type: ignore[arg-type]
                permutation_b=config.subset_sum.PERMUTATION_B,
                seed=seed,
                refusal_reason=reason,
            ),
            None,
        )

    if count > config.subset_sum.HARD_MAX:
        return refuse(
            f"гейт 1: кандидатов {count} > HARD_MAX {config.subset_sum.HARD_MAX} — "
            "безусловный отказ, любая комбинация попала бы в цель",
        )
    if not gate_candidate_count(count, config):
        return refuse(
            f"гейт 1: кандидатов {count} > MAX_CANDIDATES {config.subset_sum.MAX_CANDIDATES}",
        )

    solutions = subset_sum_solutions(
        amounts_kopecks,
        target_kopecks,
        tolerance,
        config.subset_sum.MAX_SUBSET_SIZE,
    )
    if not solutions:
        return refuse(
            "подмножество, попадающее в допуск, не найдено: расхождение не "
            "выражается целыми выдачами дня",
            gate_count_passed=True,
            solutions_found=0,
        )
    if not gate_uniqueness(solutions, config):
        return refuse(
            f"гейт 2: решений {len(solutions)}, требуется ровно одно — AMBIGUOUS",
            gate_count_passed=True,
            solutions_found=len(solutions),
        )

    width = sum(amount for amount in amounts_kopecks if amount > 0)
    density_passed, expected = gate_density(count, tolerance, width)
    if not density_passed:
        return refuse(
            f"гейт 3: ожидаемое число решений {expected:.2f} > 1 — попадание "
            "объяснимо плотностью, а не конкретной комбинацией",
            gate_count_passed=True,
            gate_unique_passed=True,
            solutions_found=len(solutions),
            expected_solutions=expected,
        )

    permutation_passed, p_value = gate_permutation_test(
        amounts_kopecks,
        target_kopecks,
        tolerance,
        config,
        pool_kopecks,
    )
    if not permutation_passed:
        return refuse(
            f"гейт 4: p = {p_value:.4f} ≥ {config.subset_sum.PERMUTATION_ALPHA} — "
            "случайные суммы того же масштаба попадают в цель не реже",
            gate_count_passed=True,
            gate_unique_passed=True,
            gate_density_passed=True,
            solutions_found=len(solutions),
            expected_solutions=expected,
            p_value=p_value,
        )

    return (
        SubsetSumGateReport(
            candidate_count=count,
            solutions_found=len(solutions),
            gate_count_passed=True,
            gate_unique_passed=True,
            gate_density_passed=True,
            gate_permutation_passed=True,
            expected_solutions=expected,
            p_value=p_value,
            permutation_b=config.subset_sum.PERMUTATION_B,
            seed=seed,
            refusal_reason=None,
        ),
        solutions[0],
    )


# --------------------------------------------------------------------------- #
# §5.9 — стадия целиком
# --------------------------------------------------------------------------- #


def _sum(entries: Sequence[LedgerEntry] | Sequence[OpsEntry]) -> Decimal:
    total = _ZERO
    for entry in entries:
        total += entry.debit + entry.credit if isinstance(entry, LedgerEntry) else entry.amount
    return total


def _result(
    day: date,
    category: Category,
    mode: PostingMode,
    status: LocalizationStatus,
    code: FindingCode | None,
    amount: Decimal,
    balance_impact: Decimal,
    explanation: str,
    *,
    ledger_rows: tuple[int, ...] = (),
    ops_rows: tuple[int, ...] = (),
    doc_numbers: tuple[str, ...] = (),
    gates: SubsetSumGateReport | None = None,
    confidence: float = 1.0,
) -> LocalizationResult:
    return LocalizationResult(
        date=day,
        category=category,
        mode=mode,
        status=status,
        code=code,
        amount=amount,
        balance_impact=balance_impact,
        ledger_rows=ledger_rows,
        ops_rows=ops_rows,
        doc_numbers=doc_numbers,
        gates=gates,
        confidence=confidence,
        explanation=explanation,
    )


def _localize_day(
    day: date,
    category: Category,
    mode: PostingMode,
    postings: Sequence[LedgerEntry],
    operations: Sequence[OpsEntry],
    config: Config,
    pool_kopecks: Sequence[int] = (),
) -> list[LocalizationResult]:
    """Локализовать один проблемный день — §5.9.2, §5.9.3, §5.9.4, §7.4.

    Порядок §14: **сопоставление 1:1 → правило единственной проводки →
    subset-sum с гейтами**. Первый шаг обязателен и не является оптимизацией:
    пока он пропускался, день 06.12.2025 Солигорска с проводками 2 493,51 и
    80,83 при выдаче 80,83 в логе не разбирался вовсе — «проводок две, правило
    §5.9.3 неприменимо», — хотя после снятия очевидной пары остаётся ровно одна
    проводка и избыток 2 075,31 приписывается ей. Это четвёртый из четырёх
    завышенных РКО эталона §11.3; без сопоставления он терялся.

    Снятие пар меняет и обратную сторону: из кандидатов subset-sum уходят
    выдачи, у которых проводка есть, — это и сужает перебор, и убирает
    дубликаты сумм, на которых закрывался гейт уникальности §7.3.

    ``pool_kopecks`` — эмпирическое распределение сумм за период; нужно гейту 4
    (§7.3), чтобы нуль-модель не вырождалась на суммах самого дня.
    """
    acc = _sum(postings)
    ops_total = _sum(operations)
    diff = acc - ops_total

    # §5.9.2 — снять однозначные пары «проводка = выдача». Разница дня от этого
    # не меняется: из обеих частей уходит одна и та же сумма.
    paired = greedy_match(postings, operations, config)
    matched_ledger = {ledger_row for ledger_row, _ in paired}
    matched_ops = {ops_row for _, ops_row in paired}
    postings = [entry for entry in postings if entry.row not in matched_ledger]
    operations = [entry for entry in operations if entry.row not in matched_ops]

    # После снятия пар обе части уменьшились на одну и ту же сумму, поэтому
    # ``diff`` не изменился и остаётся разницей дня.
    unpaired_acc = _sum(postings)
    unpaired_ops = _sum(operations)
    paired_note = (
        f" Снято {len(paired)} однозначных пар «проводка = выдача» (§5.9.2)." if paired else ""
    )

    # Выдачи есть, проводок к ним нет (§8, PAYOUT_NOT_BOOKED).
    # balance_impact = 0: этих проводок в 1С нет, на сальдо они не влияют (§4.3).
    if not postings and operations:
        return [
            _result(
                day,
                category,
                mode,
                LocalizationStatus.LOCALIZED,
                FindingCode.PAYOUT_NOT_BOOKED,
                unpaired_ops,
                _ZERO,
                (
                    f"За {day:%d.%m.%Y} в опер-логе {len(operations)} выдач на "
                    f"{unpaired_ops}, проводок к ним в 1С нет. На сальдо не влияет: "
                    f"пробел контроля, а не причина отклонения.{paired_note}"
                ),
                ops_rows=tuple(entry.row for entry in operations),
            ),
        ]

    # Проводка есть, выдач в логе нет (§8, RKO_WITHOUT_PAYOUT).
    if postings and not operations:
        return [
            _result(
                day,
                category,
                mode,
                LocalizationStatus.LOCALIZED,
                FindingCode.RKO_WITHOUT_PAYOUT,
                unpaired_acc,
                unpaired_acc,
                (
                    f"За {day:%d.%m.%Y} в 1С проведено {len(postings)} документов на "
                    f"{unpaired_acc}, выдач по ним в опер-логе нет. Требует проверки: "
                    f"инструмент не может сказать, какая из двух систем права (§16)."
                    f"{paired_note}"
                ),
                ledger_rows=tuple(entry.row for entry in postings),
                doc_numbers=tuple(entry.doc_number for entry in postings if entry.doc_number),
            ),
        ]

    # Правило единственной проводки — §5.9.3. Комбинаторики не требует, поэтому
    # гейты §7 к нему неприменимы: это самый сильный тип локализации.
    #
    # Применимо только когда 1С провела БОЛЬШЕ, чем показывает лог: именно так
    # сформулирован эталон §5.9.3 (R987 · РКО 00000257506 завышен на 160,89 —
    # в 1С 289,31, в логе одна выдача 128,42). В обратную сторону приписывать
    # расхождение проводке нельзя: если выдач больше, чем проведено, вопрос не
    # «на сколько завышена проводка», а «какие выдачи не проведены», и отвечать
    # на него нужно перебором по выдачам с гейтами §7.
    if len(postings) == 1 and diff > _ZERO:
        posting = postings[0]
        return [
            _result(
                day,
                category,
                mode,
                LocalizationStatus.LOCALIZED,
                FindingCode.RKO_OVERSTATED,
                abs(diff),
                diff,
                (
                    f"{posting.doc_text or 'документ'} от {day:%d.%m.%Y}: в 1С "
                    f"{unpaired_acc}, в опер-логе без пары {unpaired_ops} "
                    f"({len(operations)} записей). Расхождение {abs(diff)} "
                    "приписано единственной несопоставленной проводке дня — иных "
                    f"кандидатов нет.{paired_note}"
                ),
                ledger_rows=(posting.row,),
                ops_rows=tuple(entry.row for entry in operations),
                doc_numbers=(posting.doc_number,) if posting.doc_number else (),
            ),
        ]

    # Абсолютный запрет §7.4: ниже дневного агрегата продаж не локализуем.
    if category is Category.INCOME:
        return [
            _result(
                day,
                category,
                mode,
                LocalizationStatus.REFUSED_BELOW_Z_REPORT,
                None,
                abs(diff),
                diff,
                (
                    f"Расхождение {abs(diff)} локализовано до дня {day:%d.%m.%Y} и до "
                    f"агрегата; ниже — требуется Z-отчёт за {day:%d.%m.%Y}. "
                    "1С хранит свод Z-отчёта одной проводкой, опер-лог — поштучные "
                    "чеки; разложение агрегата на чеки запрещено §7.4 независимо "
                    "от гейтов."
                ),
                ledger_rows=tuple(entry.row for entry in postings),
                ops_rows=tuple(entry.row for entry in operations),
            ),
        ]

    # §5.9.4 — subset-sum с гейтами §7.3.
    # Знак разницы задаёт, что именно ищем: недостающие выдачи или лишние проводки.
    if diff < _ZERO:
        candidates: Sequence[LedgerEntry] | Sequence[OpsEntry] = operations
        code = FindingCode.PAYOUT_NOT_BOOKED
        impact = _ZERO
    else:
        candidates = postings
        code = FindingCode.RKO_WITHOUT_PAYOUT
        impact = diff

    amounts = [
        to_kopecks(entry.debit + entry.credit if isinstance(entry, LedgerEntry) else entry.amount)
        for entry in candidates
    ]
    gates, solution = apply_gates(amounts, to_kopecks(abs(diff)), config, pool_kopecks)

    if solution is None:
        return [
            _result(
                day,
                category,
                mode,
                LocalizationStatus.AMBIGUOUS
                if gates.solutions_found >= _AMBIGUOUS_MIN_SOLUTIONS
                else LocalizationStatus.NOT_LOCALIZED,
                None,
                abs(diff),
                impact,
                (
                    f"Расхождение {abs(diff)} за {day:%d.%m.%Y} до конкретного "
                    f"документа не локализовано. {gates.refusal_reason}. "
                    "Локализация остаётся на уровне дня."
                ),
                ledger_rows=tuple(entry.row for entry in postings),
                ops_rows=tuple(entry.row for entry in operations),
                gates=gates,
                confidence=0.0,
            ),
        ]

    picked = [candidates[i] for i in solution]
    return [
        _result(
            day,
            category,
            mode,
            LocalizationStatus.LOCALIZED,
            code,
            abs(diff),
            impact,
            (
                f"Расхождение {abs(diff)} за {day:%d.%m.%Y} сведено к "
                f"{len(picked)} записям из {len(candidates)} кандидатов. "
                f"Решение единственно, p = {gates.p_value:.4f}, ожидаемое число "
                f"решений {gates.expected_solutions:.3f} — все четыре гейта §7.3 "
                "пройдены."
            ),
            ledger_rows=tuple(entry.row for entry in picked if isinstance(entry, LedgerEntry))
            or tuple(entry.row for entry in postings),
            ops_rows=tuple(entry.row for entry in picked if isinstance(entry, OpsEntry)),
            doc_numbers=tuple(
                entry.doc_number
                for entry in picked
                if isinstance(entry, LedgerEntry) and entry.doc_number
            ),
            gates=gates,
            confidence=1.0 - (gates.p_value or 0.0),
        ),
    ]


def localize(
    classified: ClassifyResult,
    reversals: ReversalResult,
    timing: dict[Category, CollapseResult],
    config: Config,
) -> tuple[LocalizationResult, ...]:
    """Стадия LOCALIZE целиком — §5.9.

    Работает по несводимым остаткам §5.7: свёртка уже убрала мнимые расхождения,
    и локализовать нужно только то, что после неё осталось.

    Порядок: режим §5.9.1 → правило единственной проводки §5.9.3 → subset-sum с
    гейтами §5.9.4. Дни, покрытые агрегатом продаж, получают статус
    ``REFUSED_BELOW_Z_REPORT`` без попытки перебора (§7.4).

    Локализация окна смещения (§5.8.5) подключается на этапе 3: ей нужен
    ``BalanceTrace``, которого на этом этапе ещё нет.

    Returns:
        Результаты, упорядоченные по ``(категория, дата)`` — §12.
    """
    results: list[LocalizationResult] = []

    for category in RECONCILED_CATEGORIES:
        collapse = timing.get(category)
        if collapse is None:
            continue
        mode = posting_mode(classified.ledger, classified.ops, category, config)
        by_ledger, by_ops = day_index(
            classified.ledger,
            classified.ops,
            category,
            reversals.neutralized_rows,
        )
        # Пул периода для гейта 4 §7.3 — суммы всех выдач категории.
        pool = [to_kopecks(entry.amount) for bucket in by_ops.values() for entry in bucket]
        for day, _diff in collapse.residual_days:
            results.extend(
                _localize_day(
                    day,
                    category,
                    mode,
                    by_ledger.get(day, []),
                    by_ops.get(day, []),
                    config,
                    pool,
                ),
            )

    results.sort(key=lambda item: (item.category.value, item.date, item.ledger_rows, item.ops_rows))
    return tuple(results)


def unmatched_records(
    classified: ClassifyResult,
    reversals: ReversalResult,
    category: Category,
    config: Config,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Непарные записи подокументного режима — §5.9.2.

    Сопоставление идёт внутри окна ``DATE_WIN``; всё, что осталось без пары с
    обеих сторон, и есть находки: «проводка без выдачи» и «выдача без проводки».

    Returns:
        Пара ``(строки 1С без пары, строки лога без пары)``.
    """
    classes = ops_classes_for(category, exclude_service=True)
    postings = [
        entry
        for entry in classified.ledger
        if entry.category is category and entry.row not in reversals.neutralized_rows
    ]
    operations = [entry for entry in classified.ops if entry.classification in classes]

    pairs = greedy_match(postings, operations, config)
    matched_ledger = {ledger_row for ledger_row, _ in pairs}
    matched_ops = {ops_row for _, ops_row in pairs}

    return (
        tuple(sorted(entry.row for entry in postings if entry.row not in matched_ledger)),
        tuple(sorted(entry.row for entry in operations if entry.row not in matched_ops)),
    )
