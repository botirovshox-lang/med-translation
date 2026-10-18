/* Карусель «Фото» на главной в НАСТОЯЩЕМ браузере.
 *
 * Слайды, стрелки, кнопки языков и подписи рисует скрипт страницы — тест
 * сборки (`test_landing.py`) про него не знает ничего. Здесь проверяется:
 * пять слайдов и пять точек; стрелка «дальше» меняет исходник, пропорции
 * и набор языков; картинка КАЖДОГО исходника и перевода из списка слайда
 * загружается (битая ссылка — пустая карточка у человека); подпись слайда
 * переводится вместе со страницей.
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

/* Список картинок карусели — из самой страницы (SC_SLIDES): проверяем то,
   что страница попросит, а не свою копию списка. */
const html = fs.readFileSync(path.join(LANDING, "index.html"), "utf8");
const m = /var SC_SLIDES = (\[[\s\S]*?\n  \]);/.exec(html);
check(!!m, "в странице есть список слайдов SC_SLIDES");
const slides = m ? Function("return " + m[1])() : [];
check(slides.length === 5, "слайдов пять: " + slides.length);
for (const s of slides) {
  for (const c of [s.o].concat(s.langs.map(x => x.toLowerCase()))) {
    const f = path.join(LANDING, "media", s.f + c + ".webp");
    check(fs.existsSync(f), "файл есть: " + path.basename(f));
  }
}

if (!bin) {
  console.log("Chrome не найден — проверка карусели в браузере пропущена (CHROME_PATH)");
  process.exit(fail.length ? 1 : 0);
}

const PROBE = `
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    var out = [];
    function say(k, v) { out.push(k + "=" + v); }
    var tab = document.getElementById("tab-scan"); if (tab) tab.click();
    var dots = document.getElementById("sc-dots"), cap = document.getElementById("sc-cap");
    var o = document.getElementById("sc-o"), langs = document.getElementById("sc-langs");
    say("dots", dots ? dots.children.length : 0);
    say("cap0", cap ? cap.textContent : "");
    say("src0", o ? o.getAttribute("src") : "");
    say("chips0", langs ? langs.children.length : 0);
    var nx = document.getElementById("sc-next");
    var seen = [];
    for (var i = 0; i < 5; i++) {
      seen.push(o.getAttribute("src") + "@" + langs.children.length + "@" + document.getElementById("desk").style.getPropertyValue("--ar"));
      nx.click();
    }
    say("seen", seen.join(","));
    say("srcBack", o.getAttribute("src"));
    say("cur", [].map.call(dots.children, function (d) { return d.getAttribute("aria-current"); }).join(""));
    nx.click();
    say("cap1", cap.textContent);
    var fr = document.createElement("iframe"); fr.src = "/en/"; fr.style.cssText = "width:1200px;height:900px";
    fr.onload = function () {
      setTimeout(function () {
        var dd = fr.contentDocument;
        dd.getElementById("sc-next").click();
        say("capEn", dd.getElementById("sc-cap").textContent);
        var d = document.createElement("div"); d.id = "_probe"; d.textContent = out.join("|");
        document.body.appendChild(d);
      }, 800);
    };
    document.body.appendChild(fr);
  }, 500);
});
</script>`;

const server = http.createServer((req, res) => {
  let rel = decodeURIComponent(req.url.split("?")[0]);
  if (rel.endsWith("/")) rel += "index.html";
  const file = path.join(LANDING, rel.replace(/^\/+/, ""));
  if (!file.startsWith(LANDING) || !fs.existsSync(file)) { res.writeHead(404); res.end("no"); return; }
  let body = fs.readFileSync(file);
  if (file.endsWith(".html") && rel === "/index.html") body = Buffer.from(body.toString("utf8").replace("</body>", PROBE + "</body>"), "utf8");
  res.writeHead(200, { "Content-Type": file.endsWith(".html") ? "text/html; charset=utf-8"
    : file.endsWith(".webp") ? "image/webp" : "application/octet-stream" });
  res.end(body);
});

server.listen(0, "127.0.0.1", () => {
  const port = server.address().port;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "phchrome-"));
  const proc = spawn(bin, ["--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
    "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
    "--user-data-dir=" + profile, "--virtual-time-budget=20000", "--dump-dom",
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
    check(kv.dots === "5", "пять точек: " + kv.dots);
    check(/sign-ru\.webp$/.test(kv.src0 || ""), "первый слайд — табличка: " + kv.src0);
    const seen = (kv.seen || "").split(",");
    check(new Set(seen.map(x => x.split("@")[0])).size === 5, "стрелка меняет исходник на каждом слайде: " + kv.seen);
    check(seen.some(x => x.indexOf("@1@") > 0), "у конспекта один язык перевода");
    check(new Set(seen.map(x => x.split("@")[2])).size >= 4, "пропорции у слайдов свои");
    check(/sign-ru\.webp$/.test(kv.srcBack || ""), "после последнего — снова первый");
    check(kv.cur === "truefalsefalsefalsefalse", "точка нынешнего слайда отмечена: " + kv.cur);
    check(kv.capEn && kv.capEn !== kv.cap1 && /notes/i.test(kv.capEn), "подпись переводится со страницей: " + kv.cap1 + " → " + kv.capEn);
    console.log(fail.length ? "ПРОВАЛЕНО: " + fail.length : "ВСЁ ПРОШЛО");
    process.exit(fail.length ? 1 : 0);
  });
});
