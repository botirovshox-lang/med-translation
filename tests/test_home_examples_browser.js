/* Блок «Примеры работ» на /start/ в НАСТОЯЩЕМ браузере: стрелки и точки
 * по центру, примеры листаются сами (иначе не видно, что их четыре).
 *
 * Проверяется: точек столько же, сколько вкладок; карточка на экране —
 * через шаг автолистания выбран следующий пример, ещё через шаг — третий;
 * нажатие на точку выбирает её пример и останавливает автолистание
 * насовсем; стрелки листают по кругу; подпись стрелки переводится.
 *
 * Chrome не найден — проверка пропускается, а не проваливается.
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
const bin = [
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
].filter(Boolean).find(p => { try { return fs.statSync(p).isFile(); } catch (e) { return false; } });

if (!bin) {
  console.log("Chrome не найден — проверка блока примеров пропущена (CHROME_PATH)");
  process.exit(0);
}

const PROBE = `
<script>
window.addEventListener("load", function () {
  var out = [];
  function say(k, v) { out.push(k + "=" + v); }
  function sel() {
    var t = [].filter.call(document.querySelectorAll(".tab"), function (b) { return b.getAttribute("aria-selected") === "true"; })[0];
    return t ? t.getAttribute("data-k") : "";
  }
  var stage = document.querySelector(".ex-stage");
  stage.scrollIntoView({ block: "center", behavior: "instant" });
  var dots = document.getElementById("ex-dots");
  say("dots", dots.children.length + "/" + document.querySelectorAll(".tab").length);
  say("t0", sel());
  setTimeout(function () {
    say("t1", sel());
    setTimeout(function () {
      say("t2", sel());
      dots.children[0].click();
      say("dot", sel() + ":" + dots.children[0].getAttribute("aria-current"));
      setTimeout(function () {
        say("stopped", sel());
        document.getElementById("ex-prev").click();
        say("prev", sel());
        document.getElementById("ex-next").click();
        say("next", sel());
        say("lblRu", document.getElementById("ex-next").getAttribute("aria-label"));
        var fr = document.createElement("iframe"); fr.src = "/en/";
        fr.onload = function () {
          setTimeout(function () {
            say("lblEn", fr.contentDocument.getElementById("ex-next").getAttribute("aria-label"));
            var d = document.createElement("div"); d.id = "_probe"; d.textContent = out.join("|");
            document.body.appendChild(d);
          }, 800);
        };
        document.body.appendChild(fr);
      }, 7000);
    }, 3000);
  }, 3300);
});
</script>`;

const server = http.createServer((req, res) => {
  let rel = decodeURIComponent(req.url.split("?")[0]);
  if (rel.endsWith("/")) rel += "index.html";
  const file = path.join(LANDING, rel.replace(/^\/+/, ""));
  if (!file.startsWith(LANDING) || !fs.existsSync(file)) { res.writeHead(404); res.end("no"); return; }
  let body = fs.readFileSync(file);
  if (file.endsWith(".html")) body = Buffer.from(body.toString("utf8").replace("</body>", PROBE + "</body>"), "utf8");
  res.writeHead(200, { "Content-Type": file.endsWith(".html") ? "text/html; charset=utf-8"
    : file.endsWith(".webp") ? "image/webp" : "application/octet-stream" });
  res.end(body);
});

server.listen(0, "127.0.0.1", () => {
  const port = server.address().port;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "phchrome-"));
  const proc = spawn(bin, ["--headless=new", "--disable-gpu", "--window-size=1400,1000", "--no-sandbox", "--no-first-run",
    "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
    "--user-data-dir=" + profile, "--virtual-time-budget=30000", "--dump-dom",
    `http://127.0.0.1:${port}/`]);
  let dom = "";
  proc.stdout.on("data", b => { dom += b.toString("utf8"); });
  const killer = setTimeout(() => { try { proc.kill(); } catch (e) {} }, 60000);
  proc.on("close", () => {
    clearTimeout(killer);
    server.close();
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) {}
    const mm = /<div id="_probe">([^<]*)<\/div>/.exec(dom);
    const kv = {};
    if (mm) mm[1].split("|").forEach(p => { const i = p.indexOf("="); kv[p.slice(0, i)] = p.slice(i + 1); });
    check(!!mm, "скрипт страницы отработал");
    check(kv.dots === "4/4", "точек столько же, сколько примеров: " + kv.dots);
    check(kv.t0 === "book", "первый пример — книга: " + kv.t0);
    check(kv.t1 === "paper", "через шаг — следующий пример сам: " + kv.t1);
    check(kv.t2 === "video", "ещё через шаг — третий: " + kv.t2);
    check(kv.dot === "book:true", "точка выбирает свой пример: " + kv.dot);
    check(kv.stopped === "book", "после нажатия автолистание стоит: " + kv.stopped);
    check(kv.prev === "scan", "стрелка назад — по кругу: " + kv.prev);
    check(kv.next === "book", "стрелка вперёд: " + kv.next);
    check(kv.lblRu && kv.lblEn && kv.lblRu !== kv.lblEn, "подпись стрелки переводится: " + kv.lblRu + " → " + kv.lblEn);
    console.log(fail.length ? "ПРОВАЛЕНО: " + fail.length : "ВСЁ ПРОШЛО");
    process.exit(fail.length ? 1 : 0);
  });
});
