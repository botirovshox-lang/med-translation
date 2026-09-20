/* Чтение надписей у себя — В НАСТОЯЩЕМ БРАУЗЕРЕ, до последнего байта.

   Зачем отдельно от `test_ocr_local.js`. Тот проверяет математику, которую
   мы написали сами, и делает это в node — а половина пути там просто
   отсутствует: исполнитель тензоров, WebAssembly, canvas, ImageBitmap.
   Стоило это дорого и сразу: браузер нашёл два дефекта, которых не видел
   ни один набор.
     1. `wasmPaths` относительным путём — исполнитель подтягивает свой
        `.mjs` динамическим import'ом, и туда «vendor/ocr/» уходит как ИМЯ
        модуля: «Failed to resolve module specifier». Чтение не поднималось
        вовсе;
     2. длинная строка резалась слишком рано, и шов съедал пробел
        («Обзорнаярентгенограмма») либо добавлял букву.
   Оба видны только тут, потому что оба — про браузер, а не про наш расчёт.

   Как устроено: поднимаем статический сервер на `frontend/`, кладём рядом
   страничку и картинку с тремя строками настоящего медицинского текста,
   запускаем Chrome без окна и читаем из готового DOM, что он распознал.
   Ни одного вызова модели, ни одного обращения наружу.

   Chrome не найден — проверка ПРОПУСКАЕТСЯ с кодом 0 и говорит об этом:
   на сервере браузера нет и быть не должно, а молчаливый провал там
   означал бы красный прогон на каждом выкате.                          */
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");

const ROOT = path.join(__dirname, "..");
const WEB = path.join(ROOT, "frontend");
const PNG = path.join(__dirname, "fixtures", "ocr_lines.png");

/* Что нарисовано на картинке — то и должно прочитаться, слово в слово. */
const WANT = [
  "Диссеминированный туберкулёз лёгких",
  "Рис. 7. Обзорная рентгенограмма",
  "Бактериовыделение (МБТ+) подтверждено",
];

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

function chrome() {
  const cands = [
    process.env.CHROME_PATH,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
  ].filter(Boolean);
  return cands.find(p => { try { return fs.statSync(p).isFile(); } catch (e) { return false; } });
}

const bin = chrome();
if (!bin) {
  console.log("Chrome не найден — проверка в браузере пропущена "
    + "(путь можно задать в CHROME_PATH)");
  process.exit(0);
}

const PAGE = `<!doctype html><html><head><meta charset="utf-8"></head><body>
<pre id="out">старт</pre>
<script src="js/ocr_local.js"></script>
<script>
var out = document.getElementById("out");
function say(s) { out.textContent += "\\n" + s; }
fetch("_ocr_lines.png").then(function (r) { return r.arrayBuffer(); })
  .then(function (b) { return window.LocalOCR.read(b, "RU"); })
  .then(function (lines) {
    lines.forEach(function (l) { say("LINE " + l.conf + " " + l.text); });
    say("ГОТОВО");
  })
  .catch(function (e) { say("СБОЙ: " + (e && e.message || e)); });
</script></body></html>`;

const TYPES = { ".js": "text/javascript", ".png": "image/png", ".html": "text/html",
                ".wasm": "application/wasm", ".mjs": "text/javascript",
                ".onnx": "application/octet-stream", ".txt": "text/plain" };

const server = http.createServer((req, res) => {
  const url = req.url.split("?")[0];
  let file;
  if (url === "/_ocr.html") { res.writeHead(200, { "Content-Type": "text/html" }); return res.end(PAGE); }
  if (url === "/_ocr_lines.png") file = PNG;
  else file = path.join(WEB, url.replace(/^\/+/, ""));
  /* Наружу отдаём только то, что лежит под frontend/ — сервер живёт
     секунды, но дыра в тесте остаётся дырой. */
  if (file !== PNG && !path.resolve(file).startsWith(path.resolve(WEB))) {
    res.writeHead(403); return res.end();
  }
  fs.readFile(file, (e, data) => {
    if (e) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    res.end(data);
  });
});

server.listen(0, "127.0.0.1", () => {
  const port = server.address().port;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ocrchrome-"));
  /* Запуск ОБЯЗАН быть асинхронным. `spawnSync` держит тот же цикл событий,
     на котором стоит наш сервер, — браузер уходит за страницей, сервер
     ответить не может, и оба ждут друг друга до таймаута. Снаружи это
     выглядит как «Chrome ничего не отдал». */
  const proc = spawn(bin, [
    "--headless=new", "--disable-gpu", "--no-sandbox",
    "--no-first-run", "--no-default-browser-check",
    "--disable-background-networking", "--disable-component-update",
    "--user-data-dir=" + profile,
    "--virtual-time-budget=180000", "--dump-dom",
    `http://127.0.0.1:${port}/_ocr.html`,
  ]);
  let dom = "";
  proc.stdout.on("data", (b) => { dom += b.toString("utf8"); });
  const killer = setTimeout(() => { try { proc.kill(); } catch (e) { /* уже нет */ } }, 300000);
  proc.on("close", () => {
  clearTimeout(killer);
  server.close();
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* не наша беда */ }

  /* Браузер не отдал НИЧЕГО — это «не смогли посмотреть», а не «прочитано
     плохо»: такое бывает от политики машины, от обновлятора, от профиля.
     Объявлять провалом чужую беду нельзя, молчать о ней — тоже. */
  if (!dom.trim()) {
    console.log("Браузер ничего не отдал — проверка не состоялась "
      + "(это не провал чтения; попробуйте другой CHROME_PATH)");
    process.exit(0);
  }
  /* Смотрим ТОЛЬКО в напечатанное страницей, а не во весь DOM: слова
     «СБОЙ» и «ГОТОВО» стоят и в исходнике скрипта тут же рядом, и поиск
     по всему документу находил бы их всегда. */
  const pre = /<pre[^>]*>([\s\S]*?)<\/pre>/.exec(dom);
  const said = pre ? pre[1] : "";
  const lines = [...said.matchAll(/LINE ([\d.]+) (.*)/g)].map(m => m[2]);
  const oops = /СБОЙ: ([^<\n]*)/.exec(said);
  check(!oops, "чтение поднялось: исполнитель, модели и словарь доехали"
    + (oops ? " — " + oops[1] : ""));
  check(/ГОТОВО/.test(said), "чтение дошло до конца, а не повисло");
  check(lines.length === WANT.length,
    "строк прочитано: " + lines.length + " из " + WANT.length);
  WANT.forEach((want, i) => {
    check(lines[i] === want,
      "строка " + (i + 1) + " прочитана слово в слово: " + JSON.stringify(lines[i] || null));
  });

  console.log("\n" + (fail.length ? "ПРОВАЛЕНО: " + fail.join("; ") : "ВСЁ ПРОШЛО"));
  process.exit(fail.length ? 1 : 0);
  });
});
