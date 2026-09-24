/* Форма лендинга → приложение: файл доезжает через регистрацию, в НАСТОЯЩЕМ браузере.
 *
 * Зачем браузер: передача держится на трёх вещах, которых тест текста не видит
 * вовсе, — postMessage между двумя источниками, IndexedDB во ФРЕЙМЕ и то, что
 * браузер делит хранилище фрейма по САЙТУ верхнего окна. Лендинг и приложение
 * на проде — один сайт (click.simpletranslate.me и simpletranslate.me), и здесь
 * так же: два имени одного сайта `st.test`, оба смотрят на 127.0.0.1
 * (`--host-resolver-rules`). Разведи их по разным сайтам — и хранилище фрейма
 * отделилось бы от хранилища приложения, а тест честно бы это показал.
 *
 * Сценарий ровно человеческий: страница лендинга, файл в поле, язык перевода,
 * «Перевести». Браузер уходит на адрес приложения, а там страница-проверка
 * читает хранилище тем же js/handoff.js, что и настоящее приложение.
 *
 * Chrome не найден — проверка ПРОПУСКАЕТСЯ (закон tests/test_ocr_browser.js).
 */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");

const ROOT = path.join(__dirname, "..");
const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

function chrome() {
  return [
    process.env.CHROME_PATH,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
  ].filter(Boolean).find(p => { try { return fs.statSync(p).isFile(); } catch (e) { return false; } });
}
const bin = chrome();
if (!bin) {
  console.log("Chrome не найден — проверка передачи файла пропущена (путь можно задать в CHROME_PATH)");
  process.exit(0);
}

/* Один сервер на оба имени: отвечает по заголовку Host, как nginx. */
const PROBE_LANDING = `
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    var f = new File(["Первая страница документа."], "Статья.docx", { type: "application/octet-stream" });
    var dt = new DataTransfer(); dt.items.add(f);
    var inp = document.getElementById("tr-file");
    inp.files = dt.files;
    inp.dispatchEvent(new Event("change", { bubbles: true }));
    document.getElementById("tr-tgt").value = "EN";
    document.getElementById("tr").requestSubmit();
  }, 300);
});
</script>`;

const CHECK_PAGE = `<!doctype html><html><body><pre id="out">ждём</pre>
<script src="/js/handoff.js"></script>
<script>
MCT_HANDOFF.peek().then(function (r) {
  var q = new URLSearchParams(location.search);
  var out = ["query=" + q.get("start") + "," + q.get("src") + "," + q.get("tgt") + "," + q.get("lang")];
  if (!r) out.push("file=none");
  else {
    out.push("file=" + r.name + "," + r.file.size + "," + r.src + "," + r.tgt);
    return r.file.text().then(function (t) { out.push("text=" + t); report("ГОТОВО " + out.join(" | ")); });
  }
  report("ГОТОВО " + out.join(" | "));
}, function (e) { report("СБОЙ " + e); });
function report(t) { document.getElementById("out").textContent = t; fetch("/result", { method: "POST", body: t }); }
</script></body></html>`;

let PORT = 0;
const server = http.createServer((req, res) => {
  const host = (req.headers.host || "").split(":")[0];
  const url = new URL(req.url, "http://x");
  const landingOrigin = "http://click.st.test:" + PORT, appOrigin = "http://st.test:" + PORT;
  const send = (code, type, body, extra) => { res.writeHead(code, Object.assign({ "Content-Type": type }, extra || {})); res.end(body); };
  if (host === "click.st.test") {
    // Собранная страница как есть; подменяется только адрес приложения —
    // прод-адрес из теста недостижим, а устройство передачи то же.
    let html = fs.readFileSync(path.join(ROOT, "landing", "index.html"), "utf8");
    html = html.split("https://simpletranslate.me").join(appOrigin);
    html = html.replace("</body>", PROBE_LANDING + "</body>");
    return send(200, "text/html; charset=utf-8", html);
  }
  if (host === "st.test") {
    if (url.pathname === "/result") {
      let b = ""; req.on("data", d => { b += d; }); req.on("end", () => { send(200, "text/plain", "ok"); finish(b); });
      return;
    }
    if (url.pathname === "/handoff") {
      // Та же страница и тот же заголовок, что отдаёт main.py.
      const html = fs.readFileSync(path.join(ROOT, "frontend", "handoff.html"), "utf8")
        .replace("__ORIGINS__", JSON.stringify([landingOrigin]));
      return send(200, "text/html; charset=utf-8", html,
        { "Content-Security-Policy": "default-src 'none'; script-src 'self' 'unsafe-inline'; frame-ancestors " + landingOrigin });
    }
    if (url.pathname === "/js/handoff.js")
      return send(200, "text/javascript", fs.readFileSync(path.join(ROOT, "frontend", "js", "handoff.js")));
    if (url.pathname === "/") return send(200, "text/html; charset=utf-8", CHECK_PAGE);
  }
  send(404, "text/plain", "nf");
});

let ch = null, prof = null, done = false;
function finish(got) {
  if (done) return;
  done = true;
  if (ch) ch.kill();
  server.close();
  console.log("  страница приложения: " + (got || "(не открылась)"));
  check(got.startsWith("ГОТОВО"), "браузер ушёл с лендинга в приложение");
  check(got.includes("query=translate,RU,EN,ru"), "пара языков и язык страницы доехали адресом");
  check(got.includes("file=Статья.docx,") && got.includes(",RU,EN"), "файл лежит в хранилище приложения с парой языков");
  check(got.includes("text=Первая страница документа."), "содержимое файла доехало без потерь");
  console.log(fail.length ? "ПРОВАЛЕНО: " + fail.join("; ") : "ВСЁ ПРОШЛО");
  setTimeout(() => {
    try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) { /* профиль держит браузер */ }
    process.exit(fail.length ? 1 : 0);
  }, 500);
}

server.listen(0, "127.0.0.1", () => {
  PORT = server.address().port;
  prof = fs.mkdtempSync(path.join(os.tmpdir(), "mct-hf-"));
  // Браузер живёт, пока страница приложения не пришлёт ответ (/result);
  // окна для этого не нужно — достаточно порта отладки, который держит его открытым.
  const args = ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--user-data-dir=" + prof, "--host-resolver-rules=MAP *.st.test 127.0.0.1, MAP st.test 127.0.0.1",
    "--remote-debugging-port=0", "http://click.st.test:" + PORT + "/"];
  // spawn, а не spawnSync: сервер живёт в этом же процессе (заметка про node + headless).
  ch = spawn(bin, args);
  setTimeout(() => finish(""), 40000);
});
