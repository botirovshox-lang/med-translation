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

/* «Заново» (предел перевода заново): целое ≥ 0 или пусто. NaN и минус
   на сервер не уходят — опечатка называется здесь. */
{
  const sent = [], errs = [];
  const tstA = { info() {}, warning() {}, success() {}, error: (t, m) => errs.push(m) };
  global.API.tenantUpdate = (tid, body) => { sent.push(body); return Promise.resolve({ ok: true }); };
  hooks.length = 0; hookIdx = 0; effects.length = 0; hooks[0] = OV;
  let again = null;
  try {
    const tree = TabAdmin({ store: superStore, toast: tstA });
    (function walk(n) {
      if (again || !n || typeof n !== "object") return;
      if (Array.isArray(n)) return n.forEach(walk);
      if (n.type === "button" && (n.children || []).some(c => c === "Заново")) { again = n; return; }
      (n.children || []).forEach(walk);
    })(tree);
  } catch (e) { check(false, "рендер для «Заново» — " + e.message); }
  check(!!again, "кнопка «Заново» у организации есть");
  if (again) {
    for (const bad of [["abc", ""], ["-1", ""], ["", "1.5"]]) {
      const q = bad.slice();
      global.prompt = () => q.shift();
      again.props.onClick();
    }
    check(sent.length === 0 && errs.length === 3, "NaN, минус и дробь не отправлены, каждая названа: " + errs.length);
    const q = ["2", ""];
    global.prompt = () => q.shift();
    again.props.onClick();
    check(sent.length === 1 && sent[0].retranslateLimit === 2 && !("retranslateBulk" in sent[0]),
          "целое уходит числом: " + JSON.stringify(sent[0]));
    global.prompt = () => null;
  }
}

/* ---------- Вкладка «Метрики» ----------
   Экран отвечает на вопрос владельца («где теряем, где заработать»), а не
   показывает счётчики, поэтому сторожим ровно это: подсказка приходит КОДОМ
   и числом, а фразу к ней собирает браузер. Забудь строку в `metHintText` —
   на экране встанет сам код (`bigFiles`), и заметит это клиент, а не мы.
   Плюс два правила показа: пустой ответ — это ОТВЕТ («находок нет»), а не
   пустой экран, и техническое (маршруты, скорость) лежит под «Подробностями». */
{
  const MET = {
    ok: true, days: 7, from: "2026-09-14", to: "2026-09-20",
    spendUsd: 12.5, calls: 300,
    steps: [{ step: "translate", usd: 10, calls: 200, in: 1, out: 1 },
            { step: "backcheck", usd: 2.5, calls: 100, in: 1, out: 1 }],
    tenants: [{ id: "acme", name: "Акме", active: true, users: 2, projects: 3,
                pages: 200, pagesCredit: 500, pagesLeft: 20, spendUsd: 12.5, runs: 9,
                costPerPage: 0.0625, pricePerPage: 4, currency: "USD", margin: 0.98,
                estUsd: 10, estActualUsd: 12.5, estRatio: 0.8, lastRun: "2026-09-19",
                idleDays: 1, caps: {} }],
    quotes: { byStatus: { new: { n: 1, total: 100 }, invoiced: { n: 2, total: 800 },
                          paid: { n: 1, total: 300 } }, total: 4, currency: "USD", conversion: 0.33 },
    routes: [{ route: "GET /seed", n: 40, avgMs: 120.5, msMax: 900, slow: 0 }],
    slow: [{ route: "GET /projects/{pid}", n: 12, avgMs: 1400, msMax: 2200, slow: 7 }],
    errors: [{ code: "402 POST /projects/{pid}/jobs", n: 3 }],
    capCodes: [{ code: "filePages413", n: 9 }],
    waste: [{ code: "repairReverted", n: 31 }],
    provider: [{ code: "rate", n: 5 }],
    hints: [{ kind: "money", code: "bigFiles", n: 9, who: [{ tenant: "acme", n: 9 }] },
            { kind: "money", code: "invoicedUnpaid", n: 2, total: 800, currency: "USD" },
            { kind: "loss", code: "thinMargin", tenant: "acme", name: "Акме", n: 0.2,
              cost: 0.06, price: 4 },
            { kind: "fix", code: "provider:rate", n: 5 }],
    eventsPending: 0, store: "file",
  };
  const metRender = (m, days) => {
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    hooks[0] = OV; hooks[2] = "metrics";
    // Порядок хуков: TabAdmin 0–2, дальше TabMetrics: days(3), m(4), busy(5).
    hooks[3] = days || 7; hooks[4] = m; hooks[5] = false;
    try { return texts(TabAdmin({ store: superStore, toast })).join(" "); }
    catch (e) { check(false, "рендер «Метрик» — " + e.constructor.name + ": " + e.message); return null; }
  };
  const met = metRender(MET);
  check(!!met && met.includes("Метрики"), "переключатель вкладки метрик на месте");
  check(!!met && met.includes("Деньги на столе") && met.includes("Теряем") && met.includes("Чинить"),
        "три вида подсказок названы словами");
  check(!!met && met.includes("9") && met.includes("acme"),
        "подсказка несёт число и организацию — без них её нечем продать");
  check(!!met && !/\bbigFiles\b/.test(met) && !/\bthinMargin\b/.test(met) && !/\bprovider:rate\b/.test(met),
        "код подсказки на экран не выходит: у каждого есть фраза");
  check(!!met && met.includes("Себест./стр."), "себестоимость страницы в таблице организаций");
  check(!!met && met.includes("Технические подробности: маршруты, скорость, ошибки"),
        "техническое убрано под «Подробности», а не смешано с деньгами");
  check(!!met && met.includes("Прислать в Telegram"), "сводку словами можно отправить себе");
  const empty = metRender(Object.assign({}, MET, { hints: [] }));
  check(!!empty && empty.includes("Ни одной находки за период"),
        "пустой ответ — это ответ, а не пустой экран");
  check(metRender(null) !== null, "вкладка рисуется до ответа сервера");
}

/* ---------- Вкладка «Возможности» ----------
   Экран отвечает на вопрос «где сервис упирается в себя»: во что упёрлись
   люди, чего у нас нет и докуда они доходят. Сторожим ровно то, что ломается
   молча: код тупика обязан превратиться во фразу (забудь строку в
   `oppBlockText` — и владелец увидит `dead.writeback`), Парето обязан
   отделить «браться сейчас» от хвоста, а отказ — превратиться в «нёс файл —
   файл больше потолка», потому что «413 POST /projects/upload» владельцу
   сервиса не говорит ничего. */
{
  const OPP = {
    ok: true, days: 7, from: "2026-09-14", to: "2026-09-20", live: false, at: "12:30:05",
    blocked: [
      { code: "cap.filePages413", n: 80, kind: "money", share: 0.8, cum: 0.8, vital: true,
        items: [], who: [{ tenant: "acme", n: 80 }] },
      { code: "cap.format415", n: 15, kind: "money", share: 0.15, cum: 0.95, vital: false,
        items: [{ name: "pdf", n: 12 }, { name: "epub", n: 3 }], who: [] },
      { code: "dead.writeback", n: 5, kind: "money", share: 0.05, cum: 1, vital: false,
        items: [{ name: "odt", n: 5 }], who: [] },
    ],
    errors: [{ code: "413 POST /projects/upload", route: "POST /projects/upload",
               act: "upload", status: 413, n: 5, share: 1, cum: 1, vital: true }],
    funnel: { steps: [{ code: "upload", n: 15 }, { code: "run", n: 9 }, { code: "export", n: 4 }],
              byExt: [{ name: "pdf", n: 10 }], byKind: [{ name: "full", n: 9 }],
              dropRun: 6, dropExport: 5, conv: 0.267 },
    waste: [{ code: "repairReverted", n: 31 }], provider: [],
    money: [{ kind: "money", code: "pagesLow", tenant: "acme", name: "Акме", n: 12 }],
    quotes: { byStatus: {}, total: 0, currency: "USD", conversion: null },
    paretoShare: 0.8, eventsPending: 0,
  };
  const oppRender = (d) => {
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    hooks[0] = OV; hooks[2] = "chances";
    // Порядок хуков: TabAdmin 0–2, дальше TabChances: days(3), d(4), busy(5), auto(6).
    hooks[3] = 7; hooks[4] = d; hooks[5] = false; hooks[6] = true;
    try { return texts(TabAdmin({ store: superStore, toast })).join(" "); }
    catch (e) { check(false, "рендер «Возможностей» — " + e.constructor.name + ": " + e.message); return null; }
  };
  const opp = oppRender(OPP);
  check(!!opp && opp.includes("Возможности"), "переключатель новой вкладки на месте");
  check(!!opp && !/\bcap\.\w+|\bdead\.\w+/.test(opp),
        "код тупика на экран не выходит: у каждого есть фраза");
  check(!!opp && opp.includes("80") && opp.includes("от всех") && opp.includes("накопл."),
        "доля и накопленная доля видны: без них список не говорит, за что браться");
  check(!!opp && opp.includes("Ниже — хвост"),
        "хвост Парето отделён от жизненно важного меньшинства");
  check(!!opp && opp.includes("pdf×12"), "улики названы поимённо");
  check(!!opp && opp.includes("нёс файл") && opp.includes("файл больше потолка"),
        "отказ переведён на человеческий: маршрут и код владельцу ничего не говорят");
  check(!!opp && opp.includes("принесли файл") && opp.includes("забрали перевод"),
        "воронка названа словами");
  check(!!opp && opp.includes("Это не когорта"),
        "оговорка про когорту не спрятана: иначе числа прочтут как путь одного человека");
  check(!!opp && opp.includes("Живое обновление"), "живое обновление можно выключить");
  check(!!opp && opp.includes("Деньги по организациям") && opp.includes("Акме"),
        "денежные подсказки по организациям на месте");
  const bare = oppRender(Object.assign({}, OPP, { blocked: [], errors: [], money: [] }));
  check(!!bare && bare.includes("За период никто ни во что не упёрся"),
        "пустой ответ — это ответ, а не пустой экран");
  check(oppRender(null) !== null, "вкладка рисуется до ответа сервера");
}

/* ---- Вкладка «Роли и доступы» -------------------------------------------
   Экран правит РОЛЬ и показывает, что человеку позволено. Что сторожим:
   1) вкладка есть и рисуется до ответа сервера (числа грузятся своим
      запросом — как у «Метрик» и «Возможностей»);
   2) роль показана ПО КОМАНДАМ: домашняя правится, чужая названа. Одна
      ячейка «владелец» скрыла бы ровно то, ради чего экран заведён;
   3) себе роль не снять и себя не отключить — кнопки погашены (право
      проверяет сервер, но предлагать нельзя то, что он отвергнет);
   4) лимиты названы числами организации, а не выдуманы браузером;
   5) объяснение ролей на экране, и в нём сказано, что владелец — владелец
      СВОЕЙ организации: на этот вопрос экран обязан отвечать сам. */
{
  const ACC = {
    ok: true, roles: ["owner", "editor", "translator"],
    capDefaults: { maxPages: 500, maxProjects: 0 },
    tenants: [
      { id: "acme", name: "Акме", active: true, signup: true, limitUsd: 12.5, simple: false,
        caps: { maxPages: 500 }, usage: { pages: 300, used: 300, credit: 500 },
        spend: { over: false, spentUsd: 3 } },
      { id: "beta", name: "Бета", active: true, team: true, limitUsd: null, simple: true,
        caps: { maxPages: 0 }, usage: { pages: 10, used: 10, credit: 0 },
        spend: { over: true, spentUsd: 99 } },
    ],
    users: [
      { id: 1, login: "admin", email: "", name: "Администратор", role: "owner", tenant: "acme",
        super: true, active: true, emailVerified: false, loginCount: 7, lastLogin: "2026-09-20 10:00",
        created: "2026-01-01", teams: [{ id: "acme", name: "Акме", role: "owner", home: true }] },
      { id: 2, login: "eva@mail.ru", email: "eva@mail.ru", name: "Ева", role: "translator",
        tenant: "acme", super: false, active: true, emailVerified: true, loginCount: 3,
        lastLogin: "2026-09-21 09:00", created: "2026-02-02",
        teams: [{ id: "acme", name: "Акме", role: "translator", home: true },
                { id: "beta", name: "Бета", role: "owner", home: false }] },
      { id: 3, login: "new@mail.ru", email: "new@mail.ru", name: "Новичок", role: "owner",
        tenant: "beta", super: false, active: false, emailVerified: false, loginCount: 0,
        created: "2026-09-01", teams: [{ id: "beta", name: "Бета", role: "owner", home: true }] },
    ],
  };
  global.API.adminAccess = async () => ACC;
  const accStore = { can: { owner: true, super: true }, tab: "admin", go() {}, me: { id: 1 } };
  function accRender(data) {
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    hooks[0] = OV; hooks[2] = "access";
    // Порядок хуков: TabAdmin 0–2, дальше TabAccess: d(3), q(4), role(5), only(6).
    hooks[3] = data;
    try { return texts(TabAdmin({ store: accStore, toast })).join(" "); }
    catch (e) { check(false, "«Роли и доступы» — " + e.constructor.name + ": " + e.message); return null; }
  }
  const acc = accRender(ACC);
  check(!!acc && acc.includes("Роли и доступы"), "переключатель вкладки «Роли и доступы» на месте");
  check(accRender(null) !== null, "вкладка рисуется до ответа сервера");
  check(!!acc && acc.includes("Ева") && acc.includes("Новичок"), "люди названы");
  check(!!acc && acc.includes("eva@mail.ru"), "почта видна");
  check(!!acc && acc.includes("Акме") && acc.includes("Бета"), "организация человека названа именем, а не только кодом");
  check(!!acc && acc.includes("ещё в командах") && acc.includes("владелец"),
        "роль в ЧУЖОЙ команде названа: одна ячейка скрыла бы второй доступ");
  check(!!acc && acc.includes("Что значит роль") && acc.includes("владельцем"),
        "экран сам объясняет, что владелец — владелец СВОЕЙ организации");
  check(!!acc && acc.includes("это вы"), "себя видно: роль себе не снять");
  check(!!acc && acc.includes("$12.50"), "лимит организации показан числом");
  check(!!acc && acc.includes("исчерпан"), "исчерпанный лимит назван");
  check(!!acc && acc.includes("300 / 500"), "страницы: списано из выданного");
  check(!!acc && acc.includes("не подтверждена"), "неподтверждённая почта названа");
  check(!!acc && acc.includes("ни разу"), "«ни разу не входил» — это ответ, а не пустота");
  check(!!acc && acc.includes("Лимиты") && acc.includes("Пароль") && acc.includes("Отключить"),
        "команды над человеком на месте");
  check(!!acc && acc.includes("Добавить пользователя"), "завести человека можно отсюда");

  /* Себе роль не снять и себя не отключить: сервер отвечает 400, и кнопка
     обязана быть погашена — предлагать то, что отвергнут, нельзя. */
  {
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    hooks[0] = OV; hooks[2] = "access"; hooks[3] = ACC;
    const tree = TabAdmin({ store: accStore, toast });
    /* Заглушка вызывает функциональные компоненты СРАЗУ, поэтому ни RoleSelect,
       ни Btn в дереве не встречаются — там уже <select> и <button>. Ищем их. */
    let selfRole = null, otherRole = null, selfOff = null, otherOff = null;
    (function walk(n) {
      if (!n || typeof n !== "object") return;
      if (Array.isArray(n)) return n.forEach(walk);
      const p = n.props || {};
      if (n.type === "select" && (n.children || []).some(c => c && c.props && c.props.value === "owner")) {
        if (p.disabled) selfRole = true; else otherRole = true;
      }
      if (n.type === "button" && (n.children || []).includes("Отключить")) {
        if (p.disabled) selfOff = true; else otherOff = true;
      }
      (n.children || []).forEach(walk);
    })(tree);
    check(selfRole === true && otherRole === true,
          "свою роль менять нечем, чужую — можно: гашение точечное");
    check(selfOff === true && otherOff === true,
          "себя не отключить, а других — можно: гашение точечное, а не на всю таблицу");
  }

  /* Ответ БЕЗ `users` не должен ронять экран. Поймано настоящим ответом
     сервера: заглушка всегда клала список, а `d.users.length` на ответе
     без ключа — это белый экран ВСЕЙ админки, а не пустая таблица. */
  check(accRender({ ok: true }) !== null, "ответ без списка людей экран не роняет");
  const bare = accRender({ ok: true, users: [], tenants: [] });
  check(bare !== null && bare.includes("Люди · 0"), "пустой список — это ответ, а не пустой экран");

  /* Людей на «Сводке» больше нет: два места, правящих одних и тех же людей,
     разошлись бы первой же правкой. */
  {
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    hooks[0] = OV; hooks[2] = "summary";
    const sum = texts(TabAdmin({ store: accStore, toast })).join(" ");
    check(!sum.includes("Аккаунты ·"), "таблица людей со «Сводки» убрана — она живёт на своей вкладке");
  }
}

console.log(fail.length ? "\nПРОВАЛЕНО: " + fail.length : "\nВсё сошлось");
process.exit(fail.length ? 1 : 0);
