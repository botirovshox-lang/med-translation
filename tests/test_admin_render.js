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
  /* Рамка падения (Boundary в app.jsx) — классовый компонент: у хуков
     аналога componentDidCatch нет. Заглушке достаточно пустого класса,
     иначе 'class extends undefined' роняет загрузку файла целиком. */
  Component: class Component { constructor(props) { this.props = props; } },
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

/* Вкладка «Модели и расход»: переключатель на месте, вид рисуется и до ответа
   сервера (настройка и пересчёт грузятся своими запросами), и с ответом. */
check(!!full && full.includes("Модели и расход"), "переключатель вкладки моделей на месте");
function renderView(label, sys, sim) {
  hooks.length = 0; hookIdx = 0; effects.length = 0;
  hooks[0] = OV; hooks[2] = "models";
  if (sys) { hooks[3] = sys; hooks[4] = sys; hooks[5] = { translate: "gpt-4o" }; }
  // Порядок хуков: TabAdmin 0–2, AdminModelsView 3, AdminSystemModels 4–6,
  // AdminUsageSim 7–14 (res — 13).
  if (sim) hooks[13] = sim;
  try { return texts(TabAdmin({ store: superStore, toast })).join(" "); }
  catch (e) { check(false, label + " — " + e.constructor.name + ": " + e.message); return null; }
}
const SYS = { ok: true, groups: ["translate", "terms"],
  models: [{ id: "gpt-4o", label: "GPT-4o", in: 2.5, out: 10 }, { id: "gpt-4o-mini", label: "GPT-4o mini", in: 0.15, out: 0.6 }],
  steps: [{ key: "translate", value: "gpt-4o", codeDefault: "gpt-4o", effective: "gpt-4o" },
          { key: "backcheck", value: null, codeDefault: "gpt-4o-mini", effective: "gpt-4o-mini" }] };
const SIM = { ok: true, ledgerSince: "2026-08-01", historyRows: 2,
  total: { calls: 3, in: 100, out: 50, actual: 1.5, sim: 0.2, unpriced: 0 },
  groups: [{ group: "translate", calls: 2, in: 80, out: 40, actual: 1.2, sim: 0.1, unpriced: 0, simulable: true, actualModels: { "gpt-4o": 2 } },
           { group: "embed", calls: 1, in: 20, out: 10, actual: 0.3, sim: 0.3, unpriced: 0, simulable: false, actualModels: {} }],
  byUser: [{ user: null, calls: 3, actual: 1.5, sim: 0.2 }], byTenant: [] };
const mEmpty = renderView("вкладка моделей до ответа", null, null);
check(mEmpty !== null && !mEmpty.includes("Пополнить"), "вкладка моделей рисуется до ответа и без сводки");
const mFull = renderView("вкладка моделей с ответом", SYS, SIM);
check(!!mFull && mFull.includes("Модели шагов на всю систему") && mFull.includes("Виртуальный пересчёт расхода"),
      "обе карточки на месте");
check(!!mFull && mFull.includes("По выбранным моделям") && mFull.includes("без автора"), "итог пересчёта и строка без автора");

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
