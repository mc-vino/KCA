"""Excel-отчёт — §9.1 ТЗ. Основной формат.

Библиотека ``openpyxl``. Шрифт Arial, формат чисел ``#,##0.00;(#,##0.00);"-"``,
сетка выключена.

Ловушка §9.1
------------
Строка, начинающаяся с ``=``, интерпретируется Excel как формула: текст вроде
``= всё отклонение`` даёт ``#VALUE!``. Все текстовые значения обязаны
проверяться на ведущий ``=`` и экранироваться.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from cashforensics.models import AnalysisResult, CausalLevel, LocalizationStatus, Severity
from cashforensics.rank import confidence_label

__all__ = [
    "COLORS",
    "FONT_NAME",
    "NUMBER_FORMAT",
    "SHEETS",
    "escape_leading_equals",
    "render_excel",
    "write_row",
]

NUMBER_FORMAT = '#,##0.00;(#,##0.00);"-"'
"""Формат чисел — §9.1."""

FONT_NAME = "Arial"
"""Шрифт отчёта — §9.1."""

COLORS: dict[str, str] = {
    "ink": "1A1813",
    "steel": "34424A",
    "white": "FFFFFF",
    "hair": "D6CDBC",
    "red": "B23A2E",
    "red_bg": "FCE8E6",
    "lime": "5F7D17",
    "lime_bg": "EAF2DA",
    "amber": "A9781B",
    "amber_bg": "FBF0D9",
}
"""Палитра — §9.1."""

SHEETS: tuple[str, ...] = (
    "Причина",
    "Ключевые документы",
    "Динамика сальдо",
    "Сверка",
    "Лестница",
    "Не проведено в 1С",
    "Повторы",
    "Документы",
)
"""Обязательные листы в порядке §9.1."""

_SEVERITY_FILL = {
    Severity.ERROR: COLORS["red_bg"],
    Severity.REVIEW: COLORS["amber_bg"],
    Severity.NORMAL: COLORS["lime_bg"],
}


def escape_leading_equals(value: str) -> str:
    """Экранировать текст с ведущим ``=`` — ловушка §9.1.

    Excel считает такую строку формулой и показывает ``#VALUE!``. Апостроф
    перед строкой заставляет его трактовать содержимое как текст.
    """
    return f"'{value}" if value.startswith("=") else value


def _cell_value(value: object) -> object:
    """Привести значение к тому, что понимает Excel, не теряя точности.

    ``Decimal`` отдаётся как есть: `openpyxl` пишет его числом, а не строкой,
    и формат §9.1 применяется к настоящему числу. Текст экранируется.
    """
    if isinstance(value, str):
        return escape_leading_equals(value)
    return value


def write_row(
    sheet: Worksheet,
    values: list[object],
    *,
    bold: bool = False,
    fill: str | None = None,
) -> None:
    """Записать строку с оформлением §9.1."""
    sheet.append([_cell_value(value) for value in values])
    row = sheet.max_row
    for column in range(1, len(values) + 1):
        cell = sheet.cell(row=row, column=column)
        cell.font = Font(name=FONT_NAME, bold=bold, color=COLORS["ink"])
        if isinstance(cell.value, (int, float, Decimal)):
            cell.number_format = NUMBER_FORMAT
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        cell.alignment = Alignment(vertical="top", wrap_text=False)


def _new_sheet(workbook: Workbook, title: str) -> Worksheet:
    sheet: Worksheet = workbook.create_sheet(title)
    sheet.sheet_view.showGridLines = False
    return sheet


def _sheet_cause(workbook: Workbook, result: AnalysisResult) -> None:
    """Лист «Причина» — §9.1.1. Ответ на главный вопрос."""
    sheet = _new_sheet(workbook, SHEETS[0])
    write_row(sheet, ["Причинная раскладка отклонения сальдо"], bold=True)
    write_row(sheet, ["Сумма", "Уровень", "Причина", "Документы"], bold=True)

    # Три блока. Два первых — стороны расхождения §5.6; плоским списком раскладка
    # нечитаема на кассах со встречными потоками (на Солигорске −10 946,54 против
    # +2 893,74 при полном отклонении −1 224,80). Заголовки говорят о направлении
    # сальдо, а не о том, «больше или меньше провели»: для прихода и для выдач
    # эти прочтения противоположны.
    #
    # Третий блок — структурные слагаемые §5.10 (прочие потоки, дисбаланс логов).
    # Ошибками они не являются, но без них раскладка не сходится.
    waterfall = result.waterfall
    lines = waterfall.causal_lines
    deviation = [line for line in lines if line.is_deviation]
    blocks = (
        ("Сальдо 1С ниже фактического", waterfall.overstated()),
        ("Сальдо 1С выше фактического", waterfall.understated()),
    )
    for index, (caption, total) in enumerate(blocks):
        block = [line for line in deviation if (line.amount < 0) is (index == 0)]
        if not block:
            continue
        write_row(sheet, [total, caption], bold=True, fill=COLORS["lime_bg"])
        for line in block:
            write_row(
                sheet,
                [line.amount, line.level.value, line.title, ", ".join(line.doc_numbers)],
            )
    structure = [line for line in lines if line.level is CausalLevel.STRUCTURE]
    if structure:
        write_row(
            sheet,
            [waterfall.structural(), "Структурные слагаемые §5.10 — не расхождение учёта"],
            bold=True,
            fill=COLORS["lime_bg"],
        )
        for line in structure:
            write_row(
                sheet,
                [line.amount, line.level.value, line.title, ", ".join(line.doc_numbers)],
            )
    for line in lines:
        if line.is_residual:
            write_row(sheet, [line.amount, line.level.value, line.title], fill=COLORS["amber_bg"])
    write_row(sheet, [])
    write_row(
        sheet,
        ["Сальдо на конец", result.waterfall.closing, "целевое", result.waterfall.target],
        bold=True,
    )
    write_row(sheet, ["Несведённый остаток", result.waterfall.unresolved], bold=True)

    write_row(sheet, [])
    write_row(sheet, ["Что проверить"], bold=True)
    # §5: тихих пропусков нет. Записи лога за последней проводкой карточки в
    # сверку не вошли — сравнивать их не с чем, — и умолчать об этом нельзя.
    for category, recon in sorted(
        result.reconciliation.items(),
        key=lambda item: item[0].value,
    ):
        if not recon.outside_period:
            continue
        write_row(
            sheet,
            [
                (
                    f"Категория «{category.value}»: {recon.outside_period} опер-лога лежит "
                    "за последней проводкой карточки 1С и в сверку не вошло — сравнивать "
                    "эти записи не с чем (§5.3). Это срез выгрузки, а не непроведённые "
                    "операции; проверяется расширением периода выгрузки 1С."
                ),
            ],
        )
    write_row(
        sheet,
        [
            (
                "Инструмент не может сказать, какая из двух систем права: 1С или "
                "опер-лог. Если суммы в проблемных ордерах подтвердятся подписями "
                "клиентов, ошибка окажется в выгрузке фронтальной системы, а не в 1С."
            ),
        ],
    )
    write_row(
        sheet,
        [
            (
                "Дисбаланс самих логов измеряется, но не объясняется: его причина "
                "лежит вне обоих файлов."
            ),
        ],
    )
    write_row(
        sheet,
        ["Датировка смещения даётся окном; точная дата из ряда сальдо не выводима."],
    )


def _sheet_key_documents(workbook: Workbook, result: AnalysisResult) -> None:
    """Лист «Ключевые документы» — §9.1.2."""
    sheet = _new_sheet(workbook, SHEETS[1])
    write_row(
        sheet,
        [
            "Дата",
            "Категория",
            "Статус",
            "Код",
            "Сумма",
            "Влияние на сальдо",
            "Строки 1С",
            "Строки лога",
            "Объяснение",
        ],
        bold=True,
    )
    for item in result.localizations:
        write_row(
            sheet,
            [
                item.date,
                item.category.value,
                item.status.value,
                item.code.value if item.code else "",
                item.amount,
                item.balance_impact,
                ", ".join(str(row) for row in item.ledger_rows),
                ", ".join(str(row) for row in item.ops_rows),
                item.explanation,
            ],
            fill=COLORS["red_bg"] if item.status is LocalizationStatus.LOCALIZED else None,
        )


def _sheet_balance(workbook: Workbook, result: AnalysisResult) -> None:
    """Лист «Динамика сальдо» — §9.1.3."""
    sheet = _new_sheet(workbook, SHEETS[2])
    trace = result.balance_trace
    write_row(sheet, ["Пол кассы"], bold=True)
    write_row(sheet, ["Дата", "Пол", "Инкассация", "Приход", "Полнота выемки"], bold=True)
    for point in trace.sweep_points:
        write_row(
            sheet,
            [
                point.date,
                point.floor,
                point.collection,
                point.income,
                "полная" if point.is_full else "частичная выемка — не показатель",
            ],
        )

    write_row(sheet, [])
    write_row(sheet, ["Инвариант неотрицательности"], bold=True)
    report = trace.nonnegativity
    write_row(sheet, ["Первый день ниже целевого", report.first_below_target])
    write_row(sheet, ["Больше не поднималось после", report.never_recovered_after])
    write_row(sheet, ["Минимум", report.minimum, "дата", report.minimum_date])
    write_row(sheet, ["Доля дней ниже целевого", report.share_of_days_below])

    write_row(sheet, [])
    write_row(sheet, ["Поквартальные остатки"], bold=True)
    for label, value in trace.quarterly_balances:
        write_row(sheet, [label, value])

    write_row(sheet, [])
    write_row(sheet, ["Окна смещения"], bold=True)
    write_row(sheet, ["С", "По", "Поток логов", "Поток 1С", "Доминирующая категория"], bold=True)
    for window in trace.shift_windows:
        write_row(
            sheet,
            [
                window.window[0],
                window.window[1],
                window.ops_flow,
                window.ledger_flow,
                window.dominant_category.value if window.dominant_category else "",
            ],
        )


def _sheet_reconciliation(workbook: Workbook, result: AnalysisResult) -> None:
    """Лист «Сверка» — §9.1.4."""
    sheet = _new_sheet(workbook, SHEETS[3])
    write_row(
        sheet,
        [
            "Категория",
            "1С",
            "Опер-лог",
            "Нетто",
            "Брутто",
            "ratio",
            "Дней расхождения",
            "Нетто скорр.",
            "Брутто скорр.",
        ],
        bold=True,
    )
    for category, recon in result.reconciliation.items():
        write_row(
            sheet,
            [
                category.value,
                recon.acc_total,
                recon.ops_total,
                recon.net,
                recon.gross,
                recon.ratio,
                recon.days_with_difference,
                recon.adjusted_net,
                recon.adjusted_gross,
            ],
        )

    write_row(sheet, [])
    write_row(sheet, ["Контроли разбора"], bold=True)
    for check in result.validation.checks:
        write_row(
            sheet,
            [
                check.code,
                "пропущен" if check.skipped else ("ок" if check.passed else "НЕ ПРОЙДЕН"),
                check.message,
            ],
        )
    if result.validation.unknown_accounts:
        write_row(sheet, [])
        write_row(sheet, ["Счета вне справочника §3.5"], bold=True)
        for account in result.validation.unknown_accounts:
            write_row(sheet, [account])


def _sheet_ladder(workbook: Workbook, result: AnalysisResult) -> None:
    """Лист «Лестница» — §9.1.5. Несводимые остатки по дням."""
    sheet = _new_sheet(workbook, SHEETS[4])
    write_row(sheet, ["Категория", "Дата", "Остаток", "Пометка"], bold=True)
    for category, collapse in result.timing.items():
        for day, amount in collapse.residual_days:
            write_row(sheet, [category.value, day, amount, "для разбора"])
        if collapse.redated:
            write_row(
                sheet,
                [
                    category.value,
                    "",
                    "",
                    (
                        f"свёрнуто переносом даты: {collapse.redated} дн. — проход 3 "
                        "может ошибочно свести две разные операции, равные по сумме"
                    ),
                ],
            )


def _sheet_not_booked(workbook: Workbook, result: AnalysisResult) -> None:
    """Лист «Не проведено в 1С» — §9.1.6."""
    sheet = _new_sheet(workbook, SHEETS[5])
    write_row(sheet, ["Дата", "Сумма", "Строки лога", "Пометка"], bold=True)
    for item in result.localizations:
        if item.balance_impact != Decimal("0.00") or not item.ops_rows:
            continue
        write_row(
            sheet,
            [
                item.date,
                item.amount,
                ", ".join(str(row) for row in item.ops_rows),
                "на сальдо не влияет: этих проводок в 1С нет вовсе",
            ],
        )


def _sheet_repeats(workbook: Workbook, result: AnalysisResult) -> None:
    """Лист «Повторы» — §9.1.7. Базовая частота по ПКО обязательна (§8.1)."""
    sheet = _new_sheet(workbook, SHEETS[6])
    write_row(
        sheet,
        ["Код", "Дата", "Название", "Сумма", "Строки", "Контекст", "Объяснение"],
        bold=True,
    )
    for signature in result.signatures:
        write_row(
            sheet,
            [
                signature.code.value,
                signature.date,
                signature.title,
                signature.amount,
                ", ".join(str(row) for row in signature.rows),
                signature.baseline or "",
                signature.explanation,
            ],
        )


def _sheet_documents(workbook: Workbook, result: AnalysisResult) -> None:
    """Лист «Документы» — §9.1.8. Находки с трассировкой и итогами."""
    sheet = _new_sheet(workbook, SHEETS[7])
    write_row(
        sheet,
        [
            "Код",
            "Уровень",
            "Материальность",
            "Дата",
            "Сумма",
            "Влияние на сальдо",
            "Уверенность",
            "Строки 1С",
            "Строки лога",
            "Документы",
            "Объяснение",
        ],
        bold=True,
    )
    first_data_row = sheet.max_row + 1
    for finding in result.findings:
        day = finding.date[0] if isinstance(finding.date, tuple) else finding.date
        write_row(
            sheet,
            [
                finding.code.value,
                finding.severity.value,
                finding.materiality.value,
                day,
                finding.amount,
                finding.balance_impact,
                confidence_label(finding.confidence),
                ", ".join(str(row) for row in finding.ledger_rows),
                ", ".join(str(row) for row in finding.ops_rows),
                ", ".join(finding.doc_numbers),
                finding.explanation,
            ],
            fill=_SEVERITY_FILL.get(finding.severity),
        )
    last_data_row = sheet.max_row
    if last_data_row >= first_data_row:
        write_row(sheet, ["Итого", "", "", "", None, None], bold=True)
        total_row = sheet.max_row
        for column, letter in ((5, "E"), (6, "F")):
            cell = sheet.cell(row=total_row, column=column)
            cell.value = f"=SUM({letter}{first_data_row}:{letter}{last_data_row})"
            cell.number_format = NUMBER_FORMAT


def _sheet_audit(workbook: Workbook, result: AnalysisResult) -> None:
    """Лист журнала автогашений — §12, флаг ``--audit-log``."""
    sheet = _new_sheet(workbook, "Журнал гашений")
    write_row(sheet, ["Стадия", "Правило", "Строки", "Пара", "Сумма", "Примечание"], bold=True)
    for record in result.audit_log:
        write_row(
            sheet,
            [
                record.stage,
                record.rule,
                ", ".join(str(row) for row in record.subject_rows),
                ", ".join(str(row) for row in record.counterpart_rows),
                record.amount,
                record.note,
            ],
        )


def render_excel(
    result: AnalysisResult,
    path: Path,
    *,
    audit_log: bool = False,
) -> Path:
    """Собрать Excel-отчёт целиком — §9.1.

    Формулировки листов не квалифицируют находки как хищение (§1.2, §13.10):
    везде «расхождение», «требует проверки», «не локализовано».
    """
    workbook = Workbook()
    workbook.remove(workbook.worksheets[0])

    _sheet_cause(workbook, result)
    _sheet_key_documents(workbook, result)
    _sheet_balance(workbook, result)
    _sheet_reconciliation(workbook, result)
    _sheet_ladder(workbook, result)
    _sheet_not_booked(workbook, result)
    _sheet_repeats(workbook, result)
    _sheet_documents(workbook, result)
    if audit_log:
        _sheet_audit(workbook, result)

    workbook.save(path)
    workbook.close()
    return path
