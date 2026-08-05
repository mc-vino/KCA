"""Общие фикстуры и построитель синтетических выгрузок.

Реальные калибровочные кассы §11.3 содержат ФИО получателей и в репозиторий не
попадают. Чтобы стадии §5.1–5.2 проверялись на настоящих `.xlsx`, а не на
подсунутых списках, здесь собирается книга той же формы: слева карточка 1С
(§3.2), справа два блока опер-лога в одной из четырёх раскладок §3.3.

Построитель намеренно воспроизводит и грязь исходников: неразрывные пробелы,
числа строкой с запятой, дату, указанную один раз на блок строк за день.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from cashforensics.models import Config, load_config

CASH_ACCOUNT = "50.2"

# Раскладки блоков опер-лога — таблица §3.3 ТЗ.
# Значения: (первая колонка РКО, первая колонка ПКО); None — блок отсутствует.
BLOCK_VARIANTS: dict[str, tuple[int | None, int | None]] = {
    "A": (11, 15),
    "B": (15, 11),
    "C": (11, 14),
    "D": (12, None),
}


@dataclass(frozen=True)
class Posting:
    """Проводка карточки 1С для построителя — §3.2."""

    day: date
    doc: str
    debit_account: str
    debit: Decimal | str | None = None
    credit_account: str = ""
    credit: Decimal | str | None = None


@dataclass(frozen=True)
class OpsRecord:
    """Запись опер-лога для построителя — §3.3."""

    moment: datetime
    amount: Decimal | str
    counterparty: str = ""


@dataclass
class SheetPlan:
    """План синтетического листа.

    Attributes:
        variant: буква раскладки из :data:`BLOCK_VARIANTS`.
        postings: проводки карточки в порядке появления.
        rko: записи блока РКО.
        pko: записи блока ПКО.
        opening: сальдо на начало (колонка 4, §3.2).
        closing: сальдо на конец; ``None`` — посчитать из проводок.
        turnovers: писать ли строку «Обороты за период» (без неё V1/V2
            пропускаются, §5.3).
        closing_side: сторона сальдо на конец, «Д» или «К».
        pvz: идентификатор ПВЗ для шапки.
        stated_period: заявленный период для шапки.
    """

    variant: str = "A"
    postings: list[Posting] = field(default_factory=list)
    rko: list[OpsRecord] = field(default_factory=list)
    pko: list[OpsRecord] = field(default_factory=list)
    opening: Decimal = Decimal("0.00")
    closing: Decimal | None = None
    turnovers: bool = True
    closing_side: str = "Д"
    pvz: str = "PAX 119011650"
    stated_period: str = "19.05.2023 - 30.06.2026"


def _money(value: Decimal | str | None) -> object:
    r"""Записать сумму так, как её пишет 1С: строкой с запятой и \xa0-разрядами."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return f"{value:,.2f}".replace(",", "\xa0").replace(".", ",")


def build_workbook(path: Path, plan: SheetPlan) -> Path:
    """Собрать `.xlsx` по плану и вернуть путь к нему."""
    workbook = openpyxl.Workbook()
    sheet = workbook.worksheets[0]
    rows: list[list[Any]] = []

    def blank() -> list[Any]:
        return [None] * 20

    # Шапка: отбор по кассе и заявленный период (§5.1).
    header_1 = blank()
    header_1[0] = f"Отбор: Кассы организации = {plan.pvz}"
    rows.append(header_1)

    header_2 = blank()
    header_2[0] = plan.stated_period
    rows.append(header_2)

    # Заголовок таблицы карточки плюс заголовки блоков опер-лога.
    header_3 = blank()
    header_3[1] = "Период"
    header_3[2] = "Документ"
    header_3[3] = "Аналитика Дт"
    header_3[4] = "Счёт Дт"
    header_3[5] = "Дебет"
    header_3[6] = "Счёт Кт"
    header_3[7] = "Кредит"
    header_3[8] = "Сальдо"
    header_3[9] = "Значение"

    rko_start, pko_start = BLOCK_VARIANTS[plan.variant]
    if rko_start is not None:
        header_3[rko_start] = "Дата РКО"
        header_3[rko_start + 1] = "Сумма"
        if plan.variant != "C":
            header_3[rko_start + 2] = "Кому выдано"
    if pko_start is not None:
        header_3[pko_start] = "Дата ПКО"
        header_3[pko_start + 1] = "Сумма"
        header_3[pko_start + 2] = "От кого принято"
    rows.append(header_3)

    # Сальдо на начало — значение в колонке 4 (E), не в 9 (§3.2).
    opening_row = blank()
    opening_row[1] = "Сальдо на начало"
    opening_row[4] = _money(plan.opening)
    opening_row[9] = _money(Decimal("0.00"))
    rows.append(opening_row)

    # Карточка: дата пишется один раз на блок строк за день (§3.2).
    previous_day: date | None = None
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for posting in plan.postings:
        row = blank()
        if posting.day != previous_day:
            row[1] = posting.day.strftime("%d.%m.%Y")
            previous_day = posting.day
        row[2] = posting.doc
        row[4] = posting.debit_account
        row[5] = _money(posting.debit)
        row[6] = posting.credit_account
        row[7] = _money(posting.credit)
        # В обороты идут только проводки по кассе: строка, где 50.2 не
        # участвует, к карточке счёта не относится и в итоги не попадает (§3.2).
        if isinstance(posting.debit, Decimal) and posting.debit_account == CASH_ACCOUNT:
            total_debit += posting.debit
        if isinstance(posting.credit, Decimal) and posting.credit_account == CASH_ACCOUNT:
            total_credit += posting.credit
        rows.append(row)

    # Блоки опер-лога живут в своих колонках и по строкам с карточкой не
    # выровнены (§3.1): пишем их с собственного смещения.
    def place(records: list[OpsRecord], start: int | None, *, with_party: bool) -> None:
        if start is None:
            return
        for offset, record in enumerate(records):
            index = 4 + offset
            while index >= len(rows):
                rows.append(blank())
            rows[index][start] = record.moment.strftime("%d.%m.%Y %H:%M:%S")
            rows[index][start + 1] = _money(record.amount)
            if with_party:
                rows[index][start + 2] = record.counterparty

    place(plan.rko, rko_start, with_party=plan.variant != "C")
    place(plan.pko, pko_start, with_party=True)

    if plan.turnovers:
        turnover_row = blank()
        turnover_row[1] = "Обороты за период"
        turnover_row[4] = _money(total_debit)
        turnover_row[6] = _money(total_credit)
        rows.append(turnover_row)

    computed_closing = plan.opening + total_debit - total_credit
    closing = plan.closing if plan.closing is not None else computed_closing
    closing_row = blank()
    closing_row[1] = "Сальдо на конец"
    closing_row[4] = _money(abs(closing) if plan.closing_side == "К" else closing)
    closing_row[8] = plan.closing_side
    closing_row[9] = _money(Decimal("0.00"))
    rows.append(closing_row)

    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()
    return path


@pytest.fixture(scope="session")
def config() -> Config:
    """Конфигурация §6 из версионируемого ``config/default.yaml``."""
    root = Path(__file__).resolve().parent.parent
    return load_config(root / "config" / "default.yaml")


@pytest.fixture
def make_workbook(tmp_path: Path) -> Callable[[SheetPlan], Path]:
    """Фабрика синтетических выгрузок: ``make_workbook(plan) -> Path``."""
    counter = {"n": 0}

    def factory(plan: SheetPlan) -> Path:
        counter["n"] += 1
        return build_workbook(tmp_path / f"касса_{counter['n']}.xlsx", plan)

    return factory
