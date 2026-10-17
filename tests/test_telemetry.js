/* frontend/js/telemetry.js без браузера: что ловится, что уходит, что НЕТ.
 *
 *   1. Ошибка кода и незагрузившийся файл уходят пачкой на /api/client/beacon,
 *      с токеном, если он есть (иначе ошибку нельзя приписать организации).
 *   2. Отказ сервера (у ошибки api.js есть `status`) НЕ шлётся: его уже
 *      посчитал сервер, повтор удвоил бы счёт.
 *   3. Одна и та же ошибка — один раз, и не больше потолка за страницу:
 *      ошибка в цикле отрисовки иначе засыпала бы сервер.
 *   4. Экран подряд не повторяется.
 */
"use strict";
const fs = require("fs");
const vm = require("vm");

const fail = [];
function check(c, label) { console.log((c ? "  OK   " : "  FAIL ") + label); if (!c) fail.push(label); }

const listeners = {};
const sent = [];
let timers = [];
const store = { "mct-token": "tok123" };
const win = {
  addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
  sessionStorage: { getItem: k => store[k] || null },
  fetch: (url, opt) => { sent.push({ url, opt, body: JSON.parse(opt.body) }); return Promise.resolve({}); },
  BOOT: { v: "v1" },
};
const docListeners = {};
const ctx = {
  window: win, document: { addEventListener: (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); },
                           visibilityState: "visible" },
  performance: { getEntriesByType: () => [{ loadEventStart: 1500 }] },
  Date,
  setTimeout: (f) => { timers.push(f); return timers.length; },
  JSON, String, Promise,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync("frontend/js/telemetry.js", "utf8"), ctx);
const fire = (t, ev) => (listeners[t] || []).forEach(f => f(ev));
const tick = () => { const t = timers; timers = []; t.forEach(f => f()); };

console.log("=== 1. Ошибка и незагрузившийся файл уходят пачкой ===");
win._mcat_tab = "editor";
fire("error", { filename: "https://h/js/app.jsx?v=1", lineno: 5, colno: 2, message: "boom",
                error: { stack: "at a (https://h/js/app.jsx:5:2)" } });
fire("error", { target: { src: "https://h/js/tab_editor.jsx?v=1" } });
check(sent.length === 0, "до таймера ничего не ушло: пачка, а не запрос на ошибку");
tick();
check(sent.length === 1 && sent[0].url === "/api/client/beacon", "одна пачка на дверь сервера");
const b = sent[0] && sent[0].body;
check(b && b.errors.length === 2 && b.errors[0].file === "app.jsx" && b.errors[0].line === 5
      && b.errors[0].screen === "editor" && b.errors[0].ver === "v1",
      "файл без адреса, строка, экран и версия: " + JSON.stringify(b && b.errors[0]));
check(b && b.errors[1].kind === "load" && b.errors[1].file === "tab_editor.jsx",
      "незагрузившийся файл назван");
check(sent[0] && sent[0].opt.headers.Authorization === "Bearer tok123" && sent[0].opt.keepalive,
      "с токеном и keepalive");

console.log("=== 2. Отказ сервера не шлётся ===");
fire("unhandledrejection", { reason: { status: 402, message: "Лимит" } });
fire("unhandledrejection", { reason: { message: "x is undefined", stack: "at f (https://h/js/pay.jsx:1:1)" } });
tick();
const b2 = sent[1] && sent[1].body;
check(b2 && b2.errors.length === 1 && b2.errors[0].kind === "rejection" && b2.errors[0].file === "pay.jsx",
      "ушёл только отказ кода, с файлом из стека: " + JSON.stringify(b2));

console.log("=== 3. Повторы и потолок ===");
for (let i = 0; i < 5; i++) fire("error", { filename: "a.js", lineno: 1, message: "same" });
for (let i = 0; i < 100; i++) fire("error", { filename: "a.js", lineno: i + 2, message: "loop" });
for (let i = 0; i < 20; i++) tick();
const total = sent.slice(2).reduce((s, x) => s + x.body.errors.length, 0);
check(total + 3 <= 30, "за страницу не больше потолка ошибок: " + (total + 3));
check(sent.slice(2).every(x => x.body.errors.length <= 5), "пачка не больше пяти — влезает в потолок сервера");

console.log("=== 4. Экраны ===");
const n0 = sent.length;
win.TELEMETRY.ui("tab.editor"); win.TELEMETRY.ui("tab.editor"); win.TELEMETRY.ui("tour.step1");
tick();
check(sent.length === n0 + 1 && JSON.stringify(sent[n0].body.ui) === '["tab.editor","tour.step1"]',
      "повтор экрана подряд не шлётся");

console.log("=== 5. Клики: надпись словаря, нервные, экран ===");
win.I18N = { lang: "uz", toKey: s => ({ "Yangilash": "Обновить" })[s] || s };
const btn = { textContent: "Yangilash", getAttribute: () => null };
const clickOn = (el) => (docListeners.click || []).forEach(f => f({ target: { closest: () => el } }));
win._mcat_tab = "editor";
const n1 = sent.length;
clickOn(btn); clickOn(btn); clickOn(btn); clickOn({ textContent: "1Проекты", getAttribute: () => null });
tick();
const cl = sent.slice(n1).reduce((a, x) => a.concat(x.body.clicks || []), []);
check(cl.length === 3, "серия из трёх кликов — один обычный и один «нервный»: " + JSON.stringify(cl));
check(cl[0] && cl[0].c[0] === "Обновить" && cl[0].t === "editor", "надпись переведена в русский ключ словаря");
check(cl[1] && cl[1].rage === true, "третий клик подряд — «нервный»");
check(cl[2] && cl[2].c.indexOf("Проекты") >= 0, "номер шага в меню не мешает надписи: " + JSON.stringify(cl[2]));
store["mct-token"] = "";
clickOn({ textContent: "Войти", getAttribute: () => null });
tick();
const lastBody = sent[sent.length - 1].body;
check(lastBody.clicks[0].t === "auth", "до входа клик идёт на экран входа");
store["mct-token"] = "tok123";

console.log("=== 6. Скорость, устройство, время на экране ===");
win.innerWidth = 400;
fire("load", {});
tick();
const sl = sent.slice(-2).map(x => x.body);
check(sl.some(b => b.perf && b.perf.load === 1500), "время загрузки страницы ушло");
check(sl.some(b => (b.ui || []).indexOf("env.phone") >= 0), "устройство названо: телефон");
const realNow = Date.now;
let fake = realNow();
Date.now = () => fake;
win.TELEMETRY.ui("tab.glossary");
fake += 65000;
win.TELEMETRY.ui("tab.editor");
win.TELEMETRY.flush();
Date.now = realNow;
const dw = sent[sent.length - 1].body.dwell || {};
check(dw.glossary >= 65000 && dw.glossary < 66000, "время на вкладке посчитано: " + JSON.stringify(dw));

console.log("=== 7. Без отклика, отказ после нажатия, уход ===");
const observers = [];
win.MutationObserver = function (cb) { this.cb = cb; observers.push(this); };
win.MutationObserver.prototype.observe = function () {};
win.MutationObserver.prototype.disconnect = function () {};
ctx.document.body = {};
const mkBtn = (label, match) => ({ textContent: label, getAttribute: () => null, disabled: false,
                                   matches: () => !!match, closest: () => null });
const allClicks = () => sent.reduce((a, x) => a.concat(x.body.clicks || []), []);
const before7 = allClicks().length;
clickOn(mkBtn("Сохранить"));
tick(); tick();
check(allClicks().slice(before7).some(r => r.kind === "dead" && r.c[0] === "Сохранить"),
      "нажатие, после которого за секунду ничего не изменилось, — «без отклика»");
const b2n = allClicks().length;
clickOn(mkBtn("Применить"));
observers[observers.length - 1].cb([]);
tick(); tick();
check(!allClicks().slice(b2n).some(r => r.kind === "dead"), "экран изменился — отклик был");
const b3n = allClicks().length;
clickOn(mkBtn("Выбрать файл", true));
tick(); tick();
check(!allClicks().slice(b3n).some(r => r.kind === "dead"), "выбор файла и поля законно не меняют экран — не считаем");
clickOn(mkBtn("Перевести"));
const cx = win.TELEMETRY.claim();
check(cx && cx.c[0] === "Перевести", "запрос, начатый сразу после нажатия, привязан к кнопке");
win.TELEMETRY.failed(cx, 402);
win.TELEMETRY.failed(cx, 401);
tick(); tick();
const fl = allClicks().filter(r => r.kind === "fail");
check(fl.length === 1 && fl[0].s === 402, "отказ 402 записан, истёкшая сессия — нет");
check(!allClicks().some(r => r.kind === "dead" && r.c[0] === "Перевести"), "клик с запросом — не «без отклика»");
const realNow2 = Date.now;
let fk = realNow2();
Date.now = () => fk;
clickOn(mkBtn("Обновить"));
fk += 1500;
check(win.TELEMETRY.claim() === null, "фоновый запрос через 1,5 с к нажатию не прилипает");
Date.now = realNow2;

console.log("=== 8. Уход: отложен, тому же человеку, после 30 минут ===");
const ls = {};
win.localStorage = { getItem: k => (k in ls ? ls[k] : null), setItem: (k, v) => { ls[k] = String(v); },
                     removeItem: k => { delete ls[k]; } };
ctx.localStorage = win.localStorage;
win._mcat_uid = 7; win._mcat_tab = "export";
const realNow3 = Date.now;
let t3 = realNow3();
Date.now = () => t3;
ctx.document.visibilityState = "hidden";
(docListeners.visibilitychange || []).forEach(f => f());
check(ls["mct-exit"] && JSON.parse(ls["mct-exit"]).c === "exit.export.none",
      "ушёл, не получив перевода, — уход отложен: " + ls["mct-exit"]);
ctx.document.visibilityState = "visible";
t3 += 60000;
(docListeners.visibilitychange || []).forEach(f => f());
check(!ls["mct-exit"], "вернулся через минуту — это не уход");
ctx.document.visibilityState = "hidden";
(docListeners.visibilitychange || []).forEach(f => f());
t3 += 31 * 60000;
win._mcat_uid = 8;
const nx = sent.length;
win.TELEMETRY.flush();
check(!sent.slice(nx).some(x => (x.body.ui || []).some(c => c.indexOf("exit.") === 0)),
      "за компьютером другой человек — чужой уход ему не засчитан");
ctx.document.visibilityState = "hidden";
win._mcat_uid = 7;
(docListeners.visibilitychange || []).forEach(f => f());
t3 += 31 * 60000;
ctx.document.visibilityState = "visible";
win.TELEMETRY.success();
win.TELEMETRY.flush(); tick();
check(sent.slice(nx).some(x => (x.body.ui || []).indexOf("exit.export.none") >= 0),
      "тот же человек не вернулся за полчаса — уход засчитан");
Date.now = realNow3;

console.log(fail.length ? "\nПРОВАЛЕНО: " + fail.length : "\nВСЁ ПРОШЛО");
process.exit(fail.length ? 1 : 0);
