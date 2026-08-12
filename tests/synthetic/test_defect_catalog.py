"""Каталог дефектов §11.2 — «внедрили → нашли ровно это».

ТЗ §11.2: «Каждый дефект из таксономии §8 должен иметь генератор и тест
"внедрили → нашли ровно это"». Здесь по одному генератору на каждый из
семнадцати кодов §8 плюс обязательные негативные кейсы.

Почему это отдельный файл, а не расширение юнит-тестов
------------------------------------------------------
Юнит-тест проверяет стадию на собранных вручную структурах и не видит сцепки.
Все дефекты, найденные на реальных кассах, жили именно в сцепке: §5.7 и §5.9
смотрели на разные ряды возвратов; сопоставление 1:1 не выполнялось перед
правилом единственной проводки; сторно-пара превращалась в «непроведённые
выдачи»; проводка-агрегат блокировала §5.9.3. Ни один юнит-тест этого не ловил.
Здесь дефект вносится в настоящий `.xlsx` и ищется на выходе всего конвейера.

Каждый тест утверждает **ровно** ожидаемый код: и что он найден, и что чистая
касса его не даёт.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cashforensics.cli import run_pipeline
from cashforensics.models import (
    AnalysisResult,
    Config,
    FindingCode,
    LocalizationStatus,
    Severity,
)
from tests.conftest import OpsRecord, Posting, SheetPlan

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.synthetic

ZERO = Decimal("0.00")
START = date(2024, 2, 1)
SALE = Decimal("1000.00")
DAYS = 6


def _day(offset: int) -> date:
    return START + timedelta(days=offset)


def _at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute, second))


def _sale(day: date, amount: Decimal, index: int) -> Posting:
    return Posting(day, f"Приходный кассовый ордер 1000{index:05d}", "50.2", amount, "90.1.1")


def _collection(day: date, amount: Decimal, index: int) -> Posting:
    return Posting(day, f"Расходный кассовый ордер 2000{index:05d}", "51", None, "50.2", amount)


def _refund(day: date, amount: Decimal, index: int) -> Posting:
    return Posting(day, f"Расходный кассовый ордер 3000{index:05d}", "76.9.1", None, "50.2", amount)


def _clean() -> SheetPlan:
    """Чистая касса: приход = инкассация каждый день, сальдо 0, находок нет.

    База для всех генераторов: дефект вносится поверх неё, поэтому любое
    отклонение в результате принадлежит именно внесённому дефекту.
    """
    days = [_day(offset) for offset in range(DAYS)]
    postings = [_sale(day, SALE, index) for index, day in enumerate(days, start=1)]
    postings += [_collection(day, SALE, index) for index, day in enumerate(days, start=1)]
    return SheetPlan(
        variant="A",
        postings=postings,
        pko=[OpsRecord(_at(day, 12), SALE, "Клиент") for day in days],
        rko=[OpsRecord(_at(day, 18), SALE, "Центральная касса") for day in days],
        closing=ZERO,
    )


def _codes(result: AnalysisResult) -> set[FindingCode]:
    return {finding.code for finding in result.findings}


def _finding(result: AnalysisResult, code: FindingCode) -> object:
    matched = [item for item in result.findings if item.code is code]
    assert matched, f"{code.value} не найден; найдено: {sorted(c.value for c in _codes(result))}"
    return matched[0]


class TestCleanRegister:
    """§11.2, обязательный негативный кейс: чистая касса без дефектов."""

    def test_no_errors_and_balance_ties(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        result = run_pipeline(make_workbook(_clean()), config)

        assert result.waterfall.closing == result.waterfall.target
        assert result.unresolved == ZERO
        assert [f.code for f in result.findings if f.severity is Severity.ERROR] == []


class TestRefundDiscrepancies:
    """Коды §5.9: расхождение между проводкой возврата и выдачей в логе."""

    def test_rko_overstated(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Эталон §5.9.3: в 1С 289,31, в логе одна выдача 128,42 → 160,89."""
        plan = _clean()
        plan.postings.append(_refund(_day(3), Decimal("289.31"), 1))
        plan.rko.append(OpsRecord(_at(_day(3), 14), Decimal("128.42"), "Иванов Иван"))
        plan.closing = Decimal("-289.31")
        plan.closing_side = "К"

        result = run_pipeline(make_workbook(plan), config)

        finding = _finding(result, FindingCode.RKO_OVERSTATED)
        assert finding.amount == Decimal("160.89")  # type: ignore[attr-defined]
        # Возврат идёт в кредит 50.2: лишний проведённый рубль уносит рубль из
        # сальдо, поэтому вклад отрицателен (§4.3, §5.10). На Витебске всё
        # отклонение −160,89 объясняется этой одной строкой.
        assert finding.balance_impact == Decimal("-160.89")  # type: ignore[attr-defined]

    def test_rko_without_payout(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Проводка возврата есть, выдачи в логе нет вовсе (§8)."""
        plan = _clean()
        plan.postings.append(_refund(_day(3), Decimal("214.00"), 1))
        plan.closing = Decimal("-214.00")
        plan.closing_side = "К"

        result = run_pipeline(make_workbook(plan), config)

        finding = _finding(result, FindingCode.RKO_WITHOUT_PAYOUT)
        assert finding.amount == Decimal("214.00")  # type: ignore[attr-defined]

    def test_payout_not_booked(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§4.3: выдача есть, проводки нет — на сальдо не влияет."""
        plan = _clean()
        plan.rko.append(OpsRecord(_at(_day(3), 14), Decimal("77.40"), "Иванов Иван"))

        result = run_pipeline(make_workbook(plan), config)

        finding = _finding(result, FindingCode.PAYOUT_NOT_BOOKED)
        assert finding.amount == Decimal("77.40")  # type: ignore[attr-defined]
        assert finding.balance_impact == ZERO  # type: ignore[attr-defined]


class TestReversals:
    """Коды §5.5: сторно."""

    def _storno(self, plan: SheetPlan, amount: Decimal, *, rebooked: bool) -> SheetPlan:
        plan.postings.append(_refund(_day(2), amount, 1))
        plan.postings.append(
            Posting(
                _day(4), "Корректировка записей регистров 999", "76.9.1", None, "50.2", -amount
            ),
        )
        if rebooked:
            plan.rko.append(OpsRecord(_at(_day(2), 14), amount, "Иванов Иван"))
        return plan

    def test_reversal_pair_is_neutralized(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Пара «проводка + сторно» гасится и остаётся информационной строкой."""
        plan = self._storno(_clean(), Decimal("310.00"), rebooked=False)

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.REVERSAL_PAIR in _codes(result)
        finding = _finding(result, FindingCode.REVERSAL_PAIR)
        assert finding.severity is Severity.INFO  # type: ignore[attr-defined]

    def test_reversal_without_rebook(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Сторно снято, выдача была, перепроведения нет — влияет на сальдо."""
        plan = self._storno(_clean(), Decimal("310.00"), rebooked=True)

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.REVERSAL_WITHOUT_REBOOK in _codes(result)

    def test_reversed_day_is_not_reported_as_unbooked(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Ловушка 29.06.2023 Солигорска: те же рубли не называются дважды."""
        plan = self._storno(_clean(), Decimal("310.00"), rebooked=True)

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.PAYOUT_NOT_BOOKED not in _codes(result)
        explained = [
            item
            for item in result.localizations
            if item.status is LocalizationStatus.EXPLAINED_BY_REVERSAL
        ]
        assert explained

    def test_reversal_unmatched(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Сторно без найденной пары — §5.5, отдельный код."""
        plan = _clean()
        plan.postings.append(
            Posting(
                _day(4),
                "Корректировка записей регистров 999",
                "76.9.1",
                None,
                "50.2",
                Decimal("-99.00"),
            ),
        )
        plan.closing = Decimal("99.00")

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.REVERSAL_UNMATCHED in _codes(result)


class TestLogLevelDefects:
    """Коды, относящиеся к выгрузке целиком."""

    def test_service_misclassified(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§3.6: судебная выплата в блоке РКО — мнимое расхождение, не возврат."""
        plan = _clean()
        plan.rko.append(OpsRecord(_at(_day(3), 15), Decimal("11310.00"), "СУД г. Солигорска"))

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.SERVICE_MISCLASSIFIED in _codes(result)
        # Служебная выдача не должна превратиться в «непроведённую выдачу» (§3.6).
        assert FindingCode.PAYOUT_NOT_BOOKED not in _codes(result)

    def test_log_imbalance(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§5.10: ПКО минус все РКО не сходится — измеряется, но не объясняется."""
        plan = _clean()
        plan.pko.append(OpsRecord(_at(_day(2), 13), Decimal("500.00"), "Клиент"))

        result = run_pipeline(make_workbook(plan), config)

        finding = _finding(result, FindingCode.LOG_IMBALANCE)
        assert finding.severity is Severity.INFO  # type: ignore[attr-defined]

    def test_unknown_account(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§5.4: счёт вне справочника не поглощается молча."""
        plan = _clean()
        plan.postings.append(
            Posting(_day(3), "Расходный кассовый ордер 4000001", "99.9", None, "50.2", ZERO),
        )

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.UNKNOWN_ACCOUNT in _codes(result)

    def test_period_cutoff(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§5.3, V6: записи лога позже последней проводки 1С — признак среза."""
        plan = _clean()
        plan.pko.append(OpsRecord(_at(_day(DAYS + 2), 12), SALE, "Клиент"))

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.PERIOD_CUTOFF in _codes(result)


class TestSignatures:
    """Коды §8.1–8.2: сигнатуры, которые сверка не ловит."""

    def test_repeat_payout(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Эталон §8.1: четыре выдачи по 164,99 одному получателю за 22 секунды."""
        plan = _clean()
        base = _at(_day(3), 13, 26, 55)
        plan.rko += [
            OpsRecord(base + timedelta(seconds=shift), Decimal("164.99"), "Правосуд Дмитрий")
            for shift in (0, 7, 14, 22)
        ]

        result = run_pipeline(make_workbook(plan), config)

        finding = _finding(result, FindingCode.REPEAT_PAYOUT)
        assert finding.amount == Decimal("659.96")  # type: ignore[attr-defined]
        assert finding.balance_impact == ZERO  # type: ignore[attr-defined]
        assert "может быть законным" in finding.explanation  # type: ignore[attr-defined]

    def test_late_time_doc(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§8: запись в 23:59:59 — метка автоматического закрытия смены."""
        plan = _clean()
        plan.rko.append(OpsRecord(_at(_day(3), 23, 59, 59), Decimal("41.20"), "Иванов Иван"))

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.LATE_TIME_DOC in _codes(result)

    def test_shift_rounding(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§8: круглая сумма ниже ROUND_MAX — округление смены, severity НОРМА."""
        plan = _clean()
        plan.postings.append(_sale(_day(3), Decimal("50.00"), 90))
        plan.closing = Decimal("50.00")

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.SHIFT_ROUNDING in _codes(result)

    def test_sequence_gap(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§8.2: плотный ряд номеров с пропуском."""
        plan = _clean()
        # Ряд 3000001..3000005 без 3000003 — плотность выше 0,5, пропуск виден.
        for index, offset in enumerate((1, 2, 4, 5), start=0):
            plan.postings.append(
                Posting(
                    _day(index),
                    f"Расходный кассовый ордер 300000{offset}",
                    "76.9.1",
                    None,
                    "50.2",
                    ZERO,
                ),
            )

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.SEQUENCE_GAP in _codes(result)

    def test_pko_double_booked(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§8: две проводки одной суммы, один день, один счёт, разные номера."""
        plan = _clean()
        plan.postings.append(_sale(_day(3), Decimal("640.00"), 91))
        plan.postings.append(_sale(_day(3), Decimal("640.00"), 92))
        plan.closing = Decimal("1280.00")

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.PKO_DOUBLE_BOOKED in _codes(result)

    def test_duplicate_doc(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§8: тот же номер документа дважды за один день — дубликат выгрузки.

        Отличать от ``PKO_DOUBLE_BOOKED`` обязательно: у §8 разные severity и
        разное влияние на сальдо. Признак задвоения — **разные** номера.
        """
        plan = _clean()
        plan.postings.append(_sale(_day(3), Decimal("640.00"), 93))
        plan.postings.append(_sale(_day(3), Decimal("640.00"), 93))
        plan.closing = Decimal("1280.00")

        result = run_pipeline(make_workbook(plan), config)

        assert FindingCode.DUPLICATE_DOC in _codes(result)
        assert FindingCode.PKO_DOUBLE_BOOKED not in _codes(result)


class TestPostingDelay:
    """§8 ``POSTING_DELAY`` — выдача и её проводка разнесены за пределы LONG_WIN."""

    def test_late_booking_is_linked(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """Форма 01.10.2023 Солигорска: выдача в апреле, проводка в октябре.

        Изолированную пару «выдача −X, проводка +X» гасит проход 1 §5.7.2:
        накопитель возвращается к нулю, и весь сегмент считается погашенным.
        Это верное поведение — расхождения за период нет. Находка нужна там, где
        накопитель к нулю не возвращается, поэтому в кассу добавлено постоянное
        расхождение 500,00 без выдачи: ровно так пара и выживает на Солигорске.
        """
        amount = Decimal("38.27")
        noise = Decimal("500.00")
        days = [_day(offset) for offset in range(DAYS)]
        late = _day(120)
        postings = [_sale(day, SALE, index) for index, day in enumerate(days, start=1)]
        postings += [_collection(day, SALE, index) for index, day in enumerate(days, start=1)]
        postings.append(_refund(_day(0), noise, 9))
        postings.append(_refund(late, amount, 1))
        plan = SheetPlan(
            variant="A",
            postings=postings,
            pko=[OpsRecord(_at(day, 12), SALE, "Клиент") for day in days],
            rko=[
                *(OpsRecord(_at(day, 18), SALE, "Центральная касса") for day in days),
                OpsRecord(_at(_day(1), 14), amount, "Иванов Иван"),
            ],
            closing=-(amount + noise),
            closing_side="К",
        )

        result = run_pipeline(make_workbook(plan), config)

        finding = _finding(result, FindingCode.POSTING_DELAY)
        assert finding.amount == amount  # type: ignore[attr-defined]
        assert finding.balance_impact == ZERO  # type: ignore[attr-defined]
        assert finding.date == (_day(1), late)  # type: ignore[attr-defined]


class TestSalesAggregateBan:
    """§11.2, обязательный негативный кейс: день с десятками чеков."""

    def test_eighty_receipts_are_refused_not_guessed(
        self,
        make_workbook: Callable[[SheetPlan], Path],
        config: Config,
    ) -> None:
        """§7.4: ниже дневного агрегата продаж локализация запрещена."""
        plan = _clean()
        problem = _day(2)
        plan.pko += [
            OpsRecord(
                _at(problem, 9) + timedelta(minutes=index), Decimal("10.00"), f"Клиент {index}"
            )
            for index in range(80)
        ]

        result = run_pipeline(make_workbook(plan), config)

        refused = [
            item
            for item in result.localizations
            if item.status is LocalizationStatus.REFUSED_BELOW_Z_REPORT
        ]
        assert refused
        assert all(item.code is None for item in refused)
        assert any("Z-отчёт" in item.explanation for item in refused)
