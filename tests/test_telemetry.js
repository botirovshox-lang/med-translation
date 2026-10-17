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
const ctx = {
  window: win, document: { addEventListener: () => {}, visibilityState: "visible" },
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
check(sent.slice(2).every(x => x.body.errors.length <= 10), "пачка не больше десяти");

console.log("=== 4. Экраны ===");
const n0 = sent.length;
win.TELEMETRY.ui("tab.editor"); win.TELEMETRY.ui("tab.editor"); win.TELEMETRY.ui("tour.step1");
tick();
check(sent.length === n0 + 1 && JSON.stringify(sent[n0].body.ui) === '["tab.editor","tour.step1"]',
      "повтор экрана подряд не шлётся");

console.log(fail.length ? "\nПРОВАЛЕНО: " + fail.length : "\nВСЁ ПРОШЛО");
process.exit(fail.length ? 1 : 0);
