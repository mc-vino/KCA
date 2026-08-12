"""Стадия NORMALIZE — §5.2 ТЗ, правила разбора §3.2 и §3.4.

Читает весь период, никаких обрезаний. Наследует дату вниз, применяет
нормализацию значений и определяет направление проводки.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from cashforensics.models import (
    BlockLayout,
    Category,
    Config,
    DocType,
    IngestResult,
    LedgerEntry,
    LedgerTotals,
    NormalizeResult,
    OpsClass,
    OpsEntry,
    OpsKind,
    ParseIssue,
)

__all__ = [
    "DATE_RE",
    "DOC_NUMBER_RE",
    "HEADER_SCAN_ROWS",
    "MONEY_EXPONENT",
    "SERVICE_ROW_MARKERS",
    "actual_period",
    "cell",
    "clean_account",
    "clean_text",
    "detect_doc_type",
    "extract_doc_number",
    "find_ledger_header_row",
    "inherit_dates",
    "is_analytics_row",
    "is_service_row",
    "normalize",
    "normalize_ledger",
    "normalize_ops",
    "parse_datetime",
    "parse_decimal",
    "posting_direction",
    "quantize_money",
    "read_totals",
]

DATE_RE = re.compile(r"(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{4})(?:\s+(\d{1,2}):(\d{2}):(\d{2}))?")
"""Регулярка дат §3.4. Время сохраняется: нужно для fallback §3.3 и сигнатур §8."""

DOC_NUMBER_RE = re.compile(r"\d{6,}")
"""Номер документа — первая последовательность из ≥ 6 цифр (§3.4)."""

MONEY_EXPONENT = Decimal("0.01")
"""Квантование денежных величин — 2 знака, ``ROUND_HALF_UP`` (§10)."""

HEADER_SCAN_ROWS = 20
"""Глубина поиска строки-заголовка карточки — та же, что для блоков §3.3."""

LEDGER_DATE_CAPTIONS = ("дата", "период")
"""Заголовки первой колонки карточки — §3.2.

На PAX_119011650 колонка названа «Дата»; в других выгрузках 1С встречается
«Период». Заголовок опознаётся по паре «дата/период» + «документ», а не по
одному варианту написания.
"""

SERVICE_ROW_MARKERS = (
    "Сальдо на начало",
    "Обороты за период",
    "Сальдо на конец",
    "Обороты за",
    "Итого",
)
"""Служебные строки карточки, определяемые по колонке B — §3.2."""

_OPENING_MARKER = "Сальдо на начало"
_CLOSING_MARKER = "Сальдо на конец"
_PERIOD_TURNOVER_MARKER = "Обороты за период"

# Индексы колонок карточки 1С — §3.2, 0-based.
COL_DATE = 1
COL_DOC = 2
COL_OPERATION = 3
COL_DEBIT_ACCOUNT = 4
COL_DEBIT_AMOUNT = 5
COL_CREDIT_ACCOUNT = 6
COL_CREDIT_AMOUNT = 7
COL_BALANCE_SIDE = 8
COL_BALANCE_VALUE = 9

LEDGER_COLUMNS = range(COL_DATE, COL_BALANCE_VALUE + 1)
"""Диапазон колонок карточки: строка вне него принадлежит опер-логу (§3.1)."""

LEDGER_POSTING_COLUMNS = (
    COL_DATE,
    COL_DOC,
    COL_DEBIT_ACCOUNT,
    COL_DEBIT_AMOUNT,
    COL_CREDIT_ACCOUNT,
    COL_CREDIT_AMOUNT,
    COL_BALANCE_VALUE,
)
"""Колонки, наличие которых делает строку кандидатом в проводки — §3.2.

Колонка 3 («Операция») сюда намеренно не входит: одна проводка занимает в
карточке несколько физических строк, и в продолжениях заполнена только она —
«PAX 119011650», «Розничная торговля», «Основной договор». Это структура
выгрузки, а не сбой разбора, и в ``ParseIssue`` такие строки не попадают.
"""

_CREDIT_SIDE = "К"

# Пробельные символы, встречающиеся в выгрузках 1С внутри чисел и имён.
_SPACES = ("\xa0", " ", " ", " ", " ")

_ZERO = Decimal("0.00")

_PLACEHOLDER_CLASS = {
    OpsKind.PKO: OpsClass.INCOME,
    OpsKind.RKO: OpsClass.REFUND,
}
"""Классификация до §5.4.

Значение временное; признак «ещё не классифицировано» — пустой
``classified_by``, а не сама метка: §4.2 не предусматривает для неё «неизвестно».
"""


def cell(row: Sequence[object], index: int) -> object:
    """Значение ячейки по индексу или ``None``, если колонки в строке нет.

    Строки листа имеют разную длину: `openpyxl` в режиме ``read_only`` обрезает
    хвостовые пустые ячейки, а блоки опер-лога стоят правее карточки (§3.1).
    """
    if 0 <= index < len(row):
        return row[index]
    return None


def clean_text(value: object) -> str:
    r"""Привести значение ячейки к строке, заменив ``\xa0`` на пробел — §3.4.

    Неразрывные пробелы встречаются в датах, именах и числах; заменять
    **до любого парсинга**.
    """
    if value is None:
        return ""
    text = str(value)
    for space in _SPACES:
        text = text.replace(space, " ")
    return text.strip()


def clean_account(value: object) -> str:
    """Номер счёта в каноничном виде — §3.2, §3.5.

    Excel отдаёт «51» как ``51.0``: без нормализации счёт не находится в
    справочнике §3.5 и молча уезжает в «прочее», что §3.5 прямо запрещает.
    Счета вида «57.1.1» приходят строкой и не трогаются.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return clean_text(value)


def quantize_money(value: Decimal) -> Decimal:
    """Квантовать сумму до 2 знаков, ``ROUND_HALF_UP`` — §10."""
    return value.quantize(MONEY_EXPONENT, rounding=ROUND_HALF_UP)


def parse_decimal(value: object) -> Decimal | None:
    """Разобрать число — §3.4.

    Принимает ``float``, ``int`` или строку вида ``1 234,56`` / ``1234.56``.
    Возвращает :class:`~decimal.Decimal`, квантованный до 2 знаков,
    ``ROUND_HALF_UP`` (§10). ``float`` наружу не выходит.

    Returns:
        Сумму либо ``None``, если ячейка пуста или не является числом.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return quantize_money(value)
    if isinstance(value, int):
        return quantize_money(Decimal(value))
    if isinstance(value, float):
        # str() даёт кратчайшее представление, совпадающее с тем, что видит
        # пользователь в Excel; Decimal(float) дало бы двоичный хвост.
        return quantize_money(Decimal(str(value)))
    if isinstance(value, (datetime, date)):
        return None

    text = clean_text(value)
    if not text:
        return None
    for space in _SPACES:
        text = text.replace(space, "")
    text = text.replace("−", "-").replace("–", "-")
    text = text.replace(",", ".")
    try:
        return quantize_money(Decimal(text))
    except InvalidOperation:
        return None


def parse_datetime(value: object) -> datetime | None:
    """Разобрать дату/время — §3.4, регулярка :data:`DATE_RE`.

    Время сохраняется: оно нужно time-fallback §3.3 и сигнатурам §8.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if value is None or isinstance(value, (int, float, Decimal)):
        return None

    match = DATE_RE.search(clean_text(value))
    if match is None:
        return None
    day, month, year = (int(match.group(i)) for i in (1, 2, 3))
    hour, minute, second = (int(g) if g else 0 for g in match.group(4, 5, 6))
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        # 32.13.2024 и подобное — не дата; вызывающий обязан завести ParseIssue.
        return None


def extract_doc_number(doc_text: str) -> str:
    """Извлечь номер документа — §3.4.

    Первая последовательность из ≥ 6 цифр. Пустая строка означает, что номера
    в тексте нет: это не ошибка разбора, а свойство документа.
    """
    match = DOC_NUMBER_RE.search(clean_text(doc_text))
    return match.group(0) if match else ""


def detect_doc_type(doc_text: str, reversal_pattern: str) -> DocType:
    """Определить тип документа по тексту колонки C — §3.2.

    Сторно проверяется первым: «Корректировка записей регистров» может
    содержать в тексте и слова исходного ордера.
    """
    text = clean_text(doc_text)
    if not text:
        return DocType.OTHER
    if re.search(reversal_pattern, text, re.IGNORECASE):
        return DocType.REVERSAL
    lowered = text.lower()
    if "приходный кассовый ордер" in lowered:
        return DocType.PKO
    if "расходный кассовый ордер" in lowered:
        return DocType.RKO
    if "передача денег между кассами" in lowered:
        return DocType.TRANSFER
    return DocType.OTHER


def is_service_row(value: object) -> bool:
    """Строка карточки является служебной — §3.2.

    Определяется по колонке B: «Сальдо на начало», «Обороты за …», «Итого».
    """
    text = clean_text(value)
    return any(text.startswith(marker) for marker in SERVICE_ROW_MARKERS)


def inherit_dates(rows: Sequence[Sequence[object]]) -> tuple[date | None, ...]:
    """Протянуть дату проводки вниз по блоку строк за день — §3.2.

    Дата указывается один раз в начале блока; последующие строки её не
    повторяют. Служебные строки дату не переопределяют: «Обороты за 01.02.2024»
    содержит дату в тексте, и без этой оговорки она сбивала бы наследование.

    Returns:
        Дата для каждой строки; ``None`` до первой встреченной даты.
    """
    current: date | None = None
    result: list[date | None] = []
    for row in rows:
        raw = cell(row, COL_DATE)
        if not is_service_row(raw):
            parsed = parse_datetime(raw)
            if parsed is not None:
                current = parsed.date()
        result.append(current)
    return tuple(result)


def posting_direction(
    row: Sequence[object],
    cash_account: str,
) -> tuple[Decimal, Decimal, str] | None:
    """Определить направление проводки и корр. счёт — §3.2.

    Возвращает ``(debit, credit, counter_account)`` либо ``None``, если строка
    не относится к кассе.

    **Критично (§3.2):** для дебетовых проводок корреспондирующий счёт лежит в
    колонке **G**, для кредитовых — в **E**. Перепутанные местами счета дают
    полностью ложную классификацию прихода.
    """
    debit_account = clean_account(cell(row, COL_DEBIT_ACCOUNT))
    credit_account = clean_account(cell(row, COL_CREDIT_ACCOUNT))
    debit_amount = parse_decimal(cell(row, COL_DEBIT_AMOUNT))
    credit_amount = parse_decimal(cell(row, COL_CREDIT_AMOUNT))

    if debit_account == cash_account and debit_amount is not None:
        # Деньги пришли в кассу: корр. счёт — из G.
        return (debit_amount, _ZERO, credit_account)
    if credit_account == cash_account and credit_amount is not None:
        # Деньги ушли из кассы: корр. счёт — из E.
        return (_ZERO, credit_amount, debit_account)
    return None


def _signed_balance(row: Sequence[object]) -> Decimal | None:
    """Сальдо из колонки 4 (E) с учётом стороны из колонки 8 (I) — §3.2.

    Значение берётся из колонки 4, не из 9: чтение из 9 дало 0 вместо
    −4 952,36 (§3.2). Колонка 8 хранит сторону сальдо «Д/К»; кредитовое сальдо
    операционной кассы — отрицательное. Если сторона не указана, значение
    берётся как есть, и корректность проверит инвариант V3 (§5.3).
    """
    value = parse_decimal(cell(row, COL_DEBIT_ACCOUNT))
    if value is None:
        return None
    side = clean_text(cell(row, COL_BALANCE_SIDE)).upper()
    if side == _CREDIT_SIDE and value > 0:
        return -value
    return value


def read_totals(rows: Sequence[Sequence[object]]) -> LedgerTotals:
    """Прочитать служебные строки карточки — §3.2.

    ``Сальдо на начало`` и ``Сальдо на конец`` берутся из **колонки 4 (E)**,
    не из 9: ловушка §3.2, давшая 0 вместо −4 952,36 на Щучине. Обороты за
    период — дебет в колонке 4 (E), кредит в колонке 6 (G).

    Отсутствующие обороты возвращаются как ``None``: V1/V2 тогда пропускаются с
    пометкой, а V3 остаётся обязательным (§5.3).
    """
    opening: Decimal | None = None
    closing: Decimal | None = None
    turnover_debit: Decimal | None = None
    turnover_credit: Decimal | None = None

    for row in rows:
        marker = clean_text(cell(row, COL_DATE))
        if marker.startswith(_OPENING_MARKER):
            opening = _signed_balance(row)
        elif marker.startswith(_CLOSING_MARKER):
            closing = _signed_balance(row)
        elif marker.startswith(_PERIOD_TURNOVER_MARKER):
            turnover_debit = parse_decimal(cell(row, COL_DEBIT_ACCOUNT))
            turnover_credit = parse_decimal(cell(row, COL_CREDIT_ACCOUNT))

    return LedgerTotals(
        opening=opening if opening is not None else _ZERO,
        closing_stated=closing if closing is not None else _ZERO,
        turnover_debit=turnover_debit,
        turnover_credit=turnover_credit,
    )


def find_ledger_header_row(rows: Sequence[Sequence[object]]) -> int:
    """Найти строку-заголовок карточки — §3.2.

    Заголовок: колонка 1 начинается с «Дата», колонка 2 — с «Документ».

    Нужен, потому что шапка выгрузки лежит в той же колонке 1, что и даты
    проводок: строка «31.03.2022 - 30.06.2026» разбирается как дата и без этой
    границы запускала наследование даты до начала таблицы, а сами строки шапки
    попадали в ``ParseIssue``.

    Returns:
        Индекс строки-заголовка либо ``-1``, если заголовок не найден — тогда
        разбор идёт с начала листа.
    """
    for index in range(min(HEADER_SCAN_ROWS, len(rows))):
        row = rows[index]
        date_caption = clean_text(cell(row, COL_DATE)).lower()
        doc_caption = clean_text(cell(row, COL_DOC)).lower()
        if date_caption.startswith(LEDGER_DATE_CAPTIONS) and doc_caption.startswith("документ"):
            return index
    return -1


def _is_subheader_row(row: Sequence[object]) -> bool:
    """Вторая строка заголовка: «Счет | Сумма | Счет | Сумма» — §3.2."""
    labels = {
        clean_text(cell(row, index)).lower()
        for index in (COL_DEBIT_ACCOUNT, COL_DEBIT_AMOUNT, COL_CREDIT_ACCOUNT, COL_CREDIT_AMOUNT)
    }
    return bool(labels & {"счет", "счёт", "сумма"})


def is_analytics_row(row: Sequence[object]) -> bool:
    """Строка-продолжение проводки: заполнена только колонка «Операция» — §3.2.

    В карточке 1С одна проводка занимает несколько физических строк: первая
    несёт дату, документ, счета и суммы, последующие — аналитику
    («PAX 119011650», «ПВЗ Солигорск (розн)», «Основной договор»).

    Такие строки не разбираются и не считаются ошибкой: на Солигорске их 15 378
    из 82 611, и объявление их «неразобранными» похоронило бы настоящие
    проблемы разбора под шумом.
    """
    if not clean_text(cell(row, COL_OPERATION)):
        return False
    return not any(clean_text(cell(row, index)) for index in LEDGER_POSTING_COLUMNS)


def _row_touches_ledger(row: Sequence[object]) -> bool:
    """Строка несёт данные карточки, а не только опер-лога — §3.1."""
    return any(clean_text(cell(row, index)) for index in LEDGER_COLUMNS)


def normalize_ledger(
    rows: Sequence[Sequence[object]],
    config: Config,
) -> tuple[tuple[LedgerEntry, ...], tuple[ParseIssue, ...]]:
    """Построить нормализованные проводки 1С — §5.2, §4.1.

    Категория здесь ещё не назначена: её присваивает §5.4, поэтому все записи
    выходят с :attr:`~cashforensics.models.Category.OTHER`.

    Любая строка карточки, которую не удалось разобрать, попадает в
    :class:`~cashforensics.models.ParseIssue` с номером и причиной — «тихих»
    пропусков нет (§12).

    Returns:
        Пара ``(записи, проблемы разбора)``.
    """
    header_row = find_ledger_header_row(rows)
    # Шапка выгрузки не участвует в наследовании даты: строка периода
    # «31.03.2022 - 30.06.2026» стоит в колонке даты и сбивала бы его.
    dates = (*(None,) * (header_row + 1), *inherit_dates(rows[header_row + 1 :]))

    entries: list[LedgerEntry] = []
    issues: list[ParseIssue] = []

    for index, row in enumerate(rows):
        row_number = index + 1
        if index <= header_row or _is_subheader_row(row):
            continue
        if (
            is_service_row(cell(row, COL_DATE))
            or is_analytics_row(row)
            or not _row_touches_ledger(row)
        ):
            continue

        direction = posting_direction(row, config.cash_account)
        if direction is None:
            issues.append(
                ParseIssue(
                    row=row_number,
                    column=COL_DEBIT_ACCOUNT,
                    reason=(
                        f"строка карточки не отнесена к счёту {config.cash_account}: "
                        f"дебет «{clean_account(cell(row, COL_DEBIT_ACCOUNT))}», "
                        f"кредит «{clean_account(cell(row, COL_CREDIT_ACCOUNT))}»"
                    ),
                    raw_value=clean_text(cell(row, COL_DOC)),
                ),
            )
            continue

        entry_date = dates[index]
        if entry_date is None:
            issues.append(
                ParseIssue(
                    row=row_number,
                    column=COL_DATE,
                    reason="дата проводки не определена и не унаследована",
                    raw_value=clean_text(cell(row, COL_DATE)),
                ),
            )
            continue

        debit, credit, counter_account = direction
        doc_text = clean_text(cell(row, COL_DOC))
        doc_type = detect_doc_type(doc_text, config.patterns.reversal_doc)
        entries.append(
            LedgerEntry(
                row=row_number,
                date=entry_date,
                debit=debit,
                credit=credit,
                counter_account=counter_account,
                category=Category.OTHER,
                doc_text=doc_text,
                doc_number=extract_doc_number(doc_text),
                doc_type=doc_type,
                is_reversal=doc_type is DocType.REVERSAL or debit < 0 or credit < 0,
            ),
        )

    return tuple(entries), tuple(issues)


def normalize_ops(
    rows: Sequence[Sequence[object]],
    layout: BlockLayout,
) -> tuple[tuple[OpsEntry, ...], tuple[ParseIssue, ...]]:
    """Построить записи опер-лога из блоков РКО/ПКО — §5.2, §4.2.

    Классификация назначается на §5.4; здесь заполняются ``dt``, ``amount``,
    ``counterparty`` и ``kind``, а ``classified_by`` остаётся пустым.

    Returns:
        Пара ``(записи, проблемы разбора)``. Записи упорядочены по
        ``(row, kind)`` — полный явный ключ (§12).
    """
    entries: list[OpsEntry] = []
    issues: list[ParseIssue] = []

    blocks = ((OpsKind.RKO, layout.rko), (OpsKind.PKO, layout.pko))
    for kind, block in blocks:
        if block is None:
            continue
        date_column, amount_column, party_column = block
        for index in range(layout.header_row + 1, len(rows)):
            row = rows[index]
            raw_date = cell(row, date_column)
            raw_amount = cell(row, amount_column)
            if not clean_text(raw_date) and not clean_text(raw_amount):
                continue

            moment = parse_datetime(raw_date)
            amount = parse_decimal(raw_amount)
            if moment is None or amount is None:
                issues.append(
                    ParseIssue(
                        row=index + 1,
                        column=date_column if moment is None else amount_column,
                        reason=(
                            f"запись опер-лога {kind.value}: "
                            + ("не разобрана дата" if moment is None else "не разобрана сумма")
                        ),
                        raw_value=clean_text(raw_date if moment is None else raw_amount),
                    ),
                )
                continue

            entries.append(
                OpsEntry(
                    row=index + 1,
                    dt=moment,
                    amount=amount,
                    counterparty=(
                        clean_text(cell(row, party_column)) if party_column is not None else ""
                    ),
                    kind=kind,
                    classification=_PLACEHOLDER_CLASS[kind],
                    classified_by="",
                ),
            )

    entries.sort(key=lambda entry: (entry.row, entry.kind.value))
    return tuple(entries), tuple(issues)


def actual_period(ledger: Sequence[LedgerEntry]) -> tuple[date, date] | None:
    """Фактический период проводок — §5.1.

    Заявленный в шапке период регулярно не совпадает с фактическим (на Щучине
    шапка говорила «до 2025», данные шли до мая 2026), поэтому в отчёт идут оба.
    """
    if not ledger:
        return None
    dates = [entry.date for entry in ledger]
    return (min(dates), max(dates))


def normalize(ingested: IngestResult, config: Config) -> NormalizeResult:
    """Стадия NORMALIZE целиком — §5.2.

    Читает весь период, никаких обрезаний.
    """
    ledger, ledger_issues = normalize_ledger(ingested.raw_rows, config)
    ops, ops_issues = normalize_ops(ingested.raw_rows, ingested.layout)
    issues = tuple(
        sorted(
            (*ingested.issues, *ledger_issues, *ops_issues),
            key=lambda issue: (issue.row, issue.column if issue.column is not None else -1),
        ),
    )
    return NormalizeResult(
        ledger=ledger,
        ops=ops,
        totals=read_totals(ingested.raw_rows),
        issues=issues,
    )
