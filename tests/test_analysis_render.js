/* Экран «Анализ»: рендер без браузера.
 *
 * Этот файл до сих пор не проверялся ничем. Фронтенд собирается в браузере
 * (UMD + Babel standalone), поэтому сломанный компонент виден только там —
 * белым экраном: `node --check` ловит синтаксис, но не обращение к полю
 * undefined и не проп, который перестали передавать.
 *
 * Сторожим два свойства:
 *   1. WorkSummary не падает на ответе сервера БЕЗ новых полей. Сервер
 *      обновляется отдельно от браузера, и после деплоя фронтенда старый
 *      /analysis какое-то время отвечает по-прежнему — экран обязан пережить.
 *   2. Карточка контекстного арбитра появляется, показывает число сегментов
 *      на вопрос и перечисляет записи, которые он считает неверными. Кнопка
 *      платная, поэтому число на ней — не украшение: по нему человек решает,
 *      нажимать ли.
 *
 * Запуск: node tests/test_analysis_render.js
 */
const fs = require("fs");
const path = require("path");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

let hooks = [];
let hookIdx = 0;
const effects = [];
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
  useEffect(fn) { effects.push(fn); },
  useRef(v) {
    const i = hookIdx++;
    if (!(i in hooks)) hooks[i] = { current: v === undefined ? null : v };
    return hooks[i];
  },
  useMemo(f) { return f(); },
  useCallback(f) { return f; },
  Fragment: "Fragment",
  createContext(v) { return { _v: v, Provider: "Provider", Consumer: "Consumer" }; },
  useContext() { return { info() {}, warning() {}, error() {}, success() {} }; },
};
const { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } = React;
const mem = {
  memory: {},
  getItem(k) { return this.memory[k] || null; },
  setItem(k, v) { this.memory[k] = String(v); },
  removeItem(k) { delete this.memory[k]; },
};
global.React = React;
global.useState = useState; global.useEffect = useEffect; global.useRef = useRef;
global.useMemo = useMemo; global.useCallback = useCallback;
global.createContext = createContext; global.useContext = useContext;
global.localStorage = mem; global.sessionStorage = mem;
global.window = global;
global.document = { addEventListener() {}, removeEventListener() {}, querySelector() { return null; } };
global.API = {
  safeCall: async (fn) => fn(),
  models: async () => ({ models: [], termcheckActionable: ["critical", "major", "minor"] }),
  termContext: async () => ({ ok: true, asked: 3, settled: [], wrong: [] }),
};

const root = process.argv[2] || "frontend/js";
for (const f of ["ui.jsx", "tab_preflight.jsx"]) {
  const code = fs.readFileSync(path.join(root, f), "utf8");
  (0, eval)(code + "\n//# sourceURL=" + f);
}

function render(node) {
  hooks = []; hookIdx = 0; effects.length = 0;
  return node;
}
function texts(node, out) {
  out = out || [];
  if (node === null || node === undefined) return out;
  if (typeof node === "string" || typeof node === "number") { out.push(String(node)); return out; }
  if (Array.isArray(node)) { node.forEach(n => texts(n, out)); return out; }
  if (node.children) node.children.forEach(n => texts(n, out));
  if (node.props) {
    for (const k of ["label", "hint", "title", "body"]) {
      if (typeof node.props[k] === "string") out.push(node.props[k]);
    }
  }
  return out;
}

const BASE = {
  ok: true, total: 3, clean: [1], repaired: [2],
  machine: { repaired: 1, reverted: 0 },
  proposed: { terms: 0 },
  human: {
    terms: [], termsTotal: 0, reverted: [], glossaryConfirmed: [], confirmedFindings: [],
    termcheckDisputes: [], termcheckDisputesSegments: [],
  },
  todo: { untranslated: [], unchecked: [], findings: [3], glossaryPending: [], weak: [], weakWhy: [] },
};
const store = { activeProject: { id: 1 }, go() {}, setSegmentFilter() {} };
const toast = { info() {}, success() {}, error() {}, warning() {} };

// ─────────── 1. Ответ старого сервера — экран обязан пережить ───────────
console.log("=== 1. Сервер ещё не обновлён: полей арбитра нет ===");
let ok1 = true, tree1 = null;
try {
  tree1 = render(React.createElement(WorkSummary, { summary: BASE, store, toast }));
} catch (e) { ok1 = false; console.log("      " + e.message); }
check(ok1, "WorkSummary не падает без termContextPending / termContextWrong");
check(ok1 && texts(tree1).some(t => t.indexOf("Проверено начисто") !== -1),
      "и рисует обычные строки итога");
check(ok1 && !texts(tree1).some(t => t.indexOf("Спросить арбитра") !== -1),
      "карточки арбитра нет: спрашивать не о чем");

// ─────────── 2. Есть спорные сегменты — есть кнопка с числом ───────────
console.log("\n=== 2. Спорные сегменты есть — арбитра можно спросить ===");
const WITH = JSON.parse(JSON.stringify(BASE));
WITH.human.termcheckDisputes = [{ src: "инфильтрат", tgt: "infiltrate", suggests: ["induration"], segments: [3, 4] }];
WITH.human.termcheckDisputesSegments = [3, 4];
WITH.human.termContextPending = 11;
WITH.human.termContextWrong = [];
let tree2 = null, ok2 = true;
try { tree2 = render(React.createElement(WorkSummary, { summary: WITH, store, toast })); }
catch (e) { ok2 = false; console.log("      " + e.message); }
check(ok2, "рендер прошёл");
const t2 = ok2 ? texts(tree2) : [];
check(t2.some(s => s.indexOf("Спросить арбитра (11)") !== -1),
      "кнопка называет число сегментов — по нему решают, платить ли");
check(t2.some(s => s.indexOf("читает соседние сегменты") !== -1),
      "и сказано, чем арбитр отличается от прочих проверок");

// ─────────── 3. Арбитр ответил — вердикт виден человеку ───────────
console.log("\n=== 3. Вердикт арбитра показан, и сказано, что с ним делать ===");
const ANS = JSON.parse(JSON.stringify(WITH));
ANS.human.termContextPending = 0;
ANS.human.termContextWrong = [{
  src: "туберкулёз лёгких", tgt: "pulmonary tuberculosis", use: "lung tuberculosis",
  why: "в этом ряду речь о поражении органа", segments: [81, 473],
}];
let tree3 = null, ok3 = true;
try { tree3 = render(React.createElement(WorkSummary, { summary: ANS, store, toast })); }
catch (e) { ok3 = false; console.log("      " + e.message); }
check(ok3, "рендер прошёл");
const t3 = ok3 ? texts(tree3) : [];
check(t3.some(s => s.indexOf("туберкулёз лёгких") !== -1)
      && t3.some(s => s.indexOf("lung tuberculosis") !== -1),
      "спорная запись и предложенный вариант названы оба");
check(t3.some(s => s.indexOf("Правьте саму запись") !== -1),
      "и сказано, что чинить надо ЗАПИСЬ, а не строку: одна правка приведёт в порядок все сегменты");
check(t3.some(s => s.indexOf("была бы откачена") !== -1),
      "и почему это не отдано ремонту — иначе непонятно, отчего машина молчит");
check(t3.some(s => s.indexOf("Арбитр посмотрел все") !== -1),
      "карточка не исчезает при нуле ожидающих: иначе не видно, что ноль настоящий");

console.log();
if (fail.length) {
  console.log("ПРОВАЛЕНО: " + fail.length);
  fail.forEach(f => console.log("  - " + f));
  process.exit(1);
}
console.log("ВСЁ ПРОШЛО");
