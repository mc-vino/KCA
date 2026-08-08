"""Юнит-тесты стадии RANK — §5.11, материальность §7.5, confidence §7.6.

Ловушки, закреплённые здесь (§11.1):

* агрегация мелочи §5.11 не понижает уровень находки: порог тривиального на
  Солигорске (2 812,74) выше всего отклонения сальдо (1 224,80), и наивная
  свёртка прятала двенадцать ``RKO_OVERSTATED`` под строкой «НОРМА»;
* находка без денежной величины (``SEQUENCE_GAP``) не сворачивается: нулевая
  сумма формально ниже любого порога, но это не «мелкое расхождение»;
* локализация с отказом (``code is None``) находкой §8 не становится.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from cashforensics.models import (
    Category,
    CategoryRecon,
    ClassifyResult,
    Config,
    Finding,
    FindingCode,
    LocalizationResult,
    LocalizationStatus,
    Materiality,
    PostingMode,
    Severity,
    Signature,
    ValidationReport,
    Waterfall,
)
from cashforensics.rank import (
    CODE_SEVERITY,
    CONFIDENCE_LOCALIZED,
    CONFIDENCE_PROBABLE,
    CONFIDENCE_SIGNATURE,
    aggregate_trivial,
    classify_materiality,
    collect_findings,
    confidence_label,
    confidence_score,
    finding_materiality,
    materiality_thresholds,
    rank_findings,
    sort_key,
)
from tests.unit.test_classify import ledger_entry

pytestmark = pytest.mark.unit

ZERO = Decimal("0.00")
DAY = date(2024, 2, 1)
PERIOD = (date(2024, 1, 1), date(2024, 12, 31))
BENCHMARK = Decimal("1000000.00")


def _finding(
    *,
    code: FindingCode = FindingCode.RKO_OVERSTATED,
    severity: Severity = Severity.ERROR,
    amount: str = "100.00",
    impact: str = "100.00",
    confidence: float = 1.0,
    day: date = DAY,
) -> Finding:
    return Finding(
        code=code,
        severity=severity,
        date=day,
        amount=Decimal(amount),
        title="тест",
        explanation="тест",
        confidence=confidence,
        materiality=Materiality.MATERIAL,
        balance_impact=Decimal(impact),
    )


def _localization(
    *,
    code: FindingCode | None,
    status: LocalizationStatus = LocalizationStatus.LOCALIZED,
    amount: str = "160.89",
) -> LocalizationResult:
    return LocalizationResult(
        date=DAY,
        category=Category.REFUND,
        mode=PostingMode.PER_DOCUMENT,
        status=status,
        code=code,
        amount=Decimal(amount),
        balance_impact=Decimal(amount),
        ledger_rows=(987,),
        ops_rows=(),
        doc_numbers=("00000257506",),
        gates=None,
        confidence=1.0,
        explanation="тест",
    )


def _signature(*, code: FindingCode, amount: str | None, day: date | None = DAY) -> Signature:
    return Signature(
        code=code,
        title="тест",
        date=day,
        amount=Decimal(amount) if amount is not None else None,
        rows=(1, 2),
        baseline="базовая частота",
        explanation="тест",
    )


def _waterfall(*, log_imbalance: str = "0.00") -> Waterfall:
    return Waterfall(
        closing=Decimal("-1224.80"),
        target=ZERO,
        income_delta=ZERO,
        collection_delta=ZERO,
        refund_delta=ZERO,
        other_delta=ZERO,
        log_imbalance=Decimal(log_imbalance),
        unresolved=ZERO,
        causal_lines=(),
    )


def _validation(*, cutoff: bool = False) -> ValidationReport:
    return ValidationReport(
        checks=(),
        hard_failed=False,
        daily_reconciliation_enabled=True,
        unknown_accounts=(),
        cutoff_suspected=cutoff,
    )


def _classified(*, unknown: tuple[str, ...] = ()) -> ClassifyResult:
    return ClassifyResult(ledger=(), ops=(), fallback=None, unknown_accounts=unknown)


def _recon(*, collection_net: str = "0.00") -> dict[Category, CategoryRecon]:
    """Минимальная сверка §5.6: нужна только величина среза периода."""
    return {
        Category.COLLECTION: CategoryRecon(
            category=Category.COLLECTION,
            acc_total=ZERO,
            ops_total=ZERO,
            net=Decimal(collection_net),
            gross=ZERO,
            ratio=None,
            days_with_difference=0,
            acc_series=(),
            ops_series=(),
            daily_differences=(),
            adjusted_net=None,
            adjusted_gross=None,
        ),
    }


class TestMateriality:
    """§7.5 — пороги от бенчмарка."""

    def test_thresholds_derive_from_the_benchmark(self, config: Config) -> None:
        thresholds = materiality_thresholds(BENCHMARK, config)
        assert thresholds.overall == BENCHMARK * Decimal("0.005")
        assert thresholds.performance == thresholds.overall * Decimal("0.60")
        assert thresholds.trivial == thresholds.overall * Decimal("0.04")

    def test_three_bands(self, config: Config) -> None:
        thresholds = materiality_thresholds(BENCHMARK, config)
        assert classify_materiality(Decimal("1.00"), thresholds) is Materiality.TRIVIAL
        assert classify_materiality(Decimal("1000.00"), thresholds) is Materiality.IMMATERIAL
        assert classify_materiality(Decimal("9000.00"), thresholds) is Materiality.MATERIAL

    def test_sign_does_not_change_the_band(self, config: Config) -> None:
        thresholds = materiality_thresholds(BENCHMARK, config)
        assert classify_materiality(Decimal("-9000.00"), thresholds) is Materiality.MATERIAL

    def test_finding_without_money_is_never_trivial(self, config: Config) -> None:
        """``SEQUENCE_GAP`` не имеет суммы — сворачивать его в «мелочь» нельзя."""
        thresholds = materiality_thresholds(BENCHMARK, config)
        assert finding_materiality(ZERO, ZERO, thresholds) is Materiality.IMMATERIAL


class TestConfidence:
    """§7.6 — оценка и её словесная интерпретация."""

    def test_perfect_signals_give_one(self) -> None:
        assert confidence_score(1.0, 0.0, 1.0, 4) == pytest.approx(1.0)

    def test_score_is_clamped(self) -> None:
        assert confidence_score(1.0, 0.0, 1.0, 100) <= 1.0
        assert confidence_score(0.0, 1.0, 0.0, 0) >= 0.0

    def test_labels_follow_the_thresholds(self) -> None:
        assert confidence_label(CONFIDENCE_LOCALIZED) == "локализовано"
        assert confidence_label(CONFIDENCE_PROBABLE) == "вероятно"
        assert confidence_label(0.1) == "требует ручной проверки"

    def test_signature_confidence_reads_as_manual_check(self) -> None:
        """§8.1: сигнатура «требует точечной проверки», а не «локализовано»."""
        assert confidence_label(CONFIDENCE_SIGNATURE) == "требует ручной проверки"


class TestSortKey:
    """§5.11 — ``severity → materiality → |balance_impact| → confidence → дата``."""

    def test_errors_come_first(self) -> None:
        error = _finding(severity=Severity.ERROR)
        review = _finding(severity=Severity.REVIEW)
        assert min([review, error], key=sort_key) is error

    def test_bigger_impact_comes_first_within_a_band(self) -> None:
        small = _finding(impact="10.00")
        big = _finding(impact="500.00")
        assert min([small, big], key=sort_key) is big

    def test_key_is_total_and_deterministic(self) -> None:
        """§13.5: два одинаковых по пяти признакам разводятся кодом."""
        first = _finding(code=FindingCode.RKO_OVERSTATED)
        second = _finding(code=FindingCode.PKO_DOUBLE_BOOKED)
        assert sort_key(first) != sort_key(second)


class TestAggregateTrivial:
    """§5.11 — свёртка мелочи, но не переклассификация."""

    def test_two_trivial_normals_are_folded(self, config: Config) -> None:
        thresholds = materiality_thresholds(BENCHMARK, config)
        findings = [
            _finding(
                code=FindingCode.SHIFT_ROUNDING,
                severity=Severity.NORMAL,
                amount="10.00",
                impact="10.00",
            ),
            _finding(
                code=FindingCode.SHIFT_ROUNDING,
                severity=Severity.NORMAL,
                amount="20.00",
                impact="20.00",
            ),
        ]
        scored = [item.model_copy(update={"materiality": Materiality.TRIVIAL}) for item in findings]
        result = aggregate_trivial(scored, thresholds)
        assert len(result) == 1
        assert result[0].title == "Мелкие расхождения, 2 шт."
        assert result[0].balance_impact == Decimal("30.00")

    def test_errors_are_never_folded_into_a_normal_row(self, config: Config) -> None:
        """Ловушка Солигорска: порог тривиального выше всего отклонения сальдо."""
        thresholds = materiality_thresholds(BENCHMARK, config)
        findings = [
            _finding(severity=Severity.ERROR, amount="1148.88", impact="1148.88"),
            _finding(severity=Severity.ERROR, amount="1039.44", impact="1039.44"),
        ]
        scored = [item.model_copy(update={"materiality": Materiality.TRIVIAL}) for item in findings]
        result = aggregate_trivial(scored, thresholds)
        assert len(result) == 2
        assert all(item.severity is Severity.ERROR for item in result)

    def test_single_trivial_is_not_folded(self, config: Config) -> None:
        thresholds = materiality_thresholds(BENCHMARK, config)
        one = [
            _finding(
                code=FindingCode.SHIFT_ROUNDING,
                severity=Severity.NORMAL,
            ).model_copy(update={"materiality": Materiality.TRIVIAL}),
        ]
        assert aggregate_trivial(one, thresholds) == tuple(one)

    def test_folded_row_keeps_the_trace(self, config: Config) -> None:
        """§12: свёртка не имеет права терять номера строк."""
        thresholds = materiality_thresholds(BENCHMARK, config)
        findings = [
            _finding(
                code=FindingCode.SHIFT_ROUNDING,
                severity=Severity.NORMAL,
            ).model_copy(update={"materiality": Materiality.TRIVIAL, "ledger_rows": [row]})
            for row in (7991, 9106)
        ]
        result = aggregate_trivial(findings, thresholds)
        assert result[0].ledger_rows == [7991, 9106]


class TestCollectFindings:
    """Сборка таксономии §8 из всех источников конвейера."""

    def test_localization_becomes_a_finding_with_the_taxonomy_severity(
        self,
        config: Config,
    ) -> None:
        findings = collect_findings(
            (),
            [_localization(code=FindingCode.RKO_OVERSTATED)],
            (),
            _classified(),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )
        assert len(findings) == 1
        assert findings[0].code is FindingCode.RKO_OVERSTATED
        assert findings[0].severity is CODE_SEVERITY[FindingCode.RKO_OVERSTATED]
        assert findings[0].ledger_rows == [987]
        assert findings[0].doc_numbers == ["00000257506"]

    def test_refused_localization_is_not_a_finding(self, config: Config) -> None:
        """§7.3: у отказа нет кода §8 — предъявлять его находкой нельзя."""
        refused = _localization(
            code=None,
            status=LocalizationStatus.REFUSED_BELOW_Z_REPORT,
        )
        findings = collect_findings(
            (),
            [refused],
            (),
            _classified(),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )
        assert findings == ()

    def test_dateless_signature_takes_the_period(self, config: Config) -> None:
        findings = collect_findings(
            (),
            (),
            [_signature(code=FindingCode.SEQUENCE_GAP, amount=None, day=None)],
            _classified(),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )
        assert findings[0].date == PERIOD
        assert findings[0].balance_impact == ZERO

    def test_repeat_signature_does_not_touch_the_balance(self, config: Config) -> None:
        """§8: 1С провела агрегат, поэтому повтор на сальдо не влияет."""
        findings = collect_findings(
            (),
            (),
            [_signature(code=FindingCode.REPEAT_PAYOUT, amount="659.96")],
            _classified(),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )
        assert findings[0].amount == Decimal("659.96")
        assert findings[0].balance_impact == ZERO

    def test_signature_baseline_reaches_the_explanation(self, config: Config) -> None:
        """§8.1: базовая частота обязана быть в тексте находки, не только сигнатуры."""
        findings = collect_findings(
            (),
            (),
            [_signature(code=FindingCode.REPEAT_PAYOUT, amount="659.96")],
            _classified(),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )
        assert "базовая частота" in findings[0].explanation

    def test_unknown_account_is_not_swallowed(self, config: Config) -> None:
        """§5.4: счёт вне справочника даёт отдельную находку."""
        findings = collect_findings(
            (),
            (),
            (),
            _classified(unknown=("76.6",)),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )
        assert [item.code for item in findings] == [FindingCode.UNKNOWN_ACCOUNT]

    def test_log_imbalance_becomes_an_informational_finding(self, config: Config) -> None:
        findings = collect_findings(
            (),
            (),
            (),
            _classified(),
            _validation(),
            _waterfall(log_imbalance="-807.91"),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )
        assert findings[0].code is FindingCode.LOG_IMBALANCE
        assert findings[0].severity is Severity.INFO
        assert findings[0].balance_impact == Decimal("-807.91")

    def test_zero_log_imbalance_is_silent(self, config: Config) -> None:
        findings = collect_findings(
            (),
            (),
            (),
            _classified(),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )
        assert findings == ()

    def test_cutoff_carries_the_unbooked_collection(self, config: Config) -> None:
        """§8: срез периода влияет на сальдо — величина равна непроведённой инкассации.

        Эталон §5.10 для PAX_119023531 приводит эту строку как «+772,71
        инкассация не проведена (срез периода)». Пока находка несла нулевое
        влияние, строка в раскладке не появлялась вовсе.
        """
        findings = collect_findings(
            (),
            (),
            (),
            _classified(),
            _validation(cutoff=True),
            _waterfall(),
            _recon(collection_net="-772.71"),
            PERIOD,
            BENCHMARK,
            config,
        )
        assert findings[0].code is FindingCode.PERIOD_CUTOFF
        assert findings[0].balance_impact == Decimal("772.71")

    def test_late_booking_becomes_posting_delay(self, config: Config) -> None:
        """§8 ``POSTING_DELAY``: выдача и её проводка разнесены на месяцы.

        Ловушка Солигорска: выдача 38,27 от 09.04.2023 проведена РКО 00289603
        только 01.10.2023. Свёртка §5.7.2 пару не видит — перенос даты ограничен
        31 днём, — и одни и те же рубли попадают в отчёт дважды.
        """
        paid = date(2023, 4, 9)
        booked = date(2023, 10, 1)
        posting = ledger_entry(
            row=9109,
            day=booked,
            credit=Decimal("38.27"),
            account="62.10.1",
            category=Category.REFUND,
            doc="Расходный кассовый ордер 00289603 от 01.10.2023 23:59:59",
            number="00289603",
        )
        unbooked = _localization(
            code=FindingCode.PAYOUT_NOT_BOOKED,
            amount="38.27",
        ).model_copy(update={"date": paid, "ledger_rows": (), "ops_rows": (2231,)})
        late = _localization(
            code=FindingCode.RKO_WITHOUT_PAYOUT,
            amount="38.27",
        ).model_copy(update={"date": booked, "ledger_rows": (9109,)})

        findings = collect_findings(
            (),
            [unbooked, late],
            (),
            ClassifyResult(
                ledger=(posting,),
                ops=(),
                fallback=None,
                unknown_accounts=(),
            ),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )

        delay = next(item for item in findings if item.code is FindingCode.POSTING_DELAY)
        assert delay.date == (paid, booked)
        assert delay.amount == Decimal("38.27")
        assert delay.balance_impact == ZERO
        assert delay.ledger_rows == [9109]
        assert delay.ops_rows == [2231]
        assert delay.doc_numbers == ["00289603"]
        assert "175 дней" in delay.explanation
        assert "23:59:59" in delay.explanation

    def test_earlier_posting_is_not_a_delay(self, config: Config) -> None:
        """Проводка раньше выдачи — не задержка, а другая операция."""
        unbooked = _localization(code=FindingCode.PAYOUT_NOT_BOOKED, amount="38.27").model_copy(
            update={"date": date(2023, 10, 1)},
        )
        early = _localization(code=FindingCode.RKO_WITHOUT_PAYOUT, amount="38.27").model_copy(
            update={"date": date(2023, 4, 9), "ledger_rows": (100,)},
        )
        posting = ledger_entry(
            row=100,
            day=date(2023, 4, 9),
            credit=Decimal("38.27"),
            category=Category.REFUND,
        )

        findings = collect_findings(
            (),
            [unbooked, early],
            (),
            ClassifyResult(ledger=(posting,), ops=(), fallback=None, unknown_accounts=()),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )

        assert all(item.code is not FindingCode.POSTING_DELAY for item in findings)

    def test_one_posting_serves_one_payout(self, config: Config) -> None:
        """Проводка расходуется один раз: две выдачи одной суммы — одна пара."""
        posting = ledger_entry(
            row=9109,
            day=date(2023, 10, 1),
            credit=Decimal("38.27"),
            category=Category.REFUND,
        )
        first = _localization(code=FindingCode.PAYOUT_NOT_BOOKED, amount="38.27").model_copy(
            update={"date": date(2023, 4, 9), "ops_rows": (1,)},
        )
        second = _localization(code=FindingCode.PAYOUT_NOT_BOOKED, amount="38.27").model_copy(
            update={"date": date(2023, 5, 9), "ops_rows": (2,)},
        )
        late = _localization(code=FindingCode.RKO_WITHOUT_PAYOUT, amount="38.27").model_copy(
            update={"date": date(2023, 10, 1), "ledger_rows": (9109,)},
        )

        findings = collect_findings(
            (),
            [first, second, late],
            (),
            ClassifyResult(ledger=(posting,), ops=(), fallback=None, unknown_accounts=()),
            _validation(),
            _waterfall(),
            _recon(),
            PERIOD,
            BENCHMARK,
            config,
        )

        delays = [item for item in findings if item.code is FindingCode.POSTING_DELAY]
        assert len(delays) == 1
        assert delays[0].ops_rows == [1]

    def test_empty_ledger_keeps_only_reversal_findings(self, config: Config) -> None:
        """Без периода датировать находки уровня выгрузки нечем."""
        reversal = _finding(code=FindingCode.REVERSAL_PAIR, severity=Severity.INFO)
        findings = collect_findings(
            (reversal,),
            (),
            (),
            _classified(unknown=("76.6",)),
            _validation(cutoff=True),
            _waterfall(log_imbalance="-807.91"),
            _recon(),
            None,
            BENCHMARK,
            config,
        )
        assert findings == (reversal,)


class TestRankFindings:
    """Стадия целиком — §5.11."""

    def test_result_is_sorted_by_the_full_key(self, config: Config) -> None:
        findings = [
            _finding(severity=Severity.REVIEW, impact="10.00"),
            _finding(severity=Severity.ERROR, impact="9000.00"),
        ]
        ranked = rank_findings(findings, BENCHMARK, config)
        assert ranked[0].severity is Severity.ERROR

    def test_ranking_is_stable_between_runs(self, config: Config) -> None:
        """§13.5: тот же вход — тот же порядок."""
        findings = [
            _finding(code=code, day=DAY)
            for code in (
                FindingCode.RKO_OVERSTATED,
                FindingCode.PKO_DOUBLE_BOOKED,
                FindingCode.RKO_WITHOUT_PAYOUT,
            )
        ]
        first = [item.code for item in rank_findings(findings, BENCHMARK, config)]
        second = [item.code for item in rank_findings(list(reversed(findings)), BENCHMARK, config)]
        assert first == second

    def test_materiality_is_assigned_by_the_stage(self, config: Config) -> None:
        """До RANK материальность невычислима: нужен оборот периода."""
        ranked = rank_findings([_finding(amount="1.00", impact="1.00")], BENCHMARK, config)
        assert ranked[0].materiality is Materiality.TRIVIAL
