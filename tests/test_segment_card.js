/* Карточка сегмента (SegDetail) — рендер без браузера.

   Зачем написан. Карточку не рендерил НИ ОДИН тест: `test_editor_render.js`
   глушит её заглушкой (`global.SegDetail = () => null`), а python-тесты читают
   файл текстом. То есть ошибка в ней = белый экран у пользователя при всех
   зелёных наборах — ровно тот класс, ради которого заведён рендер редактора.

   Здесь карточка вызывается по-настоящему с заглушкой React (никакого Babel
   и npm) и проверяется то, что человек обязан увидеть: вердикт ревизии,
   его устаревание, причину, по которой правку не поставили, и человеческие
   подписи вето вместо внутренних ключей. */
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
const store = { memory: {}, getItem(k) { return this.memory[k] || null; },
                setItem(k, v) { this.memory[k] = String(v); }, removeItem(k) { delete this.memory[k]; } };
global.React = React;
global.useState = useState; global.useEffect = useEffect; global.useRef = useRef;
global.useMemo = useMemo; global.useCallback = useCallback;
global.createContext = createContext; global.useContext = useContext;
global.localStorage = store; global.sessionStorage = store;
global.window = global;
global.document = { addEventListener() {}, removeEventListener() {}, querySelector() { return null; } };
global.API = { safeCall: async (fn) => fn() };
/* Перевода нет — обе функции обязаны возвращать строку как есть: на русском
   TR(s) === s побитово, это и есть страховка инварианта 17. */
global.TR = (s) => s;
global.TRS = (s) => s;
global.bcScoreColor = () => "#000";

function load(file) {
  const src = fs.readFileSync(path.join("frontend", "js", file), "utf8")
    // JSX в этих файлах не используется — компоненты собираются через
    // React.createElement, поэтому файл выполняется как обычный JS.
    .replace(/^\s*\/\*\s*global[^*]*\*\/\s*$/gm, "");
  (0, eval)(src);
}

// Мелкие компоненты общего слоя нужны карточке живыми.
load("ui.jsx");
load("tab_editor_detail.jsx");

check(typeof SegDetail === "function", "SegDetail собрался и это функция");

const project = { id: 1, src: "RU", tgt: "EN", segments: [] };
/* Ровно то, что карточка читает у хранилища: глоссарий и память переводов
   она перебирает сама, чтобы показать подсказки по сегменту. */
const storeStub = { updateSegment() {}, replaceProjectSegments() {}, addComment() {},
                    glossary: [{ src: "пневмоторакс", tgt: "pneumothorax", tier: "verified" }],
                    tm: [] };
const toast = { info() {}, warning() {}, error() {}, success() {} };

function render(seg) {
  hookIdx = 0;
  const out = [];
  (function walk(n) {
    if (n === null || n === undefined || n === false || n === true) return;
    if (Array.isArray(n)) return n.forEach(walk);
    if (typeof n === "string" || typeof n === "number") { out.push(String(n)); return; }
    if (typeof n === "object") {
      const p = n.props || {};
      ["title", "label", "aria-label", "placeholder"].forEach(k => { if (p[k]) out.push(String(p[k])); });
      (n.children || []).forEach(walk);
    }
  })(SegDetail({ seg, project, store: storeStub, toast, models: [], onClose() {} }));
  return out.join("\n");
}

/* Поля, которые карточка читает БЕЗ защиты (seg.comments.length и т.п.).
   Настоящий сегмент приходит с сервера ровно таким — `_segment_for_client`
   отдаёт запись целиком. */
const BASE = { id: 1, source: "Закрытый пневмоторакс.", target: "Closed pneumothorax.",
               status: "translated", comments: [], qa_issues: [] };

console.log("=== 1. Карточка собирается на голом сегменте ===");
const plain = render(Object.assign({}, BASE));
check(plain.length > 0, "рендер не упал и что-то выдал");
check(plain.indexOf("Ревизия") === -1, "без вердикта блока ревизии нет");

console.log("");
console.log("=== 2. Вердикт ревизии виден человеку ===");
// До этой карточки вердикт не показывался НИГДЕ: человек получал переписанный
// сегмент без объяснения, за что.
const applied = render(Object.assign({}, BASE, {
  review: { score: 4, issues: ["неестественный английский"], applied: true,
            from: "Artificial pneumothorax treatment is closed.",
            model: "gpt-5.6-terra", at: "2026-09-02 12:00", stale: false },
}));
check(applied.indexOf("Ревизия исправила перевод") !== -1, "сказано, что текст переписан");
check(applied.indexOf("оценка ") !== -1 && applied.indexOf("4") !== -1, "оценка названа");
check(applied.indexOf("неестественный английский") !== -1, "замечание показано");
check(applied.indexOf("Artificial pneumothorax") !== -1, "прежний текст виден — есть с чем сравнить");

console.log("");
console.log("=== 3. Устаревший вердикт не выдаётся за действующий ===");
// Признак считает СЕРВЕР (_review_stale): он знает и про версию вопросов,
// и про правку ОРИГИНАЛА. Без этой строки карточка показывала бы «исправила
// перевод» про текст, которого уже нет, — тот же класс, что staleBc у полос.
const stale = render(Object.assign({}, BASE, {
  review: { score: 4, issues: ["калька"], applied: true, from: "Old text.",
            model: "m", stale: true },
}));
check(stale.indexOf("Текст менялся после ревизии") !== -1,
      "сказано, что сказанное относится к прежней версии");

console.log("");
console.log("=== 4. Причина отказа — словами, а не ключами ===");
// В `veto` лежат внутренние ключи (gloss, hard), которых нет ни в одном
// словаре: на экране это была латиница посреди узбекской фразы. Подписи
// собирает сервер (REVIEW_VETO_LABELS) и присылает в vetoLabels.
const vetoed = render(Object.assign({}, BASE, {
  review: { score: 4, issues: [], applied: false, skipped: "не прошёл сверку",
            veto: ["gloss", "hard"],
            vetoLabels: ["нарушено приказных терминов больше",
                         "расхождение чисел, единиц или отрицания"],
            model: "m", stale: false },
}));
check(vetoed.indexOf("Правка не поставлена") !== -1, "отказ назван");
check(vetoed.indexOf("нарушено приказных терминов больше") !== -1,
      "и назван человеческой подписью");
check(vetoed.indexOf("gloss") === -1 && vetoed.indexOf("hard") === -1,
      "внутренние ключи на экран не попадают");

console.log("");
console.log("=== 5. Повреждённый оригинал и откат человека ===");
const suspect = render(Object.assign({}, BASE, {
  review: { score: 3, issues: ["исходник бессвязен"], applied: false,
            sourceSuspect: true, skipped: "оригинал под подозрением",
            model: "m", stale: false },
}));
check(suspect.indexOf("повреждён сам оригинал") !== -1,
      "класс, где машина бессильна, назван прямо");
const undone = render(Object.assign({}, BASE, {
  review: { score: 4, issues: [], applied: false, undone: { by: "u1", at: "now" },
            model: "m", stale: false },
}));
check(undone.indexOf("откачена человеком") !== -1,
      "решение человека видно и сказано, что повторно не предложат");

console.log("");
console.log("=== 6. Старые записи без новых полей карточку не роняют ===");
// В боевых данных лежат вердикты, записанные до появления stale/vetoLabels.
const old = render(Object.assign({}, BASE, { review: { score: 8 } }));
check(old.indexOf("Ревизия") !== -1, "рендер пережил запись без единого нового поля");

console.log("");
if (fail.length) {
  console.log("ПРОВАЛЕНО: " + fail.length);
  fail.forEach(f => console.log("  - " + f));
  process.exit(1);
}
console.log("ВСЁ ПРОШЛО");
