"""Составить `wheels/index.json` — порядок установки колёс для страницы.

Порядок важен: `micropip` ставит колесо из указанного URL, но зависимости
разрешает по метаданным. `openpyxl` требует `et_xmlfile`, `cashforensics` —
`openpyxl` и `ruptures`. Если поставить их не в порядке зависимостей, micropip
попытается достать недостающее из PyPI, и страница перестанет работать в
закрытом контуре — молча, потому что в открытом всё соберётся.

Список формируется из того, что реально лежит в каталоге: пропущенное колесо
даёт ошибку сразу, а не догадку о том, что «наверное, поставится из сети».
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORDER = (
    # Дерево `typer`: пакет импортирует CLI в своём ``__init__``, поэтому в
    # браузере он нужен целиком, хотя команд §10 там никто не вызывает.
    "mdurl",
    "markdown_it_py",
    "pygments",
    "rich",
    "shellingham",
    "annotated_doc",
    "typer",
    # Чтение выгрузки §5.1.
    "et_xmlfile",
    "openpyxl",
    # Детектор разладки §5.8.4 — чисто-питоновая сборка, см. README рядом.
    "ruptures",
    # Сам пакет — последним: к этому моменту все его зависимости на месте.
    "cashforensics",
)
"""Порядок установки — от листьев дерева зависимостей к корню.

``numpy``, ``scipy``, ``pydantic``, ``pyyaml`` и ``click`` берутся из
дистрибутива Pyodide и сюда не входят. ``rapidfuzz`` не входит намеренно: он
объявлен зависимостью пакета, но в браузере не нужен — единственный его вызов
живёт в :func:`name_similarity`, а тот вызывается только из неиспользуемого
:func:`hungarian_match` (§5.9.2, проход 2 опционален). Поэтому колёса ставятся
с ``deps=False``: разрешение зависимостей по метаданным утащило бы страницу в
PyPI за бинарным колесом, которого для wasm не существует.
"""


def build(directory: Path) -> dict[str, list[str]]:
    """Собрать список колёс в порядке зависимостей."""
    present = {path.name.split("-")[0]: path.name for path in directory.glob("*.whl")}
    missing = [name for name in ORDER if name not in present]
    if missing:
        message = f"в {directory} нет колёс: {', '.join(missing)}"
        raise FileNotFoundError(message)
    return {"install": [present[name] for name in ORDER]}


def main(argv: list[str]) -> int:
    """Записать `index.json` рядом с колёсами."""
    expected = 2  # имя скрипта + каталог
    if len(argv) != expected:
        sys.stdout.write(f"использование: {argv[0]} <каталог-с-колёсами>\n")
        return 2
    directory = Path(argv[1])
    payload = build(directory)
    (directory / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    sys.stdout.write("порядок установки: " + " → ".join(payload["install"]) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
