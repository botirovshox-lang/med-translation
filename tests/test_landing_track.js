/* landing/track.js без браузера: какие события уходят и сколько раз.
 *
 *   1. Просмотр страницы и отметки прокрутки — один раз каждая (счёт «людьми»).
 *   2. Кнопки: `data-cta`, ссылки в приложение, вопросы FAQ, вкладки примеров.
 *   3. Форма: файл, отправка, ошибка по ключу текста, передача файла.
 *   4. Уход: глубина и «отправил ли форму» — один раз.
 *   5. Уходит `text/plain` на тот же адрес — без предварительного запроса.
 */
"use strict";
const fs = require("fs");
const vm = require("vm");

const fail = [];
function check(c, label) { console.log((c ? "  OK   " : "  FAIL ") + label); if (!c) fail.push(label); }

const winL = {}, docL = {}, sent = [];
let timers = [];
const els = {};
const errEl = { hidden: true, textContent: "", attrs: { "data-tgt": "Выберите язык" },
                getAttribute(n) { return this.attrs[n] || null; } };
let moCb = null;
const doc = {
  documentElement: { scrollHeight: 2000 },
  visibilityState: "visible",
  addEventListener: (t, f) => { (docL[t] = docL[t] || []).push(f); },
  getElementById: (id) => ({ "tr-err": errEl, "tr-file": els.file, "tr": els.form })[id] || null,
  querySelectorAll: (sel) => sel.indexOf("summary") >= 0 ? els.faq : (sel.indexOf("lens") >= 0 ? [] : []),
};
const mk = (props) => Object.assign({ listeners: {}, addEventListener(t, f) { this.listeners[t] = f; } }, props);
els.file = mk({}); els.form = mk({});
els.faq = [{ tagName: "SUMMARY", parentNode: { open: false }, getAttribute: () => null, closest: () => null },
           { tagName: "SUMMARY", parentNode: { open: false }, getAttribute: () => null, closest: () => null }];
const win = {
  innerHeight: 1000, scrollY: 0,
  addEventListener: (t, f) => { (winL[t] = winL[t] || []).push(f); },
  ym: () => {}, METRIKA_ID: 1,
};
const ctx = {
  window: win, document: doc, location: { pathname: "/uz/" },
  performance: { getEntriesByType: () => [{ loadEventStart: 2400 }] },
  fetch: (url, opt) => { sent.push({ url, opt, body: JSON.parse(opt.body) }); return Promise.resolve({}); },
  setTimeout: (f) => { timers.push(f); return timers.length; },
  MutationObserver: function (cb) { moCb = cb; this.observe = () => {}; },
  JSON, Math, Array, Promise,
};
win.MutationObserver = ctx.MutationObserver;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync("landing/track.js", "utf8"), ctx);
const tick = () => { const t = timers; timers = []; t.forEach(f => f()); };
const all = () => sent.reduce((a, x) => a.concat(x.body.land || []), []);
const click = (el) => (docL.click || []).forEach(f => f({ target: { closest: () => el } }));

console.log("=== 1. Просмотр и прокрутка ===");
(winL.load || []).forEach(f => f());
win.scrollY = 600; (winL.scroll || []).forEach(f => f());
win.scrollY = 600; (winL.scroll || []).forEach(f => f());
tick();
check(all().indexOf("view:uz") >= 0, "страница опознана по адресу: /uz/ → uz");
check(all().indexOf("perf:1to3") >= 0, "скорость загрузки корзиной");
check(all().filter(c => c === "scroll:50").length === 1 && all().indexOf("scroll:75") < 0,
      "отметка прокрутки — один раз, и только пройденная");
check(sent[0].url === "/api/client/beacon" && sent[0].opt.headers["Content-Type"] === "text/plain",
      "тот же адрес и text/plain: без предварительного запроса");

console.log("=== 2. Кнопки ===");
const a = (attrs) => ({ tagName: "A", getAttribute: (n) => attrs[n] || null, closest: () => null, id: attrs.id || "" });
click(a({ "data-cta": "price-pro" }));
click(a({ href: "https://simpletranslate.me/" }));
click(a({ href: "#faq" }));
click(els.faq[1]);
click({ tagName: "BUTTON", getAttribute: (n) => ({ role: "tab", "data-k": "video" })[n] || null, closest: () => null });
tick();
["cta:price-pro", "cta:app", "cta:anchor", "faq:2", "tab:video"].forEach(c =>
  check(all().indexOf(c) >= 0, "нажатие записано: " + c));

console.log("=== 3. Форма ===");
els.file.listeners.change();
els.form.listeners.submit();
errEl.hidden = false; errEl.textContent = "Выберите язык"; moCb && moCb([]);
win.LANDTRACK.goal("tr_handoff_fail");
win.LANDTRACK.err("eBig");
tick();
["form.file", "form.submit", "form.err:tgt", "form.err:big", "form.handoff_fail"].forEach(c =>
  check(all().indexOf(c) >= 0, "форма: " + c));

console.log("=== 4. Уход ===");
doc.visibilityState = "hidden";
(docL.visibilitychange || []).forEach(f => f());
(winL.pagehide || []).forEach(f => f());
const lv = all().filter(c => c.indexOf("leave:") === 0);
check(lv.length === 1 && lv[0] === "leave:50:sub", "уход один раз, с глубиной и отправкой: " + lv);

console.log(fail.length ? "\nПРОВАЛЕНО: " + fail.length : "\nВСЁ ПРОШЛО");
process.exit(fail.length ? 1 : 0);
