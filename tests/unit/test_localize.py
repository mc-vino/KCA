"""Юнит-тесты стадии LOCALIZE — §5.9 и гейты §7."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from cashforensics.localize import (
    BITMASK_LIMIT,
    apply_gates,
    gate_candidate_count,
    gate_density,
    gate_uniqueness,
    greedy_match,
    localize,
    name_similarity,
    posting_mode,
    subset_sum_solutions,
    to_kopecks,
)
from cashforensics.models import (
    Category,
    ClassifyResult,
    CollapseResult,
    Config,
    FindingCode,
    LedgerEntry,
    LocalizationStatus,
    OpsClass,
    OpsEntry,
    PostingMode,
    ReversalResult,
)
from tests.unit.test_classify import ledger_entry, ops_entry

pytestmark = pytest.mark.unit

ZERO = Decimal("0.00")
DAY = date(2024, 2, 1)


def _refund_posting(row: int, amount: Decimal, day: date = DAY) -> LedgerEntry:
    return ledger_entry(
        row=row,
        day=day,
        credit=amount,
        account="76.9.1",
        category=Category.REFUND,
        doc=f"Расходный кассовый ордер 0002{row:05d}",
    )


def _payout(row: int, amount: Decimal, hour: int = 12, day: date = DAY) -> OpsEntry:
    return ops_entry(
        row=row,
        moment=datetime(day.year, day.month, day.day, hour, 0, 0),
        amount=amount,
        counterparty="Иванов Иван",
    ).model_copy(update={"classification": OpsClass.REFUND, "classified_by": "counterparty"})


def _classified(ledger: tuple[LedgerEntry, ...], ops: tuple[OpsEntry, ...]) -> ClassifyResult:
    return ClassifyResult(ledger=ledger, ops=ops, fallback=None, unknown_accounts=())


def _timing(days: tuple[tuple[date, Decimal], ...]) -> dict[Category, CollapseResult]:
    return {
        Category.REFUND: CollapseResult(
            residual=sum((diff for _, diff in days), ZERO),
            collapsed=0,
            redated=0,
            total=len(days),
            residual_days=days,
            lag=None,
            calendar_aggregations=(),
            audit_log=(),
        ),
    }


def _no_reversals() -> ReversalResult:
    return ReversalResult(neutralized_rows=frozenset(), findings=(), audit_log=())


class TestKopecks:
    """§10: subset-sum считается в копейках."""

    def test_conversion_is_exact(self) -> None:
        assert to_kopecks(Decimal("128.42")) == 12842
        assert to_kopecks(Decimal("0.01")) == 1

    def test_result_is_int(self) -> None:
        assert isinstance(to_kopecks(Decimal("289.31")), int)


class TestPostingMode:
    """§5.9.1: режим проведения."""

    def test_aggregate_mode_above_ratio(self, config: Config) -> None:
        """Солигорск: 5 771 выдача на 1 811 проводок = 3,2 → агрегаты."""
        ledger = tuple(_refund_posting(row, Decimal("100.00")) for row in range(1, 4))
        ops = tuple(_payout(100 + index, Decimal("30.00")) for index in range(10))

        assert posting_mode(ledger, ops, Category.REFUND, config) is PostingMode.DAILY_AGGREGATE

    def test_per_document_mode_below_ratio(self, config: Config) -> None:
        ledger = tuple(_refund_posting(row, Decimal("100.00")) for row in range(1, 11))
        ops = tuple(_payout(100 + index, Decimal("100.00")) for index in range(10))

        assert posting_mode(ledger, ops, Category.REFUND, config) is PostingMode.PER_DOCUMENT


class TestSubsetSum:
    """§5.9.4: перебор в копейках."""

    def test_finds_exact_subset(self) -> None:
        solutions = subset_sum_solutions([10000, 20000, 30000], 50000, 1)

        assert (1, 2) in solutions

    def test_indices_are_sorted(self) -> None:
        """§12: порядок индексов детерминирован."""
        for solution in subset_sum_solutions([100, 200, 300, 400], 700, 1):
            assert list(solution) == sorted(solution)

    def test_refuses_above_bitmask_limit(self) -> None:
        """Перебор выше предела не выполняется — §7.3 отсекает гейтом 1."""
        with pytest.raises(ValueError, match="гейт"):
            subset_sum_solutions([1] * (BITMASK_LIMIT + 1), 5, 1)


class TestGates:
    """§7.3: четыре обязательных гейта."""

    def test_gate1_candidate_count(self, config: Config) -> None:
        assert gate_candidate_count(10, config)
        assert not gate_candidate_count(11, config)

    def test_gate2_requires_exactly_one_solution(self, config: Config) -> None:
        assert gate_uniqueness([(0, 1)], config)
        assert not gate_uniqueness([(0, 1), (2,)], config)
        assert not gate_uniqueness([], config)

    def test_gate3_density_formula(self) -> None:
        """``(2^N · 2ε)/W ≤ 1`` — §7.2."""
        tight_passed, tight_expected = gate_density(5, 1, 1_000_000)
        loose_passed, loose_expected = gate_density(20, 1, 100)

        assert tight_passed
        assert tight_expected < 1.0
        assert not loose_passed
        assert loose_expected > 1.0

    def test_unique_solution_is_accepted(self, config: Config) -> None:
        """§11.1: subset-sum — уникальное решение принимается."""
        amounts = [12842, 55511, 91237, 40013]
        pool = [11111, 22222, 33333, 44444, 55555, 66666, 77777, 88888]

        report, solution = apply_gates(amounts, 12842, config, pool)

        assert solution == (0,)
        assert report.gate_count_passed
        assert report.gate_unique_passed
        assert report.gate_density_passed
        assert report.gate_permutation_passed
        assert report.refusal_reason is None

    def test_two_solutions_give_ambiguous(self, config: Config) -> None:
        """§11.1: subset-sum — два решения → AMBIGUOUS."""
        amounts = [10000, 10000, 20000]

        report, solution = apply_gates(amounts, 20000, config)

        assert solution is None
        assert report.solutions_found >= 2
        assert not report.gate_unique_passed
        assert "AMBIGUOUS" in (report.refusal_reason or "")

    def test_eighty_candidates_are_refused(self, config: Config) -> None:
        """§11.1: subset-sum — N=80 → отказ гейтом, без перебора."""
        amounts = [100 * (index + 1) for index in range(80)]

        report, solution = apply_gates(amounts, 500, config)

        assert solution is None
        assert report.candidate_count == 80
        assert not report.gate_count_passed
        assert "HARD_MAX" in (report.refusal_reason or "")

    def test_refusal_report_names_the_gate(self, config: Config) -> None:
        """§0.3: пользователь обязан видеть, какой именно гейт закрылся."""
        report, _ = apply_gates([100] * 12, 300, config)

        assert report.refusal_reason
        assert "гейт 1" in report.refusal_reason

    def test_seed_is_recorded(self, config: Config) -> None:
        """§12: seed перестановочного теста фиксируется в отчёте."""
        report, _ = apply_gates([12842, 55511], 12842, config, [11111, 22222, 33333])

        assert report.seed == config.seed
        assert report.permutation_b == config.subset_sum.PERMUTATION_B

    def test_gates_are_deterministic(self, config: Config) -> None:
        """§13.5: повторный прогон даёт то же решение и то же p."""
        amounts = [12842, 55511, 91237]
        pool = [11111, 22222, 33333, 44444, 55555]

        first = apply_gates(amounts, 12842, config, pool)
        second = apply_gates(amounts, 12842, config, pool)

        assert first[1] == second[1]
        assert first[0].p_value == second[0].p_value


class TestSinglePostingRule:
    """§5.9.3: правило единственной проводки."""

    def test_single_posting_takes_the_difference(self, config: Config) -> None:
        """Эталон §5.9.3: в 1С 289,31, в логе одна выдача 128,42 → завышено на 160,89.

        Воспроизведено на реальной выгрузке PAX_119049688 (Витебск): строка 987,
        РКО 00000257506 от 31.05.2026 — единственная находка кассы, и она
        объясняет всё отклонение сальдо −160,89 (§11.3).
        """
        ledger = (_refund_posting(987, Decimal("289.31")),)
        ops = (_payout(100, Decimal("128.42")),)

        results = localize(
            _classified(ledger, ops),
            _no_reversals(),
            _timing(((DAY, Decimal("160.89")),)),
            config,
        )

        assert len(results) == 1
        result = results[0]
        assert result.status is LocalizationStatus.LOCALIZED
        assert result.code is FindingCode.RKO_OVERSTATED
        assert result.amount == Decimal("160.89")
        assert result.ledger_rows == (987,)
        assert result.gates is None

    def test_rule_applies_after_pairs_are_removed(self, config: Config) -> None:
        """§14: сопоставление 1:1 идёт **до** правила единственной проводки.

        Форма 06.12.2025 Солигорска: в 1С проводки 2 493,51 и 80,83, в логе
        выдача 80,83 и ещё четыре на 418,20. Пока пары не снимались, день
        отбрасывался как «проводок две, §5.9.3 неприменимо», и четвёртый из
        четырёх завышенных РКО эталона §11.3 терялся. После снятия очевидной
        пары остаётся ровно одна проводка, и избыток 2 075,31 её.
        """
        ledger = (
            _refund_posting(20235, Decimal("2493.51")),
            _refund_posting(20238, Decimal("80.83")),
        )
        ops = (
            _payout(100, Decimal("10.36")),
            _payout(101, Decimal("288.00")),
            _payout(102, Decimal("75.00")),
            _payout(103, Decimal("44.84")),
            _payout(104, Decimal("80.83")),
        )

        results = localize(
            _classified(ledger, ops),
            _no_reversals(),
            _timing(((DAY, Decimal("2075.31")),)),
            config,
        )

        assert len(results) == 1
        result = results[0]
        assert result.code is FindingCode.RKO_OVERSTATED
        assert result.amount == Decimal("2075.31")
        assert result.ledger_rows == (20235,)
        assert result.gates is None

    def test_aggregate_posting_covered_by_payouts_is_removed(self, config: Config) -> None:
        """§5.9.1: в режиме агрегатов проводка закрывает группу выдач.

        Форма 21.04.2023 Солигорска: проводки 637,00 и 53,45 против выдач
        352,00 + 24,50 + 260,50 + 41,60. Первая проводка — агрегат трёх выдач,
        сопоставление 1:1 §5.9.2 его не видит, и день отбрасывался как «проводок
        две». После снятия агрегата остаётся 53,45 при выдаче 41,60 → завышение
        11,85.
        """
        ledger = (
            _refund_posting(6801, Decimal("637.00")),
            _refund_posting(6804, Decimal("53.45")),
        )
        ops = (
            _payout(2301, Decimal("41.60")),
            _payout(2302, Decimal("352.00")),
            _payout(2303, Decimal("24.50")),
            _payout(2304, Decimal("260.50")),
        )

        results = localize(
            _classified(ledger, ops),
            _no_reversals(),
            _timing(((DAY, Decimal("11.85")),)),
            config,
        )

        assert len(results) == 1
        result = results[0]
        assert result.code is FindingCode.RKO_OVERSTATED
        assert result.amount == Decimal("11.85")
        assert result.ledger_rows == (6804,)

    def test_cover_is_refused_when_no_posting_is_left_over(self, config: Config) -> None:
        """Форма 11.10.2022: покрываются обе проводки — «остаток» пришлось бы выбрать.

        Пока непокрытой проводки ровно одна, она и есть остаток дня. Если
        покрываются все, выбор остатка становится догадкой, и день остаётся
        неразобранным (§7.1).
        """
        ledger = (
            _refund_posting(1, Decimal("70.00")),
            _refund_posting(2, Decimal("55.00")),
        )
        ops = (
            _payout(100, Decimal("50.00")),
            _payout(101, Decimal("20.00")),
            _payout(102, Decimal("25.00")),
            _payout(103, Decimal("30.00")),
            _payout(104, Decimal("15.00")),
        )

        results = localize(
            _classified(ledger, ops),
            _no_reversals(),
            _timing(((DAY, Decimal("-15.00")),)),
            config,
        )

        assert results[0].code is not FindingCode.RKO_OVERSTATED

    def test_cover_is_refused_when_it_is_not_unique(self, config: Config) -> None:
        """Покрытие несколькими способами — какие выдачи израсходованы, неизвестно."""
        ledger = (
            _refund_posting(1, Decimal("75.00")),
            _refund_posting(2, Decimal("300.00")),
        )
        ops = (
            _payout(100, Decimal("50.00")),
            _payout(101, Decimal("25.00")),
            _payout(102, Decimal("50.00")),
            _payout(103, Decimal("25.00")),
        )

        results = localize(
            _classified(ledger, ops),
            _no_reversals(),
            _timing(((DAY, Decimal("225.00")),)),
            config,
        )

        assert results[0].code is not FindingCode.RKO_OVERSTATED

    def test_paired_payout_is_not_reported_as_unbooked(self, config: Config) -> None:
        """Снятая пара уходит из кандидатов: выдача 80,83 проведена (§5.9.2)."""
        ledger = (
            _refund_posting(1, Decimal("2493.51")),
            _refund_posting(2, Decimal("80.83")),
        )
        ops = (_payout(100, Decimal("80.83")), _payout(101, Decimal("418.20")))

        results = localize(
            _classified(ledger, ops),
            _no_reversals(),
            _timing(((DAY, Decimal("2075.31")),)),
            config,
        )

        assert 100 not in results[0].ops_rows

    def test_rule_does_not_apply_when_payouts_exceed_posting(self, config: Config) -> None:
        """Выдач больше, чем проведено — проводка не завышена (§5.9.3).

        Вопрос не «на сколько завышена проводка», а «какие выдачи не проведены»,
        и отвечать на него нужно перебором с гейтами.
        """
        ledger = (_refund_posting(1, Decimal("100.00")),)
        ops = (_payout(100, Decimal("100.00")), _payout(101, Decimal("50.00")))

        results = localize(
            _classified(ledger, ops),
            _no_reversals(),
            _timing(((DAY, Decimal("-50.00")),)),
            config,
        )

        assert results[0].code is not FindingCode.RKO_OVERSTATED


class TestUnbookedPayouts:
    """§8, §4.3: выдача есть, проводки нет."""

    def test_day_without_postings(self, config: Config) -> None:
        ops = (_payout(100, Decimal("120.00")), _payout(101, Decimal("80.00")))

        results = localize(
            _classified((), ops),
            _no_reversals(),
            _timing(((DAY, Decimal("-200.00")),)),
            config,
        )

        assert results[0].code is FindingCode.PAYOUT_NOT_BOOKED
        assert results[0].ops_rows == (100, 101)

    def test_reversed_day_defers_to_the_reversal_finding(self, config: Config) -> None:
        """§4.3: сторнированная проводка — это не «проводки нет вовсе».

        Ловушка Солигорска: РКО 00231245 на 1 046,75 от 29.06.2023 сторнирован
        01.10.2023 (R7991 ↔ R9106). §5.5 снимает обе строки, день остаётся с
        восемью выдачами и без проводок, и те же рубли попадали в отчёт дважды —
        как ``REVERSAL_WITHOUT_REBOOK`` со влиянием на сальдо и как восемь
        «непроведённых выдач» с нулевым влиянием.
        """
        ledger = (_refund_posting(7991, Decimal("1046.75")),)
        ops = (_payout(100, Decimal("1046.75")),)
        reversals = ReversalResult(
            neutralized_rows=frozenset({7991}),
            findings=(),
            audit_log=(),
        )

        results = localize(
            _classified(ledger, ops),
            reversals,
            _timing(((DAY, Decimal("-1046.75")),)),
            config,
        )

        assert len(results) == 1
        result = results[0]
        assert result.status is LocalizationStatus.EXPLAINED_BY_REVERSAL
        assert result.code is None
        assert result.balance_impact == ZERO
        assert result.ledger_rows == (7991,)

    def test_day_without_any_posting_is_still_unbooked(self, config: Config) -> None:
        """Без сторно тот же день остаётся ``PAYOUT_NOT_BOOKED`` (§8)."""
        ops = (_payout(100, Decimal("1046.75")),)

        results = localize(
            _classified((), ops),
            _no_reversals(),
            _timing(((DAY, Decimal("-1046.75")),)),
            config,
        )

        assert results[0].code is FindingCode.PAYOUT_NOT_BOOKED

    def test_balance_impact_is_zero(self, config: Config) -> None:
        """§4.3: этих проводок в 1С нет вовсе — на сальдо они не влияют."""
        ops = (_payout(100, Decimal("8411.73")),)

        results = localize(
            _classified((), ops),
            _no_reversals(),
            _timing(((DAY, Decimal("-8411.73")),)),
            config,
        )

        assert results[0].amount == Decimal("8411.73")
        assert results[0].balance_impact == ZERO


class TestSalesAggregateBan:
    """§7.4: локализация ниже дневного агрегата продаж запрещена."""

    def test_income_day_is_refused_regardless_of_gates(self, config: Config) -> None:
        """§11.2: касса с 80 чеками в проблемном дне → отказ, а не догадка."""
        ledger = tuple(
            ledger_entry(
                row=row,
                day=DAY,
                debit=Decimal("1000.00"),
                account="90.1.1",
                category=Category.INCOME,
            )
            for row in (1, 2)
        )
        ops = tuple(
            ops_entry(
                row=100 + index,
                moment=datetime(2024, 2, 1, 9, 0, 0),
                amount=Decimal("25.00"),
                kind=ops_entry().kind,
            ).model_copy(update={"classification": OpsClass.INCOME, "classified_by": "block"})
            for index in range(80)
        )
        timing = {
            Category.INCOME: CollapseResult(
                residual=Decimal("0.00"),
                collapsed=0,
                redated=0,
                total=1,
                residual_days=((DAY, Decimal("0.00")),),
                lag=None,
                calendar_aggregations=(),
                audit_log=(),
            ),
        }

        results = localize(_classified(ledger, ops), _no_reversals(), timing, config)

        assert len(results) == 1
        assert results[0].status is LocalizationStatus.REFUSED_BELOW_Z_REPORT
        assert results[0].code is None
        assert "Z-отчёт" in results[0].explanation
        assert results[0].gates is None


class TestMatching:
    """§5.9.2: подокументное сопоставление."""

    def test_greedy_matches_exact_amount_in_window(self, config: Config) -> None:
        ledger = (_refund_posting(1, Decimal("128.42")),)
        ops = (_payout(100, Decimal("999.00")), _payout(101, Decimal("128.42")))

        assert greedy_match(ledger, ops, config) == ((1, 101),)

    def test_greedy_prefers_nearest_date_then_smaller_row(self, config: Config) -> None:
        """§12: полный явный ключ выбора пары."""
        ledger = (_refund_posting(1, Decimal("100.00")),)
        ops = (
            _payout(100, Decimal("100.00"), day=date(2024, 2, 3)),
            _payout(101, Decimal("100.00"), day=DAY),
            _payout(102, Decimal("100.00"), day=DAY),
        )

        assert greedy_match(ledger, ops, config) == ((1, 101),)

    def test_name_similarity_is_zero_for_empty(self) -> None:
        """Вариант C §3.3: имени нет — совпадение не выдумывается."""
        assert name_similarity("", "Иванов") == 0.0
        assert name_similarity("Иванов Иван", "Иванов Иван") == 1.0


def test_findings_never_qualify_as_theft(config: Config) -> None:
    """§1.2, §13.10: инструмент не квалифицирует находку как хищение."""
    ledger = (_refund_posting(987, Decimal("289.31")),)
    ops = (_payout(100, Decimal("128.42")),)

    results = localize(
        _classified(ledger, ops),
        _no_reversals(),
        _timing(((DAY, Decimal("160.89")),)),
        config,
    )

    forbidden = ("фрод", "кража", "виновен", "хищен", "мошенн")
    for result in results:
        assert not any(word in result.explanation.lower() for word in forbidden)
