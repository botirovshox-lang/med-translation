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
console.log("=== 7. Кто заверил — видно ===");
// След ответственного: id → имя даёт сервер (confirmedByName), роль на момент
// подписи — с записи. Прежняя отметка "human" — заверение до учёта авторов.
const signed = render(Object.assign({}, BASE, {
  status: "confirmed", confirmedBy: 7, confirmedByName: "Ева", confirmedRole: "editor",
  confirmedAt: "2026-09-04 12:00", editedBy: 7, editedByName: "Ева", editedAt: "2026-09-04 11:50",
}));
check(signed.indexOf("Подтвердил: ") !== -1 && signed.indexOf("Ева") !== -1 && signed.indexOf("редактор") !== -1,
      "подпись: кто, в какой роли");
check(signed.indexOf("2026-09-04 12:00") !== -1, "…и когда");
check(signed.indexOf("Правил: ") !== -1, "правка руками названа");
const legacy = render(Object.assign({}, BASE, { status: "confirmed", confirmedBy: "human" }));
check(legacy.indexOf("человек (до учёта авторов)") !== -1, "старая отметка без автора не выдаётся за имя");
const withdrawn = render(Object.assign({}, BASE, {
  status: "translated", unconfirmed: { by: 7, withdrawnBy: 7, how: "edit", withdrawnAt: "2026-09-04 12:30" },
}));
check(withdrawn.indexOf("Заверение снято") !== -1 && withdrawn.indexOf("правкой текста") !== -1,
      "снятая подпись названа, а не пропала молча");
storeStub.can = { owner: false, super: false, role: "translator" };
const asTranslator = render(Object.assign({}, BASE));
delete storeStub.can;
check(asTranslator.indexOf("Подтвердить") !== -1, "кнопка «Подтвердить» есть у любой роли: заверяет каждый, след — подпись");

console.log("");
console.log("=== 8. Имя модели человеку не показывается ===");
/* Имя модели — УСТРОЙСТВО системы (инвариант 24, modelsShown в ui.jsx):
   человек решений по нему не принимает, а на экране оно выглядит утечкой
   внутренностей. Карточка сегмента была последним местом, где оно стояло
   у всех подряд: «оценка 6/10 · gpt-5.6-terra · 2026-09-16 13:11». Время
   при этом остаётся — оно отвечает на вопрос «когда смотрели». */
const withModels = Object.assign({}, BASE, {
  review: { score: 6, issues: [], applied: false, model: "gpt-5.6-terra", at: "2026-09-16 13:11" },
  backcheck: { score: 88, model: "gpt-5.6-sol", at: "2026-09-16 13:05", reasons: [] },
  termcheck: { findings: [], model: "gpt-5.6-terra", at: "2026-09-16 13:07", stale: false },
});
const plainUser = render(withModels);
check(plainUser.indexOf("gpt-5.6") === -1, "ни в одной карточке имени модели нет");
check(plainUser.indexOf("2026-09-16 13:11") !== -1, "…а время осталось и не начинается с разделителя");
check(plainUser.split("\n").every(l => l[0] !== "·"), "ни одна подпись не начинается с висячего разделителя");
/* Эксперту устройство возвращается: он по нему и принимает решения. */
storeStub.can = { owner: true, super: true };
const asSuper = render(withModels);
delete storeStub.can;
check(asSuper.indexOf("gpt-5.6-terra") !== -1, "системному администратору модель названа");

/* Дальше — действия в карточке: жмём кнопки так, как это сделал бы человек,
   и перерисовываем. Состояние хуков сбрасывается перед каждым сюжетом:
   заглушка useState помнит черновик прошлого сегмента. */
const textOf = (n) => {
  const out = [];
  (function walk(x) {
    if (x === null || x === undefined || x === false || x === true) return;
    if (Array.isArray(x)) return x.forEach(walk);
    if (typeof x === "string" || typeof x === "number") { out.push(String(x)); return; }
    const p = x.props || {};
    ["title", "label", "aria-label", "placeholder"].forEach(k => { if (p[k]) out.push(String(p[k])); });
    (x.children || []).forEach(walk);
  })(n);
  return out.join("\n");
};
const findAll = (n, pred, out) => {
  out = out || [];
  if (!n || typeof n !== "object") return out;
  if (Array.isArray(n)) { n.forEach(c => findAll(c, pred, out)); return out; }
  if (pred(n)) out.push(n);
  (n.children || []).forEach(c => findAll(c, pred, out));
  return out;
};
const btn = (tree, label) => findAll(tree, n => n.type === "button"
  && (n.children || []).some(c => typeof c === "string" && c.indexOf(label) !== -1))[0];
const draw = (seg, extra) => { hookIdx = 0;
  return SegDetail(Object.assign({ seg, project, store: storeStub, toast, models: [] }, extra || {})); };

console.log("");
console.log("=== 9. Обратный перевод к прежнему тексту назван устаревшим ===");
// Сохранённый ответ показывается без нового вызова модели — но если перевод
// с тех пор менялся, выдавать его за нынешний нельзя.
const openBackPanel = (seg) => {
  hooks.length = 0;
  btn(draw(seg), "Подробности").props.onClick();
  btn(draw(seg), "Back check").props.onClick();
  return draw(seg);
};
const bcStaleSeg = Object.assign({}, BASE, {
  backcheck: { score: 70, back: "Старый обратный перевод.", stale: true, reasons: [] } });
const tStale = textOf(openBackPanel(bcStaleSeg));
check(tStale.indexOf("Старый обратный перевод.") !== -1, "сохранённый ответ показан без вызова модели");
check(tStale.indexOf("Устарел — перевод изменился") !== -1, "и назван устаревшим");
check(tStale.indexOf("Проверить заново") !== -1, "рядом — кнопка пересчёта");
const tFresh = textOf(openBackPanel(Object.assign({}, bcStaleSeg,
  { backcheck: Object.assign({}, bcStaleSeg.backcheck, { stale: false }) })));
check(tFresh.indexOf("Старый обратный перевод.") !== -1 && tFresh.indexOf("Устарел") === -1,
      "свежий ответ пометки не получает");

console.log("");
console.log("=== 10. Стёртый перевод сохраняется как «Новый» ===");
const saved = [];
storeStub.updateSegment = (pid, id, patch) => { saved.push(patch); };
const saveWith = (seg, text) => {
  hooks.length = 0; saved.length = 0;
  const t = draw(seg);
  findAll(t, n => n.type === "textarea")[0].props.onChange({ target: { value: text } });
  btn(draw(seg), "Сохранить").props.onClick();
  return saved[0] || {};
};
check(saveWith(Object.assign({}, BASE), "").status === "new",
      "пустой черновик уходит со статусом «new», а не «translated»");
check(saveWith(Object.assign({}, BASE), "   ").status === "new", "пробелы — тоже пусто");
check(saveWith(Object.assign({}, BASE, { status: "new", target: "" }), "Open pneumothorax.").status === "translated",
      "вписанный в новый сегмент текст — «translated», как и было");
storeStub.updateSegment = () => {};

console.log("");
console.log("=== 11. Слова из «Проверки» горят в карточке ===");
hooks.length = 0;
const hlTree = draw(Object.assign({}, BASE), { hlTerms: ["Пневмоторакс", "pneumothorax"], onClose() {} });
const srcCard = findAll(hlTree, n => /seg-src/.test((n.props || {}).className || ""))[0];
const srcMarks = findAll(srcCard, n => n.type === "mark").map(m => m.children.join(""));
check(srcMarks.join("|") === "пневмоторакс", "в оригинале подсвечен термин, регистр не важен (" + srcMarks.join("|") + ")");
const tgtHl = findAll(hlTree, n => (n.props || {}).className === "seg-tgt-hl")[0];
check(!!tgtHl && findAll(tgtHl, n => n.type === "mark").map(m => m.children.join("")).join("|") === "pneumothorax",
      "под полем перевода — перевод с подсвеченным вариантом");
check(textOf(hlTree).indexOf("Проверить слова: ") !== -1, "и слова названы строкой");
check(!!findAll(hlTree, n => n.type === "button" && n.props["aria-label"] === "Закрыть карточку")[0],
      "у карточки есть «×»");
hooks.length = 0;
check(textOf(draw(Object.assign({}, BASE))).indexOf("Проверить слова") === -1, "без выборки строки слов нет");

console.log("");
console.log("=== 12. Пустое не заверяется; прежний перевод — подсказка с «Вставить» ===");
/* «Подтвердить» на пустом черновике погашена: сервер отвечает 400, а раньше
   браузер всё равно ставил «подтверждено» и хвалил тостом. */
hooks.length = 0;
const emptySeg = Object.assign({}, BASE, { target: "", status: "new" });
const confirmBtn = btn(draw(emptySeg), "Подтвердить");
check(!!confirmBtn && confirmBtn.props.disabled === true, "пустой черновик — «Подтвердить» погашена");
hooks.length = 0;
check(btn(draw(Object.assign({}, BASE)), "Подтвердить").props.disabled === false, "с переводом — доступна");
/* prevTarget (смена оригинала, пересегментация) — только для чтения, и
   «Вставить» кладёт его в черновик без вызова модели и без записи. */
let wrote = 0;
storeStub.updateSegment = () => { wrote++; };
const prevSeg = Object.assign({}, emptySeg, { prevTarget: "Old closed pneumothorax.", prevSource: "Закрытый пневмоторакс слева." });
hooks.length = 0;
const pv = draw(prevSeg);
check(textOf(pv).indexOf("Прежний перевод") !== -1 && textOf(pv).indexOf("Old closed pneumothorax.") !== -1
      && textOf(pv).indexOf("Закрытый пневмоторакс слева.") !== -1, "прежний перевод и его оригинал показаны");
btn(pv, "Вставить").props.onClick();
const after = draw(prevSeg);
const ta = findAll(after, n => n.props && n.props.placeholder === "Введите перевод…")[0];
check(ta && ta.props.value === "Old closed pneumothorax.", "«Вставить» положил прежний перевод в черновик");
check(wrote === 0, "и ничего не записал на сервер");
check(textOf(after).indexOf("Прежний перевод") === -1, "совпавший с черновиком — подсказка скрыта");
check(btn(after, "Подтвердить").props.disabled === false, "черновик не пуст — можно заверить");
storeStub.updateSegment = () => {};
hooks.length = 0;
check(textOf(draw(Object.assign({}, BASE))).indexOf("Прежний перевод") === -1, "без prevTarget подсказки нет");

console.log("");
if (fail.length) {
  console.log("ПРОВАЛЕНО: " + fail.length);
  fail.forEach(f => console.log("  - " + f));
  process.exit(1);
}
console.log("ВСЁ ПРОШЛО");
