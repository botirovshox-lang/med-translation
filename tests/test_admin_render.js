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
/* Браузерные крючки самого окна: app.jsx вешает на load загрузку вкладок.
   В заглушке window === global, и без этих двух строк выполнение файла падает. */
global.addEventListener = () => {};
global.removeEventListener = () => {};
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
function renderView(label, sys, sim, draft) {
  hooks.length = 0; hookIdx = 0; effects.length = 0;
  hooks[0] = OV; hooks[2] = "models";
  if (sys) { hooks[3] = sys; hooks[4] = sys; hooks[5] = draft || { translate: "gpt-4o" }; }
  // Порядок хуков: TabAdmin 0–2, AdminModelsView 3, AdminSystemModels 4–8
  // (7–8 — какое предупреждение спора в фокусе), AdminUsageSim 9–16 (res — 15).
  if (sim) hooks[15] = sim;
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

/* Спор моделей по РОЛИ назван вслух и ДО сохранения: назначенная здесь модель
   уходит умолчанием ВСЕМ организациям сразу, и цена ошибки выше, чем у выбора
   на один прогон. Правило одно с панелью запуска (`modelRoleConflicts`
   в ui.jsx): две копии дали бы два разных ответа на один и тот же выбор —
   ровно то расхождение, ради которого состав прогона считает сервер. */
check(!!mFull && !mFull.includes("Back-check той же моделью"),
      "при разных моделях о споре не врёт");
const SYS_CONF = Object.assign({}, SYS, { steps: [
  { key: "translate", value: "gpt-4o", codeDefault: "gpt-4o", effective: "gpt-4o" },
  { key: "backcheck", value: "gpt-4o", codeDefault: "gpt-4o-mini", effective: "gpt-4o" },
  { key: "judge", value: null, codeDefault: "gpt-4o", effective: "gpt-4o" }] });
const mConf = renderView("вкладка моделей со спором", SYS_CONF, SIM,
                         { translate: "gpt-4o", backcheck: "gpt-4o", judge: "" });
check(!!mConf && mConf.includes("Back-check той же моделью, что и перевод"),
      "проверка себя названа предупреждением");
check(!!mConf && mConf.includes("Судья и обратный перевод одной моделью"),
      "пустой выбор раскрыт в умолчание кода — спор судьи с back-check виден");
check(!!mConf && mConf.includes("спорит по роли"),
      "спорящая строка отмечена в самой таблице, а не только словами");
/* Подсвечиваются ровно спорящие строки, и у каждой сказано, С КЕМ она
   спорит: «здесь что-то не так» без адреса заставляет искать пару глазами. */
check(!!mConf && mConf.includes("та же модель, что у: Перевод") && mConf.includes("та же модель, что у: back-check"),
      "у спорящей строки названа её пара");

/* «Прогоны»: факт по ПРОЕКТУ (счётчик сервера — и одиночные кнопки, и прогоны
   старше кольца runCosts), живые прогоны и имя проекта в строке прогона. */
const RUNS = { ok: true, shownUsd: 1.5, estRatio: 1.2, estRuns: 1, kept: 100,
  runs: [{ job: 5, kind: "full", tenant: "acme", project: 4, projectName: "Учебник", finished: "2026-09-19 10:00",
           segments: 10, est: 0.5, cost: 0.25, calls: 3 }],
  byProject: [{ tenant: "acme", project: 4, projectName: "Учебник", deleted: false, usd: 1.25, calls: 7,
                unpriced: 0, runs: 3, estUsd: 0.5, estActualUsd: 0.25, estRatio: 2 },
              { tenant: "acme", project: 9, projectName: null, deleted: true, usd: 0.1, calls: 1,
                unpriced: 0, runs: 1, estUsd: 0, estActualUsd: 0, estRatio: null }],
  live: [{ job: 42, kind: "full", status: "running", tenant: "acme", project: 4, projectName: "Учебник",
           done: 3, total: 10, est: 0.4, cost: 0.1234, calls: 2 }] };
hooks.length = 0; hookIdx = 0; effects.length = 0; hooks[0] = RUNS;
let runsTxt = null;
try { runsTxt = texts(AdminRuns()).join(" "); } catch (e) { check(false, "AdminRuns — " + e.message); }
check(!!runsTxt && runsTxt.includes("Проект") && runsTxt.includes("Прогонов") && runsTxt.includes("Факт $ по проекту"),
      "колонки расхода по проекту на месте");
check(!!runsTxt && runsTxt.includes("Учебник · №4") && runsTxt.includes("$1.250"), "проект назван, факт по проекту показан");
check(!!runsTxt && runsTxt.includes("№9 · удалён"), "удалённый проект назван номером, деньги не пропали");
check(!!runsTxt && runsTxt.includes("Идут сейчас") && runsTxt.includes("$0.123"), "идущий прогон — живым счётчиком");
check(!!runsTxt && runsTxt.includes("всего $1.50"), "итог показанных прогонов берётся из shownUsd");
const runsSrc = fs.readFileSync(path.join(root, "tab_admin.jsx"), "utf8");
check(/setInterval\([\s\S]{0,200}visibilityState[\s\S]{0,200}RUNS_REFRESH_MS/.test(runsSrc) && /RUNS_REFRESH_MS = 10000/.test(runsSrc),
      "карточка обновляется сама раз в 10 с, пока вкладка на экране");

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
