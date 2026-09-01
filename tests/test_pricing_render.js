/* Экраны цен и сметы: рендер без браузера.
 *
 * Тот же приём, что в test_export_render.js: сборки нет, .jsx выполняются
 * в браузере, поэтому сломанный компонент виден только там — белым экраном.
 * До этого теста `OrgPricing` и `ImpQuote` не грузил ни один рендер-тест.
 *
 * Проверяется то, что легко потерять молча:
 *   1. цена «не задана» показывается словами, а не нулём — иначе клиенту
 *      обещан бесплатный перевод;
 *   2. видно, ОТКУДА взята норма страницы (своя, таблица, по умолчанию);
 *   3. повторы названы, но из объёма не вычтены;
 *   4. расчёт (formula) и оговорки (notes) сервера доходят до экрана:
 *      сумма, которую нечем проверить, — это просьба верить на слово;
 *   5. в экране цен нет собственных чисел нормы и прайса — только с сервера;
 *   6. строка прайса без цены сохранена не будет, и об этом сказано ДО
 *      нажатия, а не молчанием.
 *
 * Запуск: node tests/test_pricing_render.js
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
    if (typeof type === "function") {
      return type(Object.assign({}, props, kids.length ? { children: kids } : {}));
    }
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
const { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } = React;
const store_ls = {
  memory: {},
  getItem(k) { return this.memory[k] || null; },
  setItem(k, v) { this.memory[k] = String(v); },
  removeItem(k) { delete this.memory[k]; },
};
global.React = React;
global.useState = useState; global.useEffect = useEffect;
global.useRef = useRef; global.useMemo = useMemo; global.useCallback = useCallback;
global.createContext = createContext; global.useContext = useContext;
global.localStorage = store_ls;
global.sessionStorage = store_ls;
global.window = global;
global.document = { addEventListener() {}, removeEventListener() {}, querySelector() { return null; } };
global.API = { safeCall: async (fn) => fn() };

const root = process.argv[2] || "frontend/js";
for (const f of ["ui.jsx", "tab_import.jsx", "tab_org.jsx"]) {
  (0, eval)(fs.readFileSync(path.join(root, f), "utf8") + "\n//# sourceURL=" + f);
}

const toast = { info() {}, warning() {}, error() {}, success() {} };

function text(tree) {
  const out = [];
  (function walk(node) {
    if (node === null || node === undefined) return;
    if (typeof node === "string") { if (node.trim()) out.push(node.trim()); return; }
    if (typeof node === "number") { out.push(String(node)); return; }
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node !== "object") return;
    (node.children || []).forEach(walk);
  })(tree);
  return out.join(" | ");
}

// ── Смета: сервер посчитал, экран показывает ────────────────────────
function quoteScreen(res) {
  hooks.length = 0; hookIdx = 0;
  hooks[0] = res;                      // res — первый useState в ImpQuote
  return text(React.createElement(ImpQuote, {
    file: { name: "doc.docx", raw: {} }, src: "RU", tgt: "EN", toast,
  }));
}

const priced = quoteScreen({
  file: "doc.docx", kind: "docx", basis: "file",
  counts: { chars: 437975, charsNoSpaces: 389037, words: 50955, blocks: 2703,
            repeatBlocks: 86, repeatChars: 1475 },
  norm: { lang: "RU", chars: 1800, source: "table", spaceless: false },
  pages: { exact: 243.319, billed: 243.4, normChars: 1800, minPages: 1, roundTo: 0.1 },
  rate: { price: 12.5, source: "pair" }, currency: "USD", total: 3042.5,
  notes: ["PDF: текст извлечён из текстового слоя; надписи внутри картинок в счёт не идут."],
  formula: "437975 знаков с пробелами ÷ 1800 = 243.319 стр.; к оплате 243.4 стр. × 12.5 USD = 3042.5",
});
check(priced.indexOf("243.4") !== -1, "страницы к оплате показаны");
check(priced.indexOf("3042.5") !== -1 || priced.indexOf("3 042,5") !== -1, "итог показан");
check(priced.indexOf("÷") !== -1, "расчёт строкой доехал до экрана — сумму можно проверить глазами");
check(priced.indexOf("86") !== -1 && priced.indexOf("НЕ вычтены") !== -1,
      "повторы названы и прямо сказано, что из объёма они не вычтены");
check(priced.indexOf("надписи внутри картинок в счёт не идут") !== -1,
      "оговорки сервера показаны, а не проглочены");
check(priced.indexOf("по паре") !== -1, "видно, по какой цене считали — по паре или общей");

const unpriced = quoteScreen({
  file: "doc.txt", kind: "txt", basis: "file",
  counts: { chars: 1800, charsNoSpaces: 1500, words: 250, blocks: 1, repeatBlocks: 0, repeatChars: 0 },
  norm: { lang: "KK", chars: 1800, source: "default", spaceless: false },
  pages: { exact: 1, billed: 1, normChars: 1800, minPages: 1, roundTo: 0.1 },
  rate: { price: null, source: null }, currency: "USD", total: null,
  notes: ["Нормы для языка KK в таблице нет — взята норма по умолчанию (1800 знаков)."],
  formula: "1800 знаков с пробелами ÷ 1800 = 1.0 стр.; к оплате 1.0 стр. × — USD = цена не задана",
});
check(unpriced.indexOf("не задана") !== -1, "цены нет — сказано словами");
check(unpriced.indexOf("0 USD") === -1 && unpriced.indexOf("0.00") === -1,
      "и ни одного нуля вместо суммы: бесплатный перевод клиенту не обещан");
check(unpriced.indexOf("по умолчанию") !== -1, "видно, что норма взята по умолчанию, а не для этого языка");
check(unpriced.indexOf("Задайте цену за страницу") !== -1, "сказано, что делать дальше");

// ── Прайс: свои числа экран не выдумывает ───────────────────────────
function priceScreen(card) {
  hooks.length = 0; hookIdx = 0;
  hooks[0] = card;                     // card
  hooks[1] = { default: 1800, basis: { wordsPerPage: 250 },
               rows: [{ lang: "RU", chars: 1800 }, { lang: "EN", chars: 1500 }] };   // norms
  hooks[2] = [["RU", "Русский"], ["EN", "Английский"]];                              // langs
  hooks[3] = false;                                                                  // busy
  return text(React.createElement(OrgPricing, { toast }));
}
const card = priceScreen({ currency: "USD", default: null, minPages: 1, roundTo: 0.1,
                           norms: {}, rates: [{ src: "RU", tgt: "EN", price: "" }] });
check(card.indexOf("1800") !== -1 && card.indexOf("1500") !== -1,
      "нормы показаны те, что пришли с сервера");
check(card.indexOf("ноль — это не цена") !== -1,
      "строка без цены предупреждена ДО нажатия, а не выброшена молча");
check(card.indexOf("знаков ИСХОДНИКА") !== -1, "сказано, от чего считается страница");

const src = fs.readFileSync(path.join(root, "tab_org.jsx"), "utf8");
check(!/norms\s*=\s*\{[^}]*1800/.test(src) && src.indexOf("chars: 1800") === -1,
      "в экране цен нет собственной таблицы норм — только серверная");
const impSrc = fs.readFileSync(path.join(root, "tab_import.jsx"), "utf8");
check(impSrc.indexOf("/ 1800") === -1 && impSrc.indexOf("* 1800") === -1,
      "смета не пересчитывает страницы в браузере: считает сервер");

console.log("");
if (fail.length) {
  console.log("ПРОВАЛЕНО " + fail.length + ":");
  fail.forEach((f) => console.log("  - " + f));
  process.exit(1);
}
console.log("ВСЁ ПРОШЛО");
