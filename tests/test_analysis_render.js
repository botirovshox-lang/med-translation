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

// ── 1b. Отменённые баллом правки: строка есть всегда, кнопка — по числу ──
console.log("");
console.log("=== 1b. «Ремонт отменил верную правку» ===");
check(ok1 && !texts(tree1).some(t => t.indexOf("Принять все") !== -1),
      "принимать нечего — кнопки нет, иначе она обещала бы работу, которой нет");

const VETOED = JSON.parse(JSON.stringify(BASE));
VETOED.human.reverted = [7, 8, 9];
VETOED.human.revertedByScore = [7, 8];
let treeV = null, okV = true;
try { treeV = render(React.createElement(WorkSummary, { summary: VETOED, store, toast })); }
catch (e) { okV = false; console.log("      " + e.message); }
check(okV, "рендер со списком отменённых прошёл");
const tV = okV ? texts(treeV) : [];
check(tV.some(s => s.indexOf("Ремонт отменил верную правку") !== -1),
      "своя строка на экране есть");
check(tV.some(s => s.indexOf("Принять все") !== -1),
      "и кнопка пакетного принятия при ней");
// revertedByScore — ПОДМНОЖЕСТВО reverted, и общая строка не должна считать
// его дважды: 3 всего, 2 из них с готовым текстом, значит в общей строке 1.
check(tV.filter(s => s === "1").length >= 1,
      "в «не стало лучше» осталось 3 - 2 = 1: подмножество не посчитано дважды");

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

// ─────────── 3b. Корзины «под ключ»: проценты, кнопка, строка QA ───────────
console.log("\n=== 3b. TurnkeySummary: три корзины с процентами ===");
const TK = JSON.parse(JSON.stringify(BASE));
TK.total = 4;
TK.turnkey = { ready: [1, 2], machine: [3], human: [4], case: [3],
               params: { steps: ["translate"], use_judge: true, judge_all: true,
                         retry: false, include_confirmed: false } };
TK.human.qaCritical = [4];
let treeTk = null, okTk = true;
try { treeTk = render(React.createElement(TurnkeySummary, { summary: TK, store, toast })); }
catch (e) { okTk = false; console.log("      " + e.message); }
check(okTk, "TurnkeySummary рендерится");
const tTk = okTk ? texts(treeTk) : [];
check(tTk.some(s => s === "Готово к сдаче") && tTk.some(s => s === "Возьмёт ближайший прогон")
      && tTk.some(s => s === "Нужно ваше решение"),
      "три корзины названы");
check(tTk.filter(s => s === "50%").length >= 2 && tTk.filter(s => s === "25%").length >= 2,
      "и у каждой процент: готовность 50%, корзины 50/25/25");
check(tTk.some(s => s.indexOf("Перевести и доделать") !== -1),
      "главная кнопка на месте");
check(tTk.some(s => s.indexOf("2 из 4") !== -1),
      "готовность названа и числом сегментов");

console.log("\n=== 3c. WorkSummary: критика Medical QA на подтверждённом видна ===");
const QA = JSON.parse(JSON.stringify(BASE));
QA.human.qaCritical = [7, 9];
let treeQa = null, okQa = true;
try { treeQa = render(React.createElement(WorkSummary, { summary: QA, store, toast })); }
catch (e) { okQa = false; console.log("      " + e.message); }
check(okQa, "рендер прошёл");
check(okQa && texts(treeQa).some(s => s.indexOf("Medical QA нашла критичное") !== -1),
      "строка qaCritical есть — вкладки «Замечания» больше нет, показывать больше негде");
// Строка одна на весь экран (SegRow), но доля показывается ТОЛЬКО там, где
// целое известно: в подробном итоге часть строк считает термины, а не
// сегменты, и процент от чужого целого был бы выдумкой.
check(okQa && !texts(treeQa).some(s => /^\d+(\.\d)?%$/.test(s)),
      "в подробном итоге долей нет — их целое не определено");

// ─────────── 4. Начертание терминов: строка, кнопка и сама правка ───────────
// Правка бесплатная и детерминированная, но текст в проекте она всё-таки
// меняет — значит человек обязан увидеть, ЧТО изменится, и сколько таких мест.
console.log("\n=== 4. Начертание терминов не по оригиналу ===");

const project = { id: 1, segments: [{ id: 3, source: "туберкулемы", target: "Tuberculoma" }] };
let impact = { ok: true, terms: [], segments: [], pending: [], confirmed: [], caseSegments: [3] };
const calls = [];
const patched = [];
global.API.glossaryImpact = async () => impact;
global.API.termCase = async (pid, opts) => {
  calls.push(opts && opts.apply ? "apply" : "dry");
  return opts && opts.apply
    ? { ok: true, segments: 1, ids: [3] }
    : { ok: true, dryRun: true, segments: 1, ids: [3], skippedConfirmed: [7],
        samples: [{ id: 3, fixed: [{ was: "Tuberculoma", now: "tuberculoma" }] }] };
};
global.API.fetchSegments = async () => ({ ok: true, segments: [{ id: 3, target: "tuberculoma" }] });
const store4 = { updateSegment: (pid, sid, sg) => patched.push([pid, sid, sg.target]) };
let confirmText = "";
global.confirm = (t) => { confirmText = t; return true; };

async function renderCard(props) {
  hooks = []; hookIdx = 0; effects.length = 0;
  React.createElement(GlossaryImpact, props);          // заводит хуки и эффект
  effects.slice().forEach(fn => fn());                  // useEffect стуб их только копит
  await new Promise(r => setImmediate(r));              // даём промисам дорешаться
  hookIdx = 0; effects.length = 0;
  return React.createElement(GlossaryImpact, props);
}

const props4 = { project, store: store4, toast, onDrill() {}, T: () => null };
(async () => {
  let tree4 = null, ok4 = true;
  try { tree4 = await renderCard(props4); }
  catch (e) { ok4 = false; console.log("      " + e.message); }
  check(ok4, "карточка соответствия рендерится с отчётом сервера");
  const t4 = ok4 ? texts(tree4) : [];
  check(t4.some(s => s.indexOf("Начертание не по оригиналу") !== -1),
        "строка про начертание есть — иначе о расхождении неоткуда узнать");
  check(t4.some(s => s.indexOf("чинится без вызовов модели") !== -1),
        "и сказано, что это бесплатно: иначе кнопку побоятся нажать");
  check(t4.some(s => s.indexOf("Привести начертание") !== -1),
        "кнопка на месте");

  // Ноль — строка остаётся, кнопка уходит: пропавшая строка выглядит
  // благополучнее, чем есть, а кнопке при нуле делать нечего.
  impact = Object.assign({}, impact, { caseSegments: [] });
  const zero = await renderCard(props4);
  check(texts(zero).some(s => s.indexOf("всё по оригиналу") !== -1),
        "при нуле строка не исчезает, а говорит, что ноль настоящий");
  check(!texts(zero).some(s => s.indexOf("Привести начертание") !== -1),
        "а кнопки нет: править нечего");

  // Старый сервер отвечает без caseSegments — экран обязан пережить.
  impact = { ok: true, terms: [], segments: [], pending: [], confirmed: [] };
  let okOld = true;
  try { await renderCard(props4); } catch (e) { okOld = false; console.log("      " + e.message); }
  check(okOld, "ответ сервера БЕЗ caseSegments карточку не роняет");

  // Сама правка: разбор → подтверждение → правка → подтягиваем только
  // изменившиеся сегменты, а не весь проект на пять мегабайт.
  impact = { ok: true, terms: [], segments: [], pending: [], confirmed: [], caseSegments: [3] };
  hooks = []; hookIdx = 0; effects.length = 0;
  const live = React.createElement(GlossaryImpact, props4);
  effects.slice().forEach(fn => fn());
  await new Promise(r => setImmediate(r));
  hookIdx = 0; effects.length = 0;
  let onClick = null;
  (function find(n) {
    if (!n || typeof n !== "object") return;
    if (n.props && typeof n.props.onClick === "function"
        && texts(n).some(s => s.indexOf("Привести начертание") !== -1)) onClick = n.props.onClick;
    (n.children || []).forEach(find);
  })(React.createElement(GlossaryImpact, props4));
  check(!!onClick, "у кнопки есть обработчик");
  if (onClick) {
    await onClick();
    await new Promise(r => setImmediate(r));
    check(calls.join(",") === "dry,apply",
          "сначала разбор, потом правка — и только с согласия: " + calls.join(","));
    check(confirmText.indexOf("Tuberculoma → tuberculoma") !== -1,
          "в подтверждении показано, что именно изменится");
    check(confirmText.indexOf("Заверенных человеком не трогаем: 1") !== -1,
          "и сказано про заверенные, которых правка не касается");
    check(patched.length === 1 && patched[0][2] === "tuberculoma",
          "подтянут только правленый сегмент: " + JSON.stringify(patched));
  }

  // ─────────── 4b. RunPanel: состав от сервера, галочки, запуск ───────────
  // Панель тратит деньги, поэтому проверяем именно то, на что человек смотрит
  // перед нажатием: состав по шагам приходит с СЕРВЕРА, бесплатные правки
  // названы числом и идут ДО прогона, а состав для задачи пересчитывается
  // после них — принятые тексты обязаны попасть в этот же прогон.
  console.log("\n=== 4b. RunPanel ===");
  const planSrv = {
    steps: [{ step: "translate", label: "Перевод", count: 2, model: "m1",
              modelLabel: "Модель 1", ids: [1, 2] },
            { step: "backcheck", label: "Back-check", count: 1, model: "m2",
              modelLabel: "Модель 2", ids: [1] }],
    ids: [1, 2], total: 2,
  };
  const catSrv = { models: [{ id: "m1", label: "Модель 1", in: 1, out: 2 },
                            { id: "m2", label: "Модель 2", in: 1, out: 2 }],
                   judgeDefault: "m2" };
  const seen = [];
  global.API.runPlan = async () => { seen.push("plan"); return planSrv; };
  global.API.listJobs = async () => ({ active: [], jobs: [] });
  global.API.createJob = async (pid, kind, ids, params) => {
    seen.push("job:" + kind + ":" + ids.length + ":judge_all=" + params.judge_all);
    return { ok: true, job: { id: 5, project: pid, created: "2026-08-30 10:00" } };
  };
  global.API.termCase = async (pid, o) => { seen.push("case:" + (o && o.apply)); return { ok: true, segments: 1, ids: [3] }; };
  global.API.acceptRepairBatch = async () => {
    seen.push("accept");
    return { ok: true, accepted: 2, ids: [4], stamp: "s1" };
  };
  const TKP = JSON.parse(JSON.stringify(TK));
  TKP.human.revertedByScore = [4];
  const storeRun = { activeProject: { id: 1, segments: [{ id: 1, source: "аа", target: "bb" },
                                                        { id: 2, source: "вв", target: "" }] },
                     go() {}, setSegmentFilter() {}, updateSegment() {} };
  let treeRp = null, okRp = true;
  try {
    hooks = []; hookIdx = 0; effects.length = 0;
    treeRp = React.createElement(RunPanel, { summary: TKP, store: storeRun, toast,
                                             plan: planSrv, cat: catSrv,
                                             onClose() {}, onStarted() {} });
  } catch (e) { okRp = false; console.log("      " + e.message); }
  check(okRp, "RunPanel рендерится с планом от сервера");
  const tRp = okRp ? texts(treeRp) : [];
  check(tRp.some(s => s.indexOf("Перевод") !== -1) && tRp.some(s => s.indexOf("2 сегм.") !== -1),
        "шаги и их состав показаны числом от сервера");
  check(tRp.some(s => s.indexOf("Модель 1") !== -1),
        "и модель шага названа — её выбирает сервер, а не браузер");
  check(tRp.some(s => s.indexOf("Привести начертание") !== -1)
        && tRp.some(s => s.indexOf("Принять правки") !== -1),
        "бесплатные правки названы отдельными галочками, а не спрятаны в кнопке");
  check(tRp.some(s => s.indexOf("нижняя граница") !== -1),
        "и сказано, что смета — нижняя граница");

  // Нажатие: начертание включено по умолчанию, принятие правок — нет.
  let runClick = null;
  (function find(n) {
    if (!n || typeof n !== "object") return;
    if (n.props && typeof n.props.onClick === "function"
        && texts(n).some(s => s.indexOf("Запустить") !== -1)) runClick = n.props.onClick;
    (n.children || []).forEach(find);
  })(treeRp);
  check(!!runClick, "у кнопки запуска есть обработчик");
  if (runClick) {
    await runClick();
    await new Promise(r => setImmediate(r));
    check(seen.indexOf("case:true") !== -1, "начертание правится до прогона (галочка по умолчанию)");
    // Подмена текста — не побочное действие кнопки: галочка выключена
    // по умолчанию, и без неё команда не зовётся вовсе.
    check(seen.indexOf("accept") === -1,
          "принятие отменённых правок по умолчанию НЕ выполняется: " + seen.join(","));
    check(seen.indexOf("case:true") < seen.findIndex(s => s.indexOf("job:") === 0),
          "и именно ДО постановки задачи: " + seen.join(","));
    check(seen.some(s => s.indexOf("job:full:") === 0 && s.indexOf("judge_all=true") !== -1),
          "задача поставлена с серверными параметрами, включая judge_all: " + seen.join(","));
    check(seen.filter(s => s === "plan").length === 1,
          "состав пересчитан после бесплатной правки — ровно один раз: " + seen.join(","));
  }

  // ─────────── 4c. Модели по шагам и подсказки о конфликтах ───────────
  // Выбор модели меняет и СОСТАВ (ранг termcheck, «проверял тот, кто
  // переводил»), и цену, поэтому он должен уходить в run-plan и в задачу
  // ОДНИМ телом. А модели, спорящие по роли (проверка себя, судья =
  // буквальный переводчик), называются вслух до нажатия.
  console.log("\n=== 4c. Модели по шагам ===");
  const planSame = JSON.parse(JSON.stringify(planSrv));
  planSame.steps[1].model = "m1";                    // back-check той же моделью, что перевод
  const setCalls = [];
  let treeMd = null, okMd = true;
  try {
    hooks = []; hookIdx = 0; effects.length = 0;
    treeMd = React.createElement(RunPanel, { summary: TKP, store: storeRun, toast,
                                             plan: planSame, cat: catSrv,
                                             mods: { judge_model: "m1" },
                                             setMod: (k, v) => setCalls.push(k + "=" + v),
                                             onClose() {}, onStarted() {} });
  } catch (e) { okMd = false; console.log("      " + e.message); }
  check(okMd, "RunPanel рендерится с выбором моделей");
  const tMd = okMd ? texts(treeMd) : [];
  check(tMd.filter(s => s === "по умолчанию").length >= 3,
        "у шагов и судьи есть выбор с пунктом «по умолчанию»");
  check(tMd.some(s => s.indexOf("Back-check той же моделью, что и перевод") !== -1),
        "проверка себя названа предупреждением");
  check(tMd.some(s => s.indexOf("Судья и обратный перевод одной моделью") !== -1),
        "судья = модель обратного перевода — тоже");
  check(!tMd.some(s => s.indexOf("Ремонт той же моделью") !== -1),
        "а про ремонт (другая модель) не врёт");
  check(JSON.stringify(tkPlanBody({ use_judge: true, judge_all: true },
                                  { bc_model: "m2", tc_model: "" }))
        === JSON.stringify({ use_judge: true, judge_all: true, bc_model: "m2" }),
        "tkPlanBody: пустой выбор не уходит, выбранное — уходит");

  // ─────────── 5. TabAnalysis: старый сервер без turnkey не роняет экран ───────────
  console.log("\n=== 5. TabAnalysis переживает ответ сервера без turnkey ===");
  global.API.analysis = async () => BASE;          // старый ответ, корзин нет
  global.API.runPlan = async () => ({ steps: [], ids: [], total: 0 });
  global.API.listJobs = async () => ({ active: [], jobs: [] });
  const storeTab = { activeProject: { id: 1, segments: [] }, glossary: [],
                     go() {}, setSegmentFilter() {}, updateSegment() {},
                     statusCounts() { return { failed: 0, qa: 0, all: 0 }; } };
  let okTab = true, treeTab = null;
  try {
    hooks = []; hookIdx = 0; effects.length = 0;
    React.createElement(TabAnalysis, { store: storeTab, toast });
    effects.slice().forEach(fn => fn());
    await new Promise(r => setImmediate(r));
    hookIdx = 0; effects.length = 0;
    treeTab = React.createElement(TabAnalysis, { store: storeTab, toast });
  } catch (e) { okTab = false; console.log("      " + e.message); }
  check(okTab, "TabAnalysis не падает на старом ответе");
  const tTab = okTab ? texts(treeTab) : [];
  check(tTab.some(s => s.indexOf("Сервер прежней версии") !== -1),
        "и говорит, почему корзин нет, а не молчит");
  check(tTab.some(s => s.indexOf("Проверено начисто") !== -1),
        "подробный итог при этом показан");
  check(tTab.some(s => s.indexOf("Экспорт перевода") !== -1),
        "кнопка экспорта на месте");

  console.log();
  if (fail.length) {
    console.log("ПРОВАЛЕНО: " + fail.length);
    fail.forEach(f => console.log("  - " + f));
    process.exit(1);
  }
  console.log("ВСЁ ПРОШЛО");
})();

