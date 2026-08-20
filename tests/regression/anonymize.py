"""Обезличивание калибровочных выгрузок — §11.3.

Блок РКО содержит ФИО получателей (§3.6, кейс «Правосуд Дмитрий»), блок ПКО —
ФИО плательщиков. В открытый репозиторий такие файлы класть нельзя, а без них
регрессия §11.3 пропускается и перестаёт защищать разбор реальных данных.

Скрипт заменяет ФИО устойчивыми псевдонимами так, чтобы **результат конвейера
не изменился ни на копейку**. Для этого достаточно сохранить три свойства — и
ровно три:

1. **Совпадение с ``patterns.central_cash``** («ентральн»): §3.6 по нему
   отличает инкассацию от возврата клиенту.
2. **Совпадение с ``patterns.service_recipients``**: §3.6 по нему отделяет служебные
   выдачи (суд, архив, финконтроль), которым не соответствуют проводки 1С.
3. **Тождество и различие имён**: §8.1 группирует повторы по паре
   «получатель + сумма», и склейка двух разных клиентов в одно имя создала бы
   несуществующий повтор.

Оба класса из пунктов 1–2 на калибровочных кассах — организационные единицы, а
не люди («Центральная касса РПВЗ», «СУД ПВЗ Солигорск», «АРХИВ ПВЗ Солигорск
PAX 119011650», «Финконтроль»), поэтому они переносятся дословно.

Чего сохранять **не** нужно
---------------------------
Длину строки и коллизии Jaro-Winkler. `tests/regression/fixtures/README.md`
требовал этого, ссылаясь на §5.9.2, но проход 2 (венгерский алгоритм) в §5.9.2
назван опциональным и в конвейере не включён: :func:`name_similarity`
вызывается только из :func:`hungarian_match`, а тот не вызывается ниоткуда.
Единственное активное сопоставление — :func:`greedy_match` по точной сумме в
окне ``DATE_WIN``, имена ему не нужны.

Проверка результата — не «на глаз»: после прогона снапшоты §11.3 обязаны
совпасть без обновления. Разошлись — значит замена задела что-то, кроме имён.

Запуск::

    uv run python tests/regression/anonymize.py <каталог-с-выгрузками> <куда>
"""

from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
from openpyxl.cell.cell import Cell, MergedCell

from cashforensics.classify import is_central_cash, is_service_recipient
from cashforensics.ingest import ingest
from cashforensics.models import Config, load_config
from cashforensics.normalize import clean_text

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.yaml"

_GENERIC = ("клиент",)
"""Обобщённые подписи, за которыми нет конкретного человека."""


def is_personal(name: str, config: Config) -> bool:
    """Стоит ли за подписью конкретное лицо — то, что подлежит замене."""
    if not name.strip():
        return False
    if is_central_cash(name, config.patterns.central_cash):
        return False
    if is_service_recipient(name, config.patterns.service_recipients):
        return False
    return name.strip().lower() not in _GENERIC


def pseudonym(index: int) -> str:
    """Псевдоним по порядковому номеру — устойчив и не задевает §3.6.

    Ни «ентральн», ни служебные шаблоны в него не попадают по построению.
    """
    return f"Получатель {index:05d}"


_NAME_HEADERS = ("кому выдано", "от кого принято")
"""Заголовки колонок ФИО — §3.3. Ниже них начинаются данные."""


def _first_data_row(cells: list[Cell | MergedCell]) -> int:
    """Индекс первой строки данных — сразу под заголовком колонки.

    Заголовок трогать нельзя: §3.3 ищет блоки опер-лога **по заголовкам, а не
    по фиксированным индексам**, и подмена «Кому выдано» псевдонимом убирает
    блок целиком. На `Кса_норма` это обнулило обороты лога и сделало обе
    категории неверифицируемыми — при том что сумма замен выглядела правдоподобно.
    """
    for index, cell in enumerate(cells):
        # Через `clean_text` §5.2: на Солигорске заголовок написан неразрывными
        # пробелами («От\xa0кого\xa0принято»), и сравнение по сырой строке его
        # не узнаёт.
        if clean_text(cell.value).lower() in _NAME_HEADERS:
            return index + 1
    message = "заголовок колонки ФИО не найден: замена вслепую запрещена"
    raise ValueError(message)


def anonymize_sheet(path: Path, target: Path, config: Config) -> tuple[int, int]:
    """Обезличить один файл; вернуть ``(заменено ячеек, разных имён)``.

    Читается с ``data_only=True``: в фикстуре нужны значения, а не формулы —
    иначе `openpyxl` сохранит формулы без кэша, и `ingest` прочитает пустоту.
    """
    layout = ingest(path, config).layout
    columns = [
        block[2] + 1
        for block in (layout.rko, layout.pko)
        if block is not None and block[2] is not None
    ]
    workbook = openpyxl.load_workbook(path, data_only=True)
    sheet = workbook.worksheets[0]

    names: dict[str, str] = {}
    replaced = 0
    for column in columns:
        cells = [cell for (cell,) in sheet.iter_rows(min_col=column, max_col=column)]
        start = _first_data_row(cells)
        for cell in cells[start:]:
            value = cell.value
            if not isinstance(value, str) or not is_personal(value, config):
                continue
            if value not in names:
                names[value] = pseudonym(len(names) + 1)
            cell.value = names[value]
            replaced += 1

    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)
    workbook.close()
    return (replaced, len(names))


def main(argv: list[str]) -> int:
    """Обезличить все выгрузки каталога."""
    expected = 3  # имя скрипта + два пути
    if len(argv) != expected:
        sys.stdout.write(f"использование: {argv[0]} <каталог-источник> <каталог-назначение>\n")
        return 2
    source, destination = Path(argv[1]), Path(argv[2])
    config = load_config(CONFIG_PATH)
    for path in sorted(source.glob("*.xlsx")):
        replaced, unique = anonymize_sheet(path, destination / path.name, config)
        sys.stdout.write(f"{path.name}: заменено {replaced} ячеек, разных имён {unique}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
