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
// i18n.js грузится первым и здесь: TR() зовут ВСЕ .jsx, и без него
// первый же рендер падает с ReferenceError. Словарь не подключаем —
// без него TR(s) === s, то есть тест видит ровно прежние надписи.
for (const f of ["i18n.js", "ui.jsx", "tab_preflight.jsx"]) {
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
check(t3.some(s => s.indexOf("Применить к ") !== -1 && s.indexOf("сегм.") !== -1),
      "совет исполняется одним нажатием — по строкам, число названо");
check(t3.some(s => s.indexOf("запись глоссария остаётся") !== -1),
      "и сказано, что запись глоссария при этом НЕ трогается: спор про неё остаётся человеку");
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
try { treeTk = render(React.createElement(TurnkeySummary, { expert: true, summary:TK, store, toast })); }
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
// Срез «ревизия ручается»: старый сервер поля не шлёт — строки нет; новый
// шлёт — строка названа. Снятое молча неотличимо от потерянного.
check(!tTk.some(s => s.indexOf("Ревизия ручается") !== -1),
      "без поля reviewVouched строки нет");
const TV = JSON.parse(JSON.stringify(TK));
TV.turnkey.reviewVouched = [1];
let treeTv = null;
try { treeTv = render(React.createElement(TurnkeySummary, { expert: true, summary:TV, store, toast })); }
catch (e) { console.log("      " + e.message); }
check(treeTv && texts(treeTv).some(s => s.indexOf("Ревизия ручается") !== -1),
      "с полем — строка среза названа");

// ─────────── 3d. «Нужен человек» — группы по действию ───────────
// Прежде карточка рисовала все четырнадцать строк всегда, половина — нули.
console.log("\n=== 3d. Группы по действию: нули спрятаны, топ-3, свёрнутый хвост ===");
const GR = JSON.parse(JSON.stringify(BASE));
GR.total = 20;
GR.human.reviewFlagged = [1, 2, 3]; GR.human.weak = [4, 5]; GR.human.reverted = [6];
GR.human.staleFindings = [7]; GR.human.sourceSuspect = [8, 9];
GR.human.confirmWithdrawn = [6];                 // тот же сегмент, что и в reverted
GR.human.termcheckDisputes = [{ src: "a", tgt: "b", suggests: [], segments: [10] },
                              { src: "c", tgt: "d", suggests: [], segments: [10] }];
GR.human.termcheckDisputesSegments = [10];
GR.human.termContextWrong = [{ src: "C", tgt: "D", use: "e", segments: [10] }];  // та же запись c→d
GR.turnkey = { ready: [11], machine: [12], human: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], params: {} };
const gs = analysisHumanGroups(GR);
check(gs.map(g => g.key).join() === "fix,source,records", "три группы в порядке действия");
check(gs[0].n === 7 && gs[1].n === 2 && gs[2].n === 2,
      "счёт: 7 сегментов без повтора, 2 оригинала, 2 записи (спор+арбитр об одной записи — один раз): "
      + gs.map(g => g.n).join("/"));
check(gs[0].rows.map(r => r.key).join() === "confirmWithdrawn,reviewFlagged,weak,reverted,staleFindings",
      "громкая строка первой, дальше по убыванию, нули выброшены");
const GR2 = JSON.parse(JSON.stringify(GR));
GR2.turnkey.human = [1, 2, 8, 9, 10];
check(analysisHumanGroups(GR2)[0].n === 2 && analysisHumanGroups(GR2)[1].n === 2,
      "сегменты берутся только из корзины «нужен человек»: «из них» — подмножество");
let treeG = null;
try { treeG = render(React.createElement(WorkSummary, { summary: GR, store, toast })); }
catch (e) { console.log("      " + e.message); }
const tG = treeG ? texts(treeG) : [];
check(tG.some(s => s === "Править перевод") && tG.some(s => s === "Править оригинал")
      && tG.some(s => s === "Решить про записи глоссария"), "заголовки групп на экране");
check(!tG.some(s => s.indexOf("проверки нашли критичное") !== -1), "нулевая строка не рисуется");
check(tG.some(s => s.indexOf("Машина сняла ваше подтверждение") !== -1)
      && !tG.some(s => s.indexOf("Забракованное слово") !== -1) && tG.some(s => s.indexOf("Ещё строк") !== -1),
      "громкая строка видна, а хвост группы спрятан под «Ещё строк»");
let treeG2 = null;
try { treeG2 = render(React.createElement(TurnkeySummary, { expert: true, summary:GR, store, toast })); }
catch (e) { console.log("      " + e.message); }
const tG2 = treeG2 ? texts(treeG2) : [];
check(tG2.some(s => s.indexOf("из них: править перевод") !== -1)
      && tG2.some(s => s.indexOf("из них: править оригинал") !== -1),
      "три числа групп — в карточке «под ключ»");
check(tG2.some(s => s.indexOf("ждут правки оригинала") !== -1),
      "подпись под готовностью называет повреждённый оригинал");

// ─────────── 3e. «Проверка» человеку: полоса, одна кнопка, вопросы ───────────
// Человек видит два блока: сколько готово (с ОДНОЙ кнопкой) и вопросы с командой
// в самой строке. Корзины карточками и срезы «из них» — эксперту.
console.log("\n=== 3e. Простой вид: полоса готовности и вопросы с командами ===");
let treeS = null;
try { treeS = render(React.createElement(TurnkeySummary, { summary: GR, store, toast })); }
catch (e) { console.log("      " + e.message); }
const tS = treeS ? texts(treeS) : [];
check(tS.some(s => s.indexOf("Доделать сама · 1") === 0),
      "одна главная кнопка «Доделать сама» с числом строк: " + tS.filter(s => s.indexOf("Доделать") !== -1).join("|"));
check(!tS.some(s => s === "Готово к сдаче") && !tS.some(s => s.indexOf("из них:") !== -1),
      "корзины карточками и срезы «из них» человеку не показаны");
check(tS.some(s => s.indexOf("1 из 20 строк") !== -1), "легенда называет готовность числом строк");

// Машине делать нечего, но есть заверенное с находками: кнопка обязана
// открываться — галочка «чинить и заверенные» живёт в её панели.
const CF = JSON.parse(JSON.stringify(GR));
CF.turnkey.machine = []; CF.human.confirmedFindings = [9];
let treeCF = null;
try { treeCF = render(React.createElement(TurnkeySummary, { summary: CF, store, toast })); }
catch (e) { console.log("      " + e.message); }
let cfBtn = null;
const cfSeen = [];
(function findBtn(n) {
  if (!n || typeof n !== "object") return;
  if (Array.isArray(n)) { n.forEach(findBtn); return; }
  if (n.type === "button") cfSeen.push(texts(n).join("/") + ":" + !!(n.props || {}).disabled);
  if (n.type === "button" && texts(n).some(s => s.indexOf("Доделать сама") === 0)) cfBtn = n;
  (n.children || []).forEach(findBtn);
})(treeCF);
check(cfBtn && !cfBtn.props.disabled,
      "машинная корзина пуста, но заверенное с находками есть — «Доделать сама» открыта"
      + (cfBtn && !cfBtn.props.disabled ? "" : " · кнопки: " + JSON.stringify(cfSeen)));

const QS = JSON.parse(JSON.stringify(GR));
QS.human.revertedByScore = [6]; QS.human.reverted = [6];
QS.human.confirmedFindings = [9];
QS.human.termsTotal = 3; QS.proposed = { terms: 2 };
let treeQ = null;
try { treeQ = render(React.createElement(CheckQuestions, { summary: QS, store, toast })); }
catch (e) { console.log("      " + e.message); }
const tQ = treeQ ? texts(treeQ) : [];
const at = (sub) => tQ.findIndex(s => s.indexOf(sub) !== -1);
check(at("Вопросы к вам") !== -1, "список вопросов назван");
/* Снятая отметка «проверено» — извещение, а не вопрос: полосой НАД таблицей,
   то есть раньше её шапки. Проверяем место, а не формулировку: заголовки
   первого экрана переписываются, инвариант — порядок. */
check(at("Я поправила строки, которые вы отметили как проверенные") !== -1
      && at("Я поправила строки, которые вы отметили как проверенные") < at("Что не так"),
      "снятая отметка «проверено» стоит НАД таблицей вопросов");
check(at("Что не так") !== -1 && at("Где") !== -1 && at("Ваш ответ") !== -1 && at("Сколько изменится") !== -1,
      "таблица вопросов выровнена по четырём названным колонкам");
/* Раскладка по ФАКТУ команды: у «Готовый текст ждёт вашего „да“» есть
   «Принять все» — вопрос; у «Перевела обратно — вышло другое» команды нет,
   значит это стопка на просмотр, а не вопрос с пустой колонкой ответа. */
check(at("Просмотреть глазами") !== -1 && at("Перевела обратно — вышло другое") > at("Просмотреть глазами"),
      "строки без решения ушли в «Просмотреть глазами», а не висят вопросами");
/* Исчерпаемость: ни одна строка `analysisHumanGroups` не пропала с экрана.
   Потерянная строка — это сегменты, которых человек не видит вовсе,
   а картина выглядит благополучнее, чем есть. */
const grpKeys = analysisHumanGroups(QS).reduce((a, g) => a.concat(g.rows.map(r => r.key)), []);
const askTitles = {
  reviewConfirmed: "Я перечитала эти строки и предлагаю другой перевод",
  reviewFlagged: "Вижу проблему, но починить не смогла",
  weak: "Перевела обратно — вышло другое",
  reverted: "Пробовала исправить, вышло хуже — оставила как было",
  revertedByScore: "Готовый текст ждёт вашего «да»",
  staleFindings: "Слово, которое я забраковала, осталось в тексте",
  confirmWithdrawn: "Я поправила строки, которые вы отметили как проверенные",
  glossaryConfirmed: "Вы отметили строки, а перевод спорит со словарём",
  confirmedFindings: "Вы отметили строки как проверенные, а я нашла ошибку",
  qaCritical: "Вы отметили строки, а в них критичное замечание",
  sourceSuspect: "Похоже, в книге испорчен сам текст",
  disputes: "Проверка спорит со словарём",
  ctxWrong: "Арбитр: запись словаря не подходит здесь",
  terms: "терминов ждут ответа",
};
const lost = grpKeys.filter(k => askTitles[k] && at(askTitles[k]) === -1);
check(lost.length === 0, "все строки разбора попали на экран" + (lost.length ? " · потеряно: " + lost.join(", ") : ""));
check(at("Принять все") !== -1, "«Принять все» — кнопкой в самом вопросе, а не в «Подробностях»");
check(at("5 терминов ждут ответа") !== -1,
      "термины: ждущие решения + готовые к одобрению = очередь «Словарей» для человека");
check(at("с галочкой «чинить и заверенные»") !== -1,
      "заверенные с находками ведут к двери, которую человек видит, а не к строке «Ремонт»");
check(at("Арбитр: запись словаря не подходит здесь") !== -1 && at("Проверка спорит со словарём") !== -1
      && at("Понизить запись") !== -1,
      "записи словаря — по вопросу на запись, с командой понижения");
check(at("Показать все") === -1, "десяток вопросов влезает без свёртки");
/* Хвост длиннее ASK_TOP свёрнут, но число названо. Считаются ВОПРОСЫ
   (строки таблицы), а не всё подряд: стопка на просмотр потолком не режется —
   там строк единицы, и прятать их не за чем. */
const QS2 = JSON.parse(JSON.stringify(QS));
for (let i = 0; i < 12; i++)
  QS2.human.termcheckDisputes.push({ src: "x" + i, tgt: "y" + i, suggests: ["z"], segments: [10 + i] });
let treeQ2 = null;
try { treeQ2 = render(React.createElement(CheckQuestions, { summary: QS2, store, toast })); }
catch (e) { console.log("      " + e.message); }
check(treeQ2 && texts(treeQ2).some(s => s.indexOf("Показать все · ") !== -1),
      "хвост длиннее потолка свёрнут, но число названо");
const EMPTY = JSON.parse(JSON.stringify(BASE));
EMPTY.turnkey = { ready: [1, 2, 3], machine: [], human: [], params: {} };
let treeE = null;
try { treeE = render(React.createElement(CheckQuestions, { summary: EMPTY, store, toast })); }
catch (e) { console.log("      " + e.message); }
check(treeE && texts(treeE).some(s => s === "Вопросов к вам нет."), "без вопросов — так и сказано");

console.log("\n=== 3c. WorkSummary: критика Medical QA на подтверждённом видна ===");
const QA = JSON.parse(JSON.stringify(BASE));
QA.human.qaCritical = [7, 9];
let treeQa = null, okQa = true;
try { treeQa = render(React.createElement(WorkSummary, { summary: QA, store, toast })); }
catch (e) { okQa = false; console.log("      " + e.message); }
check(okQa, "рендер прошёл");
check(okQa && texts(treeQa).some(s => s.indexOf("проверки нашли критичное") !== -1),
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
// Подтянутое с сервера кладётся ЛОКАЛЬНО (mergeServerSegments), а не через
// updateSegment: тот шлёт текст обратно на сервер. Вызов updateSegment здесь —
// регрессия, и заглушка его засчитывает отдельно.
const wroteBack = [];
const store4 = {
  mergeServerSegments: (pid, segs) => (segs || []).forEach(sg => patched.push([pid, sg.id, sg.target])),
  updateSegment: (pid, sid, sg) => wroteBack.push([pid, sid]),
};
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
    check(wroteBack.length === 0,
          "подтянутое не пишется обратно на сервер (updateSegment): " + JSON.stringify(wroteBack));
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
  /* Устройство прогона (модели, цена по шагам) видит СИСТЕМНЫЙ
     АДМИНИСТРАТОР — инвариант 24. Стаб без `can` говорил бы о панели
     неправду: это вид администратора, а не всякого вошедшего. */
  const storeRun = { activeProject: { id: 1, segments: [{ id: 1, source: "аа", target: "bb" },
                                                        { id: 2, source: "вв", target: "" }] },
                     can: { owner: true, super: true, role: "owner" }, expert: true,
                     go() {}, setSegmentFilter() {}, updateSegment() {}, mergeServerSegments() {} };
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

  // ─────────── 4d. Два рубежа: устройство прогона и смета ───────────
  // Инвариант 24. Редактор этот рубеж держал с самого начала, а панель
  // запуска на «Анализе» — нет: её единственным условием был тенантный
  // `simple` (инвариант 22), то есть переводчик видел здесь ровно ту таблицу
  // моделей, которую редактор ему не показывает. Состав (шаг и сколько
  // сегментов) при этом остаётся всем: это обещание работы.
  console.log("\n=== 4d. Устройство — админу, смета — плательщику ===");
  const asRole = (can) => {
    hooks = []; hookIdx = 0; effects.length = 0;
    const st = Object.assign({}, storeRun, { can });
    return texts(React.createElement(RunPanel, { summary: TKP, store: st, toast,
                                                 plan: planSame, cat: catSrv,
                                                 mods: { judge_model: "m1" },
                                                 setMod: (k, v) => {},
                                                 onClose() {}, onStarted() {} }));
  };
  const tOwn = asRole({ owner: true, super: false, role: "owner" });
  check(tOwn.some(s => s.indexOf("Перевод") !== -1) && tOwn.some(s => s.indexOf("2 сегм.") !== -1),
        "владелец: состав по шагам на месте");
  check(!tOwn.some(s => s === "по умолчанию"), "владелец: выбора моделей нет");
  check(!tOwn.some(s => s.indexOf("Модель 1") !== -1),
        "владелец: действующая модель не названа");
  check(!tOwn.some(s => s.indexOf("Back-check той же моделью") !== -1),
        "владелец: подсказка о конфликте моделей не тревожит без двери");
  check(tOwn.some(s => s.indexOf("нижняя граница") !== -1),
        "владелец: про смету сказано — он платит");
  const tTr = asRole({ owner: false, super: false, role: "translator" });
  check(tTr.some(s => s.indexOf("Запустить") !== -1), "переводчик: кнопка на месте");
  check(!tTr.some(s => s === "по умолчанию"), "переводчик: выбора моделей нет");
  check(!tTr.some(s => s.indexOf("нижняя граница") !== -1),
        "переводчик: сметы нет — деньги не его дело");

  // ─────────── 5. TabAnalysis: старый сервер без turnkey не роняет экран ───────────
  console.log("\n=== 5. TabAnalysis переживает ответ сервера без turnkey ===");
  global.API.analysis = async () => BASE;          // старый ответ, корзин нет
  global.API.runPlan = async () => ({ steps: [], ids: [], total: 0 });
  global.API.listJobs = async () => ({ active: [], jobs: [] });
  const storeTab = { activeProject: { id: 1, segments: [] }, glossary: [],
                     go() {}, setSegmentFilter() {}, updateSegment() {}, mergeServerSegments() {},
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

  // ─────────── 5b. Новый сервер: человеку вопросы, эксперту — подробности ───────────
  console.log("\n=== 5b. TabAnalysis: устройство прогона — только эксперту ===");
  const NEW = JSON.parse(JSON.stringify(QS));
  const tabTree = async (st) => {
    hooks = []; hookIdx = 0; effects.length = 0;
    React.createElement(TabAnalysis, { store: st, toast });
    effects.slice().forEach(fn => fn());
    await new Promise(r => setImmediate(r));
    hookIdx = 0; effects.length = 0;
    return React.createElement(TabAnalysis, { store: st, toast });
  };
  global.API.analysis = async () => NEW;
  global.API.coverage = async () => ({ ok: true, src: "RU", tgt: "EN", works: [{ key: "n", label: "числа" }],
                                        silent: [], model: [] });
  let tHum = [], tExp = [], ok5b = true;
  try {
    tHum = texts(await tabTree(Object.assign({}, storeTab, { can: { owner: true } })));
    tExp = texts(await tabTree(Object.assign({}, storeTab, { can: { super: true }, expert: true, expertView: true })));
  } catch (e) { ok5b = false; console.log("      " + e.message); }
  check(ok5b, "рендер человеку и эксперту прошёл");
  check(tHum.some(s => s === "Проверка") && tHum.some(s => s === "Вопросы к вам"),
        "человеку — «Проверка» и вопросы");
  check(!tHum.some(s => s.indexOf("Подробности и ручные команды") !== -1)
        && !tHum.some(s => s.indexOf("Проверено начисто") !== -1),
        "а подробностей и итога из двенадцати строк у него нет");
  check(!tHum.some(s => s.indexOf("бесплатных проверок") !== -1),
        "покрытие пары молчит, когда молчащих проверок нет");
  check(tHum.some(s => s.indexOf("Настройки книги") !== -1), "настройки книги (стиль, терм-лист) доступны и не эксперту");
  check(tExp.some(s => s.indexOf("Подробности и ручные команды") !== -1),
        "эксперту дверь к подробностям есть");

  // ─────────── 6. Смена проекта: чужое не показывается и поздним ответом не ложится ───────────
  /* Экран «Проверка» при смене проекта не пересоздаётся. Прежде карточки
     держали ответ прошлого проекта: до прихода нового стояли чужая пара
     языков и чужой итог, а запоздавший ответ по старому проекту ложился
     поверх свежего. Эффекты здесь запускаются руками, и cleanup заглушка
     не зовёт — ровно худший случай: защищает только номер проекта. */
  console.log("\n=== 6. Смена проекта на «Проверке» ===");
  let releaseOld = null;
  global.API.coverage = (pid) => pid === 1
    ? new Promise(r => { releaseOld = () => r({ ok: true, src: "RU", tgt: "EN", works: [], silent: [{ key: "x", label: "x" }], model: [] }); })
    : Promise.resolve({ ok: true, src: "RU", tgt: "UZ", works: [], silent: [{ key: "y", label: "y" }], model: [] });
  const covTree = (pid) => { hookIdx = 0; return React.createElement(CoverageCard, { project: { id: pid } }); };
  hooks = []; effects.length = 0;
  covTree(1);
  effects.slice().forEach(fn => fn());          // запрос по проекту 1 ушёл и висит
  effects.length = 0;
  covTree(2);                                    // человек переключил проект
  effects.slice().forEach(fn => fn());          // запрос по проекту 2 — быстрый
  await new Promise(r => setImmediate(r));
  if (releaseOld) releaseOld();                  // ответ по проекту 1 приходит ПОЗЖЕ
  await new Promise(r => setImmediate(r));
  const tCov = texts(covTree(2)).join(" | ");
  check(tCov.indexOf("RU → UZ") !== -1 && tCov.indexOf("RU → EN") === -1,
        "поздний ответ прошлого проекта не лёг поверх нынешнего (" + tCov.slice(0, 60) + ")");
  // Сброс без ожидания: у проекта 3 ответа ещё нет — чужая пара не стоит ни мгновения.
  const tCov3 = texts(covTree(3)).join(" | ");
  check(tCov3.indexOf("RU → UZ") === -1, "у нового проекта до ответа карточки нет, а не чужая пара");

  global.API.analysis = async (pid) => (pid === 1 ? NEW : null);
  const stA = Object.assign({}, storeTab, { can: { owner: true }, activeProject: { id: 1, segments: [] } });
  hooks = []; hookIdx = 0; effects.length = 0;
  React.createElement(TabAnalysis, { store: stA, toast });
  effects.slice().forEach(fn => fn());
  await new Promise(r => setImmediate(r));
  hookIdx = 0; effects.length = 0;
  const tA1 = texts(React.createElement(TabAnalysis, { store: stA, toast }));
  check(tA1.some(s => s === "Вопросы к вам"), "итог проекта 1 показан");
  stA.activeProject = { id: 2, segments: [] };
  hookIdx = 0; effects.length = 0;
  const tA2 = texts(React.createElement(TabAnalysis, { store: stA, toast }));
  check(!tA2.some(s => s === "Вопросы к вам") && tA2.some(s => s.indexOf("Считаем итог") !== -1),
        "после смены проекта чужой итог сброшен сразу — «Считаем итог…», а не вопросы проекта 1");

  // ─────────── 7. Переход в редактор несёт слова и корзину ───────────
  /* setSegmentFilter(ids, {terms, label, bucket}): слова спорной записи
     (термин и варианты перевода) редактор подсвечивает, корзина зажигает
     свою кнопку-фильтр. Прежде уезжал голый список номеров. */
  console.log("\n=== 7. Переход в редактор: слова и корзина ===");
  const sent = [];
  const storeRec = Object.assign({}, store, { setSegmentFilter: (ids, meta) => sent.push([ids, meta || null]) });
  const DQ = JSON.parse(JSON.stringify(BASE));
  DQ.human.termcheckDisputes = [{ src: "кашель", tgt: "cough", suggests: ["tussis"], segments: [5] }];
  DQ.human.termcheckDisputesSegments = [5];
  DQ.turnkey = { ready: [], machine: [], human: [5], params: {} };
  const qTree = render(React.createElement(CheckQuestions, { summary: DQ, store: storeRec, toast }));
  const opens = [];
  (function findOpen(n) {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(findOpen);
    if (n.type === "button" && texts(n).some(s => s === "Открыть")) opens.push(n);
    (n.children || []).forEach(findOpen);
  })(qTree);
  opens.forEach(b => b.props.onClick());
  const disp = sent.find(c => c[0].join() === "5");
  check(!!disp && disp[1] && (disp[1].terms || []).join("|") === "кашель|cough|tussis",
        "«Открыть» у спора со словарём несёт термин и все варианты перевода: "
        + JSON.stringify(disp && disp[1]));
  sent.length = 0;
  const wTree = render(React.createElement(WorkSummary, { summary: DQ, store: storeRec, toast }));
  const gOpen = [];
  (function findOpen(n) {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(findOpen);
    if (n.type === "button" && texts(n).some(s => s === "Открыть")) gOpen.push(n);
    (n.children || []).forEach(findOpen);
  })(wTree);
  gOpen.forEach(b => b.props.onClick());
  check(sent.some(c => c[1] && (c[1].terms || []).indexOf("tussis") !== -1),
        "и «Открыть» у группы «Решить про записи глоссария» — тоже");
  sent.length = 0;
  const bc = render(React.createElement(BucketCard, { store: storeRec, toast, ids: [1, 2], tone: "hum",
                                                     label: "Нужно ваше решение", hint: "" }));
  bc.props.onClick();
  check(sent.length === 1 && sent[0][1] && sent[0][1].bucket === "human",
        "карточка корзины на «Проверке» передаёт корзину — в редакторе зажжётся её кнопка");

  // ─────────── 5c. Правила документа ───────────
  console.log("\n=== 5c. GuideCard: правила документа ===");
  const guideTree = async (st, answer) => {
    hooks = []; hookIdx = 0; effects.length = 0;
    global.API.guide = async () => answer;
    React.createElement(GuideCard, { project: { id: 1 }, store: st, toast });
    effects.slice().forEach(fn => fn());
    await new Promise(r => setImmediate(r));
    hookIdx = 0; effects.length = 0;
    return React.createElement(GuideCard, { project: { id: 1 }, store: st, toast });
  };
  const G0 = { ok: true, built: false, rules: [], active: 0, ready: 5, min: 20, minPairs: 3, tgt: "UZ", orgLang: [] };
  const G1 = { ok: true, built: true, builtBy: "auto", sample: 25, rules: [
      { id: 1, text: "Address the reader formally (siz).", kind: "lang", on: true, by: "model" },
      { id: 2, text: "Use «guillemets».", kind: "doc", on: false, by: "human" }],
    active: 1, ready: 25, min: 20, minPairs: 3, tgt: "UZ", orgLang: ["Keep oʻ with U+02BB."] };
  // Старый сервер без /guide: карточка молчит, а не роняет экран.
  const G_OLD = null;
  let g0 = [], g1own = [], g1tr = [], okG = true, oldTree = "x";
  try {
    g0 = texts(await guideTree({ can: {} }, G0));
    g1own = texts(await guideTree({ can: { owner: true } }, G1));
    g1tr = texts(await guideTree({ can: {} }, G1));
    oldTree = await guideTree({ can: {} }, G_OLD);
  } catch (e) { okG = false; console.log("      " + e.message); }
  check(okG, "рендер карточки прошёл");
  check(g0.some(s => s.indexOf("Соберутся сами") !== -1) && g0.some(s => s === "Собрать сейчас"),
        "до сбора: сказано, когда соберутся сами, и есть кнопка");
  check(g1own.some(s => s.indexOf("Собраны сами по первым") !== -1) && g1own.some(s => s === "Пересобрать"),
        "после сбора: откуда правила и кнопка пересборки");
  check(g1own.some(s => s === "Во все книги") && !g1tr.some(s => s === "Во все книги"),
        "перенос правила языка в организацию — только владельцу");
  check(g1own.some(s => s.indexOf("Правила языка организации") !== -1) && g1own.some(s => s === "Keep oʻ with U+02BB."),
        "правила языка организации видны");
  check(oldTree === null, "старый сервер без правил — карточки нет, экран цел");

  console.log();
  if (fail.length) {
    console.log("ПРОВАЛЕНО: " + fail.length);
    fail.forEach(f => console.log("  - " + f));
    process.exit(1);
  }
  console.log("ВСЁ ПРОШЛО");
})();

