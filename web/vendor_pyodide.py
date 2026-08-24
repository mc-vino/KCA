"""Привезти Pyodide к сайту — чтобы страница не зависела от чужого CDN.

Скачивать среду исполнения со стороннего CDN на каждый открытый файл кассы —
плохая идея по трём причинам, и только третья очевидна.

Первая: инструмент форензики кассы применяют внутри организации, а корпоративные
сети режут CDN куда чаще, чем собственный GitHub Pages. Страница, у которой
Pyodide не загрузился, не показывает ошибку разбора — она просто не оживает.

Вторая: версия на CDN — это строка в HTML, которую никто не проверяет. Одна
опечатка в номере, и страница мертва, причём молча и только в бою: локальная
проверка с ``?pyodide=`` пойдёт по другому пути и ничего не заметит.

Третья: воспроизводимость §13.5. Отчёт называет версию правил и хеш конфига, но
считает-то его конкретный Python с конкретным numpy. Привязать их к тому, что
CDN отдаёт сегодня, значит потерять право утверждать, что тот же вход даст тот
же выход.

Цепочка доверия — одна закреплённая сумма. Мы проверяем по списку
:data:`CORE_DIGESTS` пять файлов ядра, включая ``pyodide-lock.json``; сам lock
несёт ``sha256`` каждого пакета, и этого достаточно, чтобы проверить остальные
тридцать мегабайт, ничего больше не закрепляя вручную. Подменённый файл роняет
сборку, а не уезжает на сайт.

Список пакетов не выдуман: он раскрывается транзитивно из lock по тем, что
страница запрашивает у ``loadPackage``.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

VERSION = "0.28.3"
"""Закреплённая версия Pyodide. Меняется осознанно и вместе с суммами ниже."""

BASE = f"https://cdn.jsdelivr.net/pyodide/v{VERSION}/full/"
"""Откуда берём при сборке. Это зависимость **сборки**, а не страницы."""

WANTED = ("numpy", "scipy", "pydantic", "pyyaml", "micropip")
"""Что страница просит у ``loadPackage``; остальное раскроется по зависимостям."""

CORE_DIGESTS = {
    "pyodide.js": "24a458425dcb4ea9836eb5ce26701d18cb769374e2b79247602ba605bf093278",
    "pyodide.asm.js": "b22e5831eade9ff10e6fe2c811c68688cd91f10154377b4f80debcf5bafa1e56",
    "pyodide.asm.wasm": "5effb6a1a6cc4a1a85bec4622701aa797c031e1de923cbbaf2ad47abdc4ab325",
    "python_stdlib.zip": "71fee17f88a6260ec8c9c7c063533ee59c021fdc88a1ce76247378d3c4a35f4c",
    "pyodide-lock.json": "f6e6f42f451f42affbbcddb00e8c9a3278dcbf399f57aab9f3f568839a7ff4a6",
}
"""SHA-256 файлов ядра 0.28.3, снятые с официального релизного архива.

Проверено побайтовым сравнением с
``pyodide-0.28.3.tar.bz2`` — тот же архив, на котором прогонялась страница.
Строка ``0.28.0.dev0`` внутри lock-файла к версии отношения не имеет: это
особенность сборки апстрима, а не другой выпуск.
"""

TIMEOUT = 300
"""Секунд на файл: ``scipy`` весит 12,6 МБ, и на медленном раннере это долго."""


def _norm(name: str) -> str:
    """Имя пакета в сравнимом виде: ``typing-extensions`` и ``typing_extensions``."""
    return name.lower().replace("-", "_")


def _fetch(name: str) -> bytes:
    """Скачать один файл среды."""
    with urllib.request.urlopen(BASE + name, timeout=TIMEOUT) as response:  # noqa: S310
        return bytes(response.read())


def _verify(name: str, payload: bytes, expected: str) -> None:
    """Сверить сумму и остановить сборку при расхождении."""
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        message = f"{name}: sha256 {actual}, ожидалась {expected}"
        raise ValueError(message)


def closure(lock: dict[str, object], wanted: tuple[str, ...]) -> list[str]:
    """Раскрыть зависимости пакетов транзитивно — вернуть имена файлов.

    Считать список руками нельзя: ``scipy`` тянет ``libopenblas``, ``pydantic``
    — ``pydantic_core``, ``annotated-types`` и ``typing-extensions``. Пропущенный
    пакет проявится только в браузере и только на той стадии §5, которая до него
    доберётся.
    """
    packages = lock["packages"]
    if not isinstance(packages, dict):
        message = "в pyodide-lock.json нет раздела packages"
        raise TypeError(message)
    index = {_norm(str(item["name"])): item for item in packages.values()}

    seen: set[str] = set()
    queue = list(wanted)
    while queue:
        entry = index.get(_norm(queue.pop()))
        if entry is None or entry["name"] in seen:
            continue
        seen.add(str(entry["name"]))
        queue.extend(str(item) for item in entry.get("depends", []))

    return sorted({str(index[_norm(name)]["file_name"]) for name in seen})


def vendor(target: Path) -> int:
    """Сложить среду в ``target``. Возвращает число записанных файлов."""
    target.mkdir(parents=True, exist_ok=True)

    for name, digest in CORE_DIGESTS.items():
        payload = _fetch(name)
        _verify(name, payload, digest)
        (target / name).write_bytes(payload)
        sys.stdout.write(f"  ядро {name} — {len(payload) / 1048576:.1f} МБ\n")

    lock = json.loads((target / "pyodide-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    digests = {str(item["file_name"]): str(item["sha256"]) for item in packages.values()}

    files = closure(lock, WANTED)
    for name in files:
        payload = _fetch(name)
        _verify(name, payload, digests[name])
        (target / name).write_bytes(payload)
        sys.stdout.write(f"  пакет {name} — {len(payload) / 1048576:.1f} МБ\n")

    return len(CORE_DIGESTS) + len(files)


def main(argv: list[str]) -> int:
    """Точка входа: ``vendor_pyodide.py <каталог>``."""
    expected = 2  # имя скрипта + каталог
    if len(argv) != expected:
        sys.stdout.write(f"использование: {argv[0]} <каталог-для-pyodide>\n")
        return 2

    target = Path(argv[1])
    sys.stdout.write(f"Pyodide {VERSION} → {target}\n")
    written = vendor(target)
    total = sum(item.stat().st_size for item in target.iterdir() if item.is_file())
    sys.stdout.write(f"записано файлов: {written}, всего {total / 1048576:.1f} МБ\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
