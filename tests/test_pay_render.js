/* Экраны оплаты: рендер без браузера (инвариант 39).
 *
 * Сборки нет — сломанный компонент виден только белым экраном. Экраны
 * рисуются ответами НАСТОЯЩИХ эндпоинтов (tests/fixtures/pay_payloads.json
 * снимает и сверяет с живой формой tests/test_payments.py): заглушка,
 * написанная вместе с экраном, повторяет его предположения и поломку формы
 * не видит по построению.
 *
 * Сторожится:
 *   1. карточка оплаты: способы со знаками (Visa, Mastercard, Click, Payme,
 *      Kaspi), цены в валюте способа, свои заказы со статусом словами;
 *   2. организация без предоплаты формы оплаты не получает — только слова;
 *   3. полоса «нечем платить»: владельцу — кнопка «Пополнить», остальным —
 *      «попросите владельца»;
 *   4. админка: заказы с «Подтвердить», настройки цен, адреса колбэков;
 *      расход по проектам — пресеты периода от «сегодня» СЕРВЕРА;
 *   5. ответ без ожидаемых ключей экран не роняет; нигде нет undefined/NaN;
 *   6. цены в .jsx не зашиты — считает сервер.
 *
 * Запуск: node tests/test_pay_render.js
 */
const fs = require("fs");
const path = require("path");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

const hooks = [];
let hookIdx = 0;
const React = {
  createElement(type, props, ...children) {
    const kids = [];
    (function flat(list) {
      for (const c of list) {
        if (Array.isArray(c)) flat(c);
        else if (c !== null && c !== undefined && c !== false && c !== true) kids.push(c);
      }
    })(children);
    if (typeof type === "function") return type(Object.assign({}, props, kids.length ? { children: kids } : {}));
    return { type, props: props || {}, children: kids };
  },
  useState(init) {
    const i = hookIdx++;
    if (!(i in hooks)) hooks[i] = typeof init === "function" ? init() : init;
    return [hooks[i], (v) => { hooks[i] = typeof v === "function" ? v(hooks[i]) : v; }];
  },
  useEffect() {},
  useRef(v) { return { current: v === undefined ? null : v }; },
  useMemo(f) { return f(); },
  useCallback(f) { return f; },
  Fragment: "Fragment",
  createContext(v) { return { _v: v, Provider: "Provider", Consumer: "Consumer" }; },
  useContext() { return { info() {}, warning() {}, error() {}, success() {} }; },
};
const ls = { m: {}, getItem(k) { return this.m[k] || null; }, setItem(k, v) { this.m[k] = String(v); }, removeItem(k) { delete this.m[k]; } };
Object.assign(global, { React, useState: React.useState, useEffect: React.useEffect, useRef: React.useRef,
  useMemo: React.useMemo, useCallback: React.useCallback, createContext: React.createContext,
  useContext: React.useContext, localStorage: ls, sessionStorage: ls });
global.window = global;
global.document = { addEventListener() {}, removeEventListener() {}, querySelector() { return null; } };
global.API = { safeCall: async (fn) => fn() };

const root = process.argv[2] || "frontend/js";
for (const f of ["i18n.js", "ui.jsx", "pay_icons.jsx", "pay.jsx", "tab_admin.jsx"])
  (0, eval)(fs.readFileSync(path.join(root, f), "utf8") + "\n//# sourceURL=" + f);

const FX = JSON.parse(fs.readFileSync("tests/fixtures/pay_payloads.json", "utf8"));
const toast = { info() {}, warning() {}, error() {}, success() {} };

function text(tree) {
  const out = [];
  (function walk(n) {
    if (n === null || n === undefined) return;
    if (typeof n === "string") { if (n.trim()) out.push(n.trim().replace(/ /g, " ")); return; }
    if (typeof n === "number") { out.push(String(n)); return; }
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (typeof n !== "object") return;
    if (n.props && n.props["aria-label"]) out.push("[" + n.props["aria-label"] + "]");
    (n.children || []).forEach(walk);
  })(tree);
  return out.join(" | ");
}
function draw(Comp, props, preset) {
  hooks.length = 0; hookIdx = 0;
  Object.assign(hooks, preset || {});
  return text(React.createElement(Comp, props || {}));
}
const clean = (t) => t.indexOf("undefined") === -1 && t.indexOf("NaN") === -1;

console.log("=== 1. Карточка оплаты ===");
// Хуки PayCard: 0 st, 1 pages, 2 minutes, 3 method, 4 quote, 5 qErr, 6 busy, 7 done.
const pay = FX.pay;
let t = draw(PayCard, { toast }, { 0: pay, 1: 10, 2: 5, 3: "payme",
  4: { amount: "101600", currency: "UZS" }, 5: "", 6: false, 7: null });
check(clean(t), "без undefined и NaN");
for (const brand of ["Visa", "Mastercard", "Click", "Payme", "Kaspi"])
  check(t.indexOf("[" + brand + "]") !== -1, "знак " + brand + " на экране");
check(t.indexOf("К оплате: 101 600 сум") !== -1, "сумма к оплате с разрядами и валютой");
check(t.indexOf("6 350 сум") !== -1 && t.indexOf("за стр.") !== -1, "цена страницы в сумах у способа");
check(t.indexOf("по счёту") !== -1, "способ «по счёту» назван честно, что это не мгновенно");
check(t.indexOf("Мои заказы") !== -1 && /№\d+/.test(t) && t.indexOf("оплачен") !== -1, "свои заказы со статусом словами");
check(t.indexOf("неполная минута — минута") !== -1, "правило минут видео сказано на экране");
t = draw(PayCard, { toast }, { 0: Object.assign({}, pay, { payable: { pages: false, minutes: false } }) });
check(t.indexOf("без предоплаты") !== -1 && t.indexOf("Оплатить") === -1,
      "организация без предоплаты формы не получает — только слова");
t = draw(PayCard, { toast }, { 0: { ok: true } });
check(clean(t), "ответ без ключей экран не роняет");

console.log("=== 2. Полоса «нечем платить» ===");
const owner = { can: { owner: true }, go() {} };
t = draw(PayNeedBar, { store: owner, toast }, { 0: { kind: "minutes", need: 12, left: 3 }, 1: null });
check(t.indexOf("Минут видео не хватает") !== -1 && t.indexOf("12") !== -1 && t.indexOf("Пополнить") !== -1,
      "владельцу: сколько не хватает и кнопка «Пополнить»");
t = draw(PayNeedBar, { store: { can: { owner: false }, go() {} }, toast }, { 0: { kind: "pages" }, 1: null });
check(t.indexOf("Попросите владельца") !== -1 && t.indexOf("Пополнить") === -1,
      "переводчику: попросить владельца, кнопки нет");
t = draw(PayNeedBar, { store: owner, toast }, { 0: null, 1: { id: 1001, status: "paid" } });
check(t.indexOf("1001") !== -1 && t.indexOf("баланс пополнен") !== -1, "возврат с кассы: оплата прошла");
check(draw(PayNeedBar, { store: owner, toast }, { 0: null, 1: null }) === "", "нечего сказать — полосы нет");

console.log("=== 3. Админка: оплаты ===");
const ap = FX.adminPayments;
const cfg = Object.assign({}, ap.config, { pagePacks: ap.config.pagePacks.join(", "), minutePacks: ap.config.minutePacks.join(", ") });
t = draw(AdminPayments, { toast }, { 0: ap, 1: "", 2: cfg });
check(clean(t), "без undefined и NaN");
check(t.indexOf("Подтвердить") !== -1 || ap.orders.every(o => o.status !== "new"), "у неоплаченных — «Подтвердить»");
check(t.indexOf("/api/pay/payme") !== -1, "адреса колбэков для кабинетов показаны");
check(t.indexOf("Цена страницы, $") !== -1 && t.indexOf("Курс: сумов за $1") !== -1, "настройки цен и курса");
check(t.indexOf("Оплачено, UZS") !== -1, "итог оплаченного по валютам");
check(clean(draw(AdminPayments, { toast }, { 0: { ok: true }, 1: "", 2: { methods: {}, notes: {} } })),
      "ответ без заказов экран не роняет");

console.log("=== 4. Админка: расход по проектам ===");
const ps = FX.projectSpend;
t = draw(AdminProjectSpend, {}, { 0: ps, 1: "today", 2: [ps.from, ps.to], 3: "", 4: "" });
check(clean(t), "без undefined и NaN");
for (const p of ["Сегодня", "Вчера", "Эта неделя", "Прошлая неделя", "Этот месяц", "Прошлый месяц", "Квартал", "Год", "Период"])
  check(t.indexOf(p) !== -1, "пресет «" + p + "»");
check(t.indexOf("$ за период") !== -1 && t.indexOf("Мин продано") !== -1 && t.indexOf("Себестоимость") !== -1,
      "колонки: расход, продано, себестоимость");
check(t.indexOf("учёт по дням ведётся с") !== -1, "сказано, с какого дня ведётся учёт");
check(clean(draw(AdminProjectSpend, {}, { 0: { ok: true }, 1: "today", 2: ["", ""], 3: "", 4: "" })),
      "ответ без строк экран не роняет");
const P = (k) => spendPreset(k, "2026-09-26").join("..");       // суббота
check(P("today") === "2026-09-26..2026-09-26" && P("yesterday") === "2026-09-25..2026-09-25", "сегодня / вчера");
check(P("week") === "2026-09-21..2026-09-26" && P("lastweek") === "2026-09-14..2026-09-20", "неделя с понедельника");
check(P("month") === "2026-09-01..2026-09-26" && P("lastmonth") === "2026-08-01..2026-08-31", "месяц и прошлый месяц");
check(P("quarter") === "2026-07-01..2026-09-26" && P("year") === "2026-01-01..2026-09-26", "квартал и год");
check(spendPreset("lastmonth", "2026-01-15").join("..") === "2025-12-01..2025-12-31", "прошлый месяц через Новый год");

console.log("=== 5. Цен в браузере нет ===");
const src = fs.readFileSync(path.join(root, "pay.jsx"), "utf8");
check(!/12700|0\.5\b|priceMinute|pricePage/.test(src), "в карточке оплаты нет своих цен и курса — только с сервера");

console.log("");
if (fail.length) { console.log("ПРОВАЛЕНО " + fail.length + ":"); fail.forEach(f => console.log("  - " + f)); process.exit(1); }
console.log("ВСЁ ПРОШЛО");
