"""Юнит-тесты стадии CLASSIFY — §5.4, справочники §3.5 и §3.6."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from cashforensics.classify import (
    BlockClassificationFailed,
    classify,
    classify_ledger_entry,
    classify_ops_entry,
    is_central_cash,
    is_service_recipient,
    needs_time_fallback,
    service_total,
    unknown_accounts,
    verify_time_fallback,
)
from cashforensics.models import (
    Category,
    Config,
    DocType,
    LedgerEntry,
    LedgerTotals,
    NormalizeResult,
    OpsClass,
    OpsEntry,
    OpsKind,
)

pytestmark = pytest.mark.unit

ZERO = Decimal("0.00")


def ledger_entry(
    *,
    row: int = 1,
    day: date = date(2024, 2, 1),
    debit: Decimal = ZERO,
    credit: Decimal = ZERO,
    account: str = "90.1.1",
    category: Category = Category.OTHER,
    doc: str = "Документ 000123456",
    number: str = "000123456",
    doc_type: DocType = DocType.PKO,
    is_reversal: bool = False,
) -> LedgerEntry:
    """Проводка 1С для теста — §4.1."""
    return LedgerEntry(
        row=row,
        date=day,
        debit=debit,
        credit=credit,
        counter_account=account,
        category=category,
        doc_text=doc,
        doc_number=number,
        doc_type=doc_type,
        is_reversal=is_reversal,
    )


def ops_entry(
    *,
    row: int = 1,
    moment: datetime = datetime(2024, 2, 1, 10, 0, 0),
    amount: Decimal = Decimal("100.00"),
    counterparty: str = "",
    kind: OpsKind = OpsKind.RKO,
) -> OpsEntry:
    """Запись опер-лога для теста — §4.2."""
    return OpsEntry(
        row=row,
        dt=moment,
        amount=amount,
        counterparty=counterparty,
        kind=kind,
        classification=OpsClass.REFUND,
        classified_by="",
    )


class TestServiceRecipients:
    """§3.6: якорь ``^`` обязателен."""

    def test_pravosud_is_not_service(self, config: Config) -> None:
        """Регресс на ловушку §3.6.

        Первая версия регулярки была ``/суд |^суд|архив|финконтрол/i`` и
        отбросила выдачу клиенту «Правосуд Дмитрий» (203,93), потому что строка
        содержит «суд ».
        """
        assert not is_service_recipient("Правосуд Дмитрий", config.patterns.service_recipients)

    @pytest.mark.parametrize(
        "recipient",
        ["СУД Минского района", "суд г. Солигорска", "АРХИВ ПВЗ", "Финконтроль"],
    )
    def test_real_service_recipients_detected(self, recipient: str, config: Config) -> None:
        assert is_service_recipient(recipient, config.patterns.service_recipients)

    @pytest.mark.parametrize(
        "recipient",
        ["Правосудов Игорь", "Судакова Мария", "Рассудов Пётр", ""],
    )
    def test_clients_whose_names_contain_sud(self, recipient: str, config: Config) -> None:
        """Фамилии с «суд» внутри — обычные клиенты, а не служебные записи."""
        assert not is_service_recipient(recipient, config.patterns.service_recipients)

    def test_central_cash_detected_case_insensitively(self, config: Config) -> None:
        assert is_central_cash("ЦЕНТРАЛЬНАЯ КАССА", config.patterns.central_cash)
        assert is_central_cash("Центральная касса №1", config.patterns.central_cash)
        assert not is_central_cash("Иванов Иван", config.patterns.central_cash)


class TestLedgerCategories:
    """§5.4: приход = только продажи + авансы."""

    @pytest.mark.parametrize(
        ("account", "expected"),
        [("90.1.1", Category.INCOME), ("62.4.1", Category.INCOME)],
    )
    def test_debit_on_sales_is_income(
        self,
        account: str,
        expected: Category,
        config: Config,
    ) -> None:
        assert classify_ledger_entry(account, is_debit=True, config=config) == expected

    @pytest.mark.parametrize("account", ["76.9.1", "76.6"])
    def test_debit_on_refund_accounts_is_other_not_income(
        self,
        account: str,
        config: Config,
    ) -> None:
        """Регресс на ловушку §5.4.

        На Кассе 3 включение дебета 76.9.1 в приход давало 579 868,96 вместо
        корректных 579 749,96 и ломало сходимость раскладки.
        """
        result = classify_ledger_entry(account, is_debit=True, config=config)

        assert result is Category.OTHER

    def test_credit_on_refund_account_is_refund(self, config: Config) -> None:
        assert classify_ledger_entry("76.9.1", is_debit=False, config=config) is Category.REFUND

    @pytest.mark.parametrize("account", ["51", "57.1.1"])
    def test_collection_accounts(self, account: str, config: Config) -> None:
        assert classify_ledger_entry(account, is_debit=False, config=config) is Category.COLLECTION

    def test_exchange_account(self, config: Config) -> None:
        assert classify_ledger_entry("50.1", is_debit=False, config=config) is Category.EXCHANGE

    def test_unknown_account_falls_to_other(self, config: Config) -> None:
        assert classify_ledger_entry("99.9.9", is_debit=True, config=config) is Category.OTHER

    def test_unknown_accounts_are_listed_not_swallowed(self, config: Config) -> None:
        """§3.5: молчаливое поглощение неизвестного счёта запрещено."""
        ledger = (
            ledger_entry(row=1, account="90.1.1"),
            ledger_entry(row=2, account="99.9.9"),
            ledger_entry(row=3, account="88.8"),
            ledger_entry(row=4, account="99.9.9"),
        )

        assert unknown_accounts(ledger, config) == ("88.8", "99.9.9")


class TestOpsClassification:
    """§3.6: классификация записей опер-лога."""

    def test_pko_is_always_income(self, config: Config) -> None:
        entry = ops_entry(kind=OpsKind.PKO, counterparty="Иванов Иван")

        assert classify_ops_entry(entry, config) == (OpsClass.INCOME, "block")

    def test_central_cash_is_collection(self, config: Config) -> None:
        entry = ops_entry(counterparty="Центральная касса")

        assert classify_ops_entry(entry, config) == (OpsClass.COLLECTION, "counterparty")

    def test_service_recipient_is_service(self, config: Config) -> None:
        entry = ops_entry(counterparty="АРХИВ ПВЗ")

        assert classify_ops_entry(entry, config) == (OpsClass.SERVICE, "counterparty")

    def test_client_is_refund(self, config: Config) -> None:
        entry = ops_entry(counterparty="Правосуд Дмитрий", amount=Decimal("203.93"))

        assert classify_ops_entry(entry, config) == (OpsClass.REFUND, "counterparty")

    def test_time_fallback_midnight_is_collection(self, config: Config) -> None:
        entry = ops_entry(moment=datetime(2024, 2, 1, 0, 0, 0), counterparty="")

        assert classify_ops_entry(entry, config) == (OpsClass.COLLECTION, "time_fallback")

    def test_time_fallback_real_time_is_refund(self, config: Config) -> None:
        entry = ops_entry(moment=datetime(2024, 2, 1, 14, 3, 7), counterparty="")

        assert classify_ops_entry(entry, config) == (OpsClass.REFUND, "time_fallback")

    def test_classified_by_records_the_method(self, config: Config) -> None:
        """§4.2: способ классификации нужен аудиторскому следу §12."""
        by_party = classify_ops_entry(ops_entry(counterparty="Иванов"), config)[1]
        by_time = classify_ops_entry(ops_entry(counterparty=""), config)[1]

        assert by_party == "counterparty"
        assert by_time == "time_fallback"


class TestTimeFallbackVerification:
    """§3.3: гипотеза верифицируется до применения."""

    def test_fallback_needed_only_without_counterparties(self) -> None:
        with_party = (ops_entry(counterparty="Иванов"),)
        without = (ops_entry(counterparty=""),)

        assert not needs_time_fallback(with_party)
        assert needs_time_fallback(without)

    def test_accepted_when_days_converge(self) -> None:
        """Порог §3.3 — ≥ 90 % точно сходящихся дней."""
        ledger = tuple(
            ledger_entry(
                row=index,
                day=date(2024, 2, index),
                credit=Decimal("100.00"),
                account="76.9.1",
                category=Category.REFUND,
            )
            for index in range(1, 11)
        )
        ops = tuple(
            ops_entry(
                row=index,
                moment=datetime(2024, 2, index, 14, 0, 0),
                amount=Decimal("100.00"),
            )
            for index in range(1, 11)
        )

        verification = verify_time_fallback(ops, ledger)

        assert verification.accepted
        assert verification.days_exact == 10
        assert verification.exact_day_share == 1.0

    def test_refused_when_days_do_not_converge(self) -> None:
        """Не прошло — отказ, а не «примерно подходит» (§0.3)."""
        ledger = tuple(
            ledger_entry(
                row=index,
                day=date(2024, 2, index),
                credit=Decimal("100.00"),
                account="76.9.1",
                category=Category.REFUND,
            )
            for index in range(1, 11)
        )
        ops = tuple(
            ops_entry(
                row=index,
                moment=datetime(2024, 2, index, 14, 0, 0),
                amount=Decimal("77.00"),
            )
            for index in range(1, 11)
        )

        verification = verify_time_fallback(ops, ledger)

        assert not verification.accepted
        assert verification.days_exact == 0

    def test_classify_stops_with_block_classification_failed(self, config: Config) -> None:
        """§3.3: не прошло — остановка, а не догадка."""
        normalized = NormalizeResult(
            ledger=(
                ledger_entry(
                    row=1,
                    credit=Decimal("100.00"),
                    account="76.9.1",
                    category=Category.REFUND,
                ),
            ),
            ops=(ops_entry(row=2, amount=Decimal("77.00"), counterparty=""),),
            totals=_totals(),
            issues=(),
        )

        with pytest.raises(BlockClassificationFailed, match="BLOCK_CLASSIFICATION_FAILED"):
            classify(normalized, config)

    def test_failure_message_names_the_gate(self, config: Config) -> None:
        """§0.3: отказ обязан объяснять причину."""
        normalized = NormalizeResult(
            ledger=(
                ledger_entry(
                    row=1,
                    credit=Decimal("100.00"),
                    account="76.9.1",
                    category=Category.REFUND,
                ),
            ),
            ops=(ops_entry(row=2, amount=Decimal("77.00"), counterparty=""),),
            totals=_totals(),
            issues=(),
        )

        with pytest.raises(BlockClassificationFailed) as excinfo:
            classify(normalized, config)

        message = str(excinfo.value)
        assert "точно сходятся" in message
        assert "90%" in message


class TestServiceTotal:
    """§3.6: служебные исключаются из сверки возвратов, но остаются в отчёте."""

    def test_service_total_sums_only_service(self, config: Config) -> None:
        normalized = NormalizeResult(
            ledger=(),
            ops=(
                ops_entry(row=1, amount=Decimal("11310.00"), counterparty="СУД Минского района"),
                ops_entry(row=2, amount=Decimal("150.00"), counterparty="АРХИВ ПВЗ"),
                ops_entry(row=3, amount=Decimal("150.00"), counterparty="Финконтроль"),
                ops_entry(row=4, amount=Decimal("203.93"), counterparty="Правосуд Дмитрий"),
            ),
            totals=_totals(),
            issues=(),
        )

        result = classify(normalized, config)

        # Солигорск: служебные давали мнимое расхождение 11 610,00.
        assert service_total(result.ops) == Decimal("11610.00")


def _totals() -> LedgerTotals:
    """Пустые контрольные суммы: тестам классификации они безразличны."""
    return LedgerTotals(
        opening=ZERO,
        closing_stated=ZERO,
        turnover_debit=None,
        turnover_credit=None,
    )
