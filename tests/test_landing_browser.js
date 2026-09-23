/* Лендинг в НАСТОЯЩЕМ браузере: линза переключает пару, а разметка жива.
 *
 * Зачем браузер, когда есть tests/test_landing.py: тот читает собранный
 * HTML как текст и про скрипт не знает ничего. А линза — это ровно скрипт:
 * абзацы обеих сторон рисуются из window.LENS_PAIRS при загрузке, метка
 * на кольце берётся из data-code, кнопки выбора заводятся в цикле.
 * Сломай любое из трёх — страница соберётся, тест сборки промолчит,
 * а человек увидит пустую белую карточку вместо примера перевода.
 *
 * Chrome не найден — проверка ПРОПУСКАЕТСЯ, а не проваливается: чужая
 * машина без браузера это не сломанный лендинг (тот же закон, что
 * в tests/test_ocr_browser.js).
 */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");

const ROOT = path.join(__dirname, "..");
const LANDING = path.join(ROOT, "landing");

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
  ].filter(Boolean).find(p => {
    try { return fs.statSync(p).isFile(); } catch (e) { return false; }
  });
}

const bin = chrome();
if (!bin) {
  console.log("Chrome не найден — проверка лендинга в браузере пропущена "
    + "(путь можно задать в CHROME_PATH)");
  process.exit(0);
}

/* Что спрашиваем у страницы. Результат пишется в #_probe, и его забирает
   --dump-dom: отдельного канала связи с headless-браузером у нас нет. */
const PROBE = `
<script>
window.addEventListener("load", function () {
  /* Кадр после load: пары рисуются синхронно при выполнении скрипта тела,
     но кнопка выбора нажимается уже по готовой разметке. */
  setTimeout(function () {
    var out = [], pick = document.getElementById("lens-pick");
    var src = document.getElementById("lens-src"), tgt = document.getElementById("lens-tgt");
    var ring = document.getElementById("lens-ring");
    function say(k, v) { out.push(k + "=" + v); }
    say("pairs", window.LENS_PAIRS ? window.LENS_PAIRS.length : 0);
    say("buttons", pick ? pick.children.length : 0);
    say("srcParas", src ? src.children.length : 0);
    say("tgtParas", tgt ? tgt.children.length : 0);
    say("srcText", src ? src.textContent.replace(/\\s+/g, " ").trim().slice(0, 60) : "");
    say("tgtText", tgt ? tgt.textContent.replace(/\\s+/g, " ").trim().slice(0, 60) : "");
    say("code0", ring ? ring.getAttribute("data-code") : "");
    say("pressed0", pick ? pick.children[0].getAttribute("aria-pressed") : "");
    /* Переключаем на ПОСЛЕДНЮЮ пару и смотрим, изменилось ли всё,
       что обязано измениться: обе стороны, метка кольца и нажатая кнопка. */
    if (pick && pick.children.length > 1) {
      var last = pick.children.length - 1;
      pick.children[last].click();
      say("srcAfter", src.textContent.replace(/\\s+/g, " ").trim().slice(0, 60));
      say("tgtAfter", tgt.textContent.replace(/\\s+/g, " ").trim().slice(0, 60));
      say("codeAfter", ring.getAttribute("data-code"));
      say("pressedLast", pick.children[last].getAttribute("aria-pressed"));
      say("pressed0After", pick.children[0].getAttribute("aria-pressed"));
      say("srcLangAfter", src.getAttribute("lang") || "");
    }
    /* Демо-плеер: он рисует строки сам, и пустой #docpane означает
       сломанный скрипт страницы целиком. */
    var pane = document.getElementById("docpane");
    say("docRows", pane ? pane.children.length : 0);
    var d = document.createElement("div");
    d.id = "_probe"; d.textContent = out.join("|");
    document.body.appendChild(d);
  }, 400);
});
</script>`;

/* Локальный сервер: страница грузит шрифты с чужого хоста, и без сети
   она всё равно рисуется — нам важен только свой скрипт. */
const server = http.createServer((req, res) => {
  let rel = decodeURIComponent(req.url.split("?")[0]);
  if (rel.endsWith("/")) rel += "index.html";
  const file = path.join(LANDING, rel.replace(/^\/+/, ""));
  if (!file.startsWith(LANDING) || !fs.existsSync(file)) {
    res.writeHead(404); res.end("no"); return;
  }
  let body = fs.readFileSync(file);
  if (file.endsWith(".html")) {
    body = Buffer.from(body.toString("utf8").replace("</body>", PROBE + "</body>"), "utf8");
  }
  res.writeHead(200, { "Content-Type": file.endsWith(".html")
    ? "text/html; charset=utf-8" : "application/octet-stream" });
  res.end(body);
});

const PAGES = ["/", "/uz/", "/en/"];
const results = {};

function ask(port, page) {
  return new Promise((done) => {
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), "lndchrome-"));
    const proc = spawn(bin, [
      "--headless=new", "--disable-gpu", "--no-sandbox",
      "--no-first-run", "--no-default-browser-check",
      "--disable-background-networking", "--disable-component-update",
      "--user-data-dir=" + profile,
      "--virtual-time-budget=20000", "--dump-dom",
      `http://127.0.0.1:${port}${page}`,
    ]);
    let dom = "";
    proc.stdout.on("data", (b) => { dom += b.toString("utf8"); });
    const killer = setTimeout(() => { try { proc.kill(); } catch (e) {} }, 60000);
    proc.on("close", () => {
      clearTimeout(killer);
      try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) {}
      const m = /<div id="_probe">([^<]*)<\/div>/.exec(dom);
      const kv = {};
      if (m) m[1].split("|").forEach(p => {
        const i = p.indexOf("=");
        kv[p.slice(0, i)] = p.slice(i + 1);
      });
      results[page] = { dom: dom.trim().length, kv };
      done();
    });
  });
}

server.listen(0, "127.0.0.1", async () => {
  const port = server.address().port;
  for (const p of PAGES) await ask(port, p);
  server.close();

  const any = PAGES.some(p => results[p].dom > 0);
  if (!any) {
    console.log("Браузер ничего не отдал — проверка не состоялась "
      + "(это не провал лендинга; попробуйте другой CHROME_PATH)");
    process.exit(0);
  }

  for (const page of PAGES) {
    const r = results[page], kv = r.kv;
    console.log("=== " + page + " ===");
    if (!r.dom) { check(false, page + ": браузер не отдал страницу"); continue; }
    check(Object.keys(kv).length > 0, page + ": скрипт страницы отработал");
    if (!Object.keys(kv).length) continue;

    check(+kv.pairs >= 3, page + ": пары линзы доехали (" + kv.pairs + ")");
    check(+kv.buttons === +kv.pairs, page + ": кнопок выбора столько же, сколько пар");
    /* Абзацы рисует скрипт: пустая карточка — это сломанная линза,
       и тест сборки её не увидит. */
    check(+kv.srcParas >= 3 && +kv.tgtParas >= 3,
      page + ": обе стороны нарисованы (" + kv.srcParas + "/" + kv.tgtParas + ")");
    check(kv.srcText.length > 20 && kv.tgtText.length > 20, page + ": в линзе есть текст");
    check(kv.srcText !== kv.tgtText, page + ": оригинал и перевод различаются");
    check(!!kv.code0, page + ": метка кольца проставлена (" + kv.code0 + ")");
    check(kv.pressed0 === "true", page + ": первая пара отмечена нажатой");

    /* Главное обещание: выбрал язык — увидел ИМЕННО его. */
    check(kv.srcAfter !== kv.srcText || kv.tgtAfter !== kv.tgtText,
      page + ": переключение пары меняет текст в линзе");
    check(kv.tgtAfter !== kv.tgtText, page + ": сторона перевода сменилась");
    check(kv.pressedLast === "true" && kv.pressed0After === "false",
      page + ": нажатой отмечена ровно одна кнопка");
    check(!!kv.srcLangAfter, page + ": у куска документа объявлен свой язык");
    /* Плеер — тот же скрипт страницы: пустой список строк означает,
       что он упал раньше линзы. */
    check(+kv.docRows > 0, page + ": демо-плеер нарисовал строки");
  }

  if (fail.length) {
    console.log("\nПРОВАЛЕНО: " + fail.length);
    fail.forEach(f => console.log("  - " + f));
    process.exit(1);
  }
  console.log("\nВСЁ ПРОШЛО");
});
