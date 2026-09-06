/* Экран «Админ» и синтаксис ВСЕХ браузерных файлов: рендер без браузера.
 *
 * Заведён по боевой поломке: в `tab_admin.jsx` стояла лишняя закрывающая
 * скобка. Сборки нет, файлы компилирует Babel в браузере — поэтому
 * несобравшийся файл не оставляет НИ ОДНОГО следа на сервере: страница
 * отдаётся с кодом 200, `TabAdmin` просто не появляется в глобальной области,
 * а `tabMap` в `app.jsx` роняет весь App с ReferenceError. То есть белый экран
 * после входа — при ровном ряде двухсоток в журнале сервиса.
 *
 * Ловится это двумя дешёвыми правилами:
 *   1. КАЖДЫЙ файл из frontend/js разбирается как скрипт. Прежние рендер-тесты
 *      грузят только свои файлы, поэтому `tab_admin.jsx` не разбирал никто —
 *      ровно та дыра, в которую поломка и уехала в продакшен;
 *   2. `TabAdmin` рисуется дважды: до ответа сервера (`ov = null` — это первый
 *      рендер, и он обязан пережить отсутствие сводки) и с ответом той формы,
 *      какую отдаёт `/api/admin/overview`.
 * Плюс два правила показа, которые легко потерять молча: без служебного адреса
 * (`window.ADMIN_ENTRY`) и без `can.super` экран содержимого не отдаёт.
 *
 * Запуск: node tests/test_admin_render.js
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

const root = process.argv[2] || "frontend/js";

/* 1. Синтаксис всех браузерных файлов ------------------------------------ */
for (const f of fs.readdirSync(root).filter(n => /\.jsx?$/.test(n)).sort()) {
  const src = fs.readFileSync(path.join(root, f), "utf8");
  let err = null;
  try { new vm.Script(src, { filename: f }); } catch (e) { err = e.message; }
  check(!err, "разбирается: " + f + (err ? " — " + err : ""));
}

/* 2. Рендер «Админа» ------------------------------------------------------ */
const hooks = []; let hookIdx = 0; const effects = [];
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
  useEffect(fn) { effects.push(fn); },
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
global.useState = useState; global.useEffect = useEffect; global.useRef = useRef;
global.useMemo = useMemo; global.useCallback = useCallback;
global.createContext = createContext; global.useContext = useContext;
global.localStorage = store_ls;
global.sessionStorage = store_ls;
global.window = global;
global.document = { addEventListener() {}, removeEventListener() {}, querySelector() { return null; },
                   getElementById() { return {}; } };
global.ReactDOM = { createRoot: () => ({ render() {} }) };
global.prompt = () => null;
global.confirm = () => false;

/* Форма ответа `/api/admin/overview`: организация с потолками, объёмом
   в страницах и журналом — то, что добавили последние правки учёта. */
const OV = {
  ok: true, month: "2026-09",
  capDefaults: { filePages: 0, maxPages: 0, maxProjects: 0 },
  process: { uptimeSec: 27000, usage: { cost: 1.23, calls: 42, unpriced: 0 },
             stateBytes: 5000000, sessions: 3, openaiKey: true,
             version: "5.6.0", termQueue: 12, auditRows: 100 },
  jobs: { active: [], recent: [], queued: 0, workerAlive: false },
  tenants: [{
    id: "default", name: "Организация", active: true, users: 2, activeUsers: 1,
    projects: 1, segments: 2670, glossary: 9502, domains: 0, limitUsd: null,
    spend: { spentUsd: 1.5, calls: 10, over: false, unpriced: 0 },
    caps: { maxPages: 500, pagesLimited: true, maxProjects: 0, filePages: 0,
            own: { maxPages: 500, maxProjects: null } },
    usage: { pages: 300.5, used: 300, imagePages: 0.5, projects: 1,
             credit: 500, left: 199.5, counter: true },
    pagesLog: [{ at: "2026-09-05 10:00", kind: "credit", pages: 500, note: "env" },
               { at: "2026-09-05 11:00", kind: "debit", pages: 300, title: "Учебник" },
               { at: "2026-09-05 12:00", kind: "repeat", pages: 0, title: "Учебник" }],
  }],
};
global.API = {
  safeCall: async (fn) => fn(), hasToken: () => false,
  me: async () => ({ ok: true, me: {}, can: { owner: true, super: true }, teams: [], tenant: {}, invites: [] }),
  models: async () => ({ ok: true }), seed: async () => ({ projects: [], glossary: [], tm: [] }),
  adminOverview: async () => OV, usersAll: async () => ({ users: [] }), auditAll: async () => ({ items: [] }),
};

for (const f of ["i18n.js", "ui.jsx", "tab_admin.jsx", "app.jsx"])
  (0, eval)(fs.readFileSync(path.join(root, f), "utf8") + "\n//# sourceURL=" + f);

const toast = { info() {}, warning() {}, error() {}, success() {} };
function texts(node, out) {
  out = out || [];
  if (node == null || node === false || node === true) return out;
  if (typeof node === "string" || typeof node === "number") { out.push(String(node)); return out; }
  if (Array.isArray(node)) { node.forEach(n => texts(n, out)); return out; }
  if (node.props) for (const k of ["label", "title", "placeholder"])
    if (typeof node.props[k] === "string") out.push(node.props[k]);
  (node.children || []).forEach(n => texts(n, out));
  return out;
}
function render(store, label, seed) {
  hooks.length = 0; hookIdx = 0; effects.length = 0;
  if (seed !== undefined) hooks[0] = seed;   // первый useState в TabAdmin — сводка
  try { return texts(TabAdmin({ store, toast })).join(" "); }
  catch (e) { check(false, label + " — " + e.constructor.name + ": " + e.message); return null; }
}

const superStore = { can: { owner: true, super: true }, tab: "admin", go() {}, me: {} };
global.ADMIN_ENTRY = true;

const waiting = render(superStore, "рендер без сводки", undefined);
check(waiting !== null, "рисуется до ответа сервера (ov = null)");

const full = render(superStore, "рендер со сводкой", OV);
check(full !== null, "рисуется с ответом /api/admin/overview");
check(!!full && full.includes("Организация"), "организация названа в таблице");
check(!!full && full.includes("Пополнить") && full.includes("Журнал"), "кнопки учёта страниц на месте");
check(!!full && full.includes("500"), "выданные страницы показаны");

/* Два правила показа: служебный адрес и роль. Пропавшая проверка открыла бы
   сводку по всем организациям с главной страницы. */
global.ADMIN_ENTRY = false;
const noEntry = render(superStore, "рендер без служебного адреса", OV);
check(!!noEntry && !noEntry.includes("Пополнить"), "без служебного адреса содержимого нет");
global.ADMIN_ENTRY = true;
const notSuper = render({ can: { owner: true, super: false }, tab: "admin", go() {}, me: {} },
                        "рендер не суперпользователю", OV);
check(!!notSuper && !notSuper.includes("Пополнить"), "не суперпользователю содержимого нет");

console.log(fail.length ? "\nПРОВАЛЕНО: " + fail.length : "\nВсё сошлось");
process.exit(fail.length ? 1 : 0);
