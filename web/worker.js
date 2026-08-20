// Конвейер §5 исполняется здесь, а не в главном потоке страницы.
//
// Причина не в архитектурной чистоте. Pyodide — обычный синхронный код: пока
// он считает, главный поток не перерисовывает ничего. Разбор Солигорска
// (82 611 строк карточки, 108 локализаций с перестановочными тестами §7.3)
// занимает около семидесяти секунд, и всё это время вкладка неотличима от
// зависшей — браузер успевает предложить её закрыть. Полосу хода в таком
// режиме нарисовать нельзя в принципе: сообщения о стадиях записались бы в
// DOM, но ни одно не попало бы на экран до самого конца.
//
// Воркер решает обе задачи разом: главный поток остаётся живым, а стадии §5
// приходят сообщениями по мере прохождения.
//
// Данные кассы отсюда никуда не уходят. Воркер делает ровно три сетевых
// запроса — за Pyodide, колёсами и конфигурацией §6, — и все три происходят до
// того, как страница увидит файл. Сама выгрузка приходит из главного потока
// буфером и живёт только в памяти (§3.6: блок РКО содержит ФИО получателей).

// Воркер классический, а не модульный (`type: "module"`), хотя модульный
// выглядел бы современнее. Модульные воркеры появились в Firefox только в 114
// и в Safari в 15 — на всём, что старше, страница молча не поднималась бы
// вовсе. `importScripts` работает везде, а Pyodide отдаёт классическую сборку
// `pyodide.js` рядом с `pyodide.mjs`.

let pyodide = null;

const post = (message) => self.postMessage(message);
const log = (line) => post({ type: "log", line });

/** Поднять окружение: Pyodide, колёса, конфигурация §6, модуль `runner`. */
async function boot(pyodideBase) {
  log("Загружаем Pyodide…");
  self.importScripts(pyodideBase + "pyodide.js");
  pyodide = await self.loadPyodide({ indexURL: pyodideBase });

  log("Ставим numpy, scipy, pydantic, pyyaml…");
  await pyodide.loadPackage(["numpy", "scipy", "pydantic", "pyyaml", "micropip"]);

  // Все недостающие колёса лежат рядом со страницей: сайт не зависит ни от
  // PyPI, ни от чужого CDN, и работает в закрытом контуре.
  log("Ставим openpyxl, ruptures, cashforensics…");
  const micropip = pyodide.pyimport("micropip");
  const wheels = await (await fetch("wheels/index.json")).json();
  for (const name of wheels.install) {
    // deps:false — порядок установки задан в index.json явно. Разрешение
    // зависимостей по метаданным увело бы micropip в PyPI за rapidfuzz,
    // которого под wasm не существует; см. web/wheel_index.py.
    //
    // callKwargs — иначе объект уходит в позиционный `keep_going`, а не в
    // `deps`, и micropip всё равно идёт в PyPI.
    await micropip.install.callKwargs(new URL("wheels/" + name, self.location.href).href, {
      deps: false,
    });
  }

  log("Кладём конфигурацию §6…");
  pyodide.FS.mkdirTree("/config");
  for (const name of ["default.yaml", "holidays_by.yaml"]) {
    const text = await (await fetch("config/" + name)).text();
    pyodide.FS.writeFile("/config/" + name, text);
  }

  const runner = await (await fetch("runner.py")).text();
  pyodide.FS.writeFile("/runner.py", runner);
  await pyodide.runPythonAsync("import sys; sys.path.insert(0, '/'); import runner");

  post({ type: "ready", total: pyodide.runPython("import runner; runner.TOTAL_STAGES") });
}

/** Разобрать выгрузку. Возвращает сводку страницы одной строкой JSON. */
async function analyze({ name, buffer, target }) {
  const onStage = (number, title) => post({ type: "stage", number, title });
  pyodide.globals.set("_name", name);
  pyodide.globals.set("_data", new Uint8Array(buffer));
  pyodide.globals.set("_target", target || "");
  pyodide.globals.set("_on_stage", onStage);
  // json.dumps на стороне Python: суммы уже строки (§2 — Decimal строкой), и
  // через границу идёт текст, а не объект с прокси на каждое поле.
  const payload = await pyodide.runPythonAsync(
    "import runner, json; json.dumps(" +
      "runner.analyze_bytes(_name, bytes(_data), _target, _on_stage), ensure_ascii=False)",
  );
  post({ type: "result", payload });
}

self.onmessage = async (event) => {
  const message = event.data;
  try {
    if (message.type === "boot") {
      await boot(message.pyodideBase);
    } else if (message.type === "analyze") {
      await analyze(message);
    }
  } catch (error) {
    post({ type: "error", phase: message.type, message: String(error) });
  }
};
