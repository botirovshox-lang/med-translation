/* Экран «Словарь книги» (tab_glossary_tm.jsx): рендер без браузера.
 *
 * До этого файла экран не рендерил НИ ОДИН тест: сборки нет, .jsx
 * выполняются в браузере, и сломанный компонент виден только там — белым
 * экраном. Тот же приём, что в test_profile_render.js: заглушка React
 * с хуками, файлы выполняются как есть.
 *
 * Проверяется то, что легко потерять молча:
 *   1. TabGlossary собирается: три служебные панели стоят в сетке
 *      `.kb-decks`, ниже — очередь и таблица;
 *   2. карточки очереди лежат в сетке `.kb-cands`, а «Показать ещё»
 *      и пустое сообщение — СНАРУЖИ неё: попав внутрь, они стали бы
 *      ячейками сетки шириной в карточку;
 *   3. имена верхнего уровня файла не совпадают с ui.jsx (одна глобальная
 *      область — поздний файл молча затирает ранний).
 *
 * Запуск: node tests/test_knowledge_render.js
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
  Component: class Component { constructor(props) { this.props = props; } },
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
// Эффекты не запускаются, поэтому в сеть экран не ходит; заглушка нужна
// только для проверок `window.API &&` при сборке дерева.
global.API = { safeCall: async (fn) => fn() };

const root = process.argv[2] || "frontend/js";
const uiSrc = fs.readFileSync(path.join(root, "ui.jsx"), "utf8");
const kbSrc = fs.readFileSync(path.join(root, "tab_glossary_tm.jsx"), "utf8");
for (const [f, src] of [["i18n.js", fs.readFileSync(path.join(root, "i18n.js"), "utf8")], ["ui.jsx", uiSrc], ["tab_glossary_tm.jsx", kbSrc]]) {
  (0, eval)(src + "\n//# sourceURL=" + f);
}

const toast = { info() {}, warning() {}, error() {}, success() {} };
const store = {
  glossary: [{ src: "плевра", tgt: "pleura", cat: "Anatomy", freq: 3, conf: "high", tier: "verified", dict: "d1" }],
  tm: [], activeProject: { id: 1, src: "RU", tgt: "EN", domain: "medical" },
  /* Словари организации и папка открытого файла: колонка «Словарь», фильтр
     и поле в окне термина рисуются только при них. */
  dicts: [{ id: "d1", title: "Словарь учебника", count: 1 }, { id: "old", title: "Старый словарь", count: 1307 }],
  activeFolder: { id: 1, title: "Учебник", files: [1], dicts: ["d1", "old"] },
  saveTerm() {}, deleteTerm() {}, deleteTM() {}, go() {}, openProject() {}, setSegmentFilter() {},
};

function find(node, pred, out) {
  out = out || [];
  if (!node || typeof node !== "object") return out;
  if (Array.isArray(node)) { node.forEach(n => find(n, pred, out)); return out; }
  if (pred(node)) out.push(node);
  (node.children || []).forEach(n => find(n, pred, out));
  return out;
}
function texts(node, out) {
  out = out || [];
  if (node === null || node === undefined) return out;
  if (typeof node === "string" || typeof node === "number") { out.push(String(node)); return out; }
  if (Array.isArray(node)) { node.forEach(n => texts(n, out)); return out; }
  (node.children || []).forEach(n => texts(n, out));
  return out;
}
const cls = (n) => String((n.props || {}).className || "");

/* 1. Экран собирается, панели — в сетке */
console.log("[1] TabGlossary собирается");
hooks = []; hookIdx = 0;
let tree = null, err = null;
try { tree = TabGlossary({ store, toast }); } catch (e) { err = e; }
check(!err, "рендер без исключения" + (err ? ": " + err.message : ""));
const decks = find(tree, n => cls(n) === "kb-decks");
check(decks.length === 1, "сетка kb-decks ровно одна");
const deckCards = (decks[0] ? decks[0].children : []).filter(n => cls(n).split(" ").includes("card"));
check(deckCards.length === 3, "в сетке три служебные панели, а не " + deckCards.length);
const t = texts(tree).join(" | ");
check(t.includes("Автоодобрение однозначных") && t.includes("Сверка смысла записей") && t.includes("Вынести массовый импорт"),
  "все три панели названы");
check(find(tree, n => n.type === "table").length === 1, "таблица словаря на месте");
check(t.includes("плевра") && t.includes("pleura"), "запись словаря видна");
check(!deckCards.some(n => n.props.style && n.props.style.marginBottom),
  "у панелей нет своего marginBottom (расстояние даёт gap сетки)");

/* 2. Очередь: карточки в сетке, «Показать ещё» и пустое сообщение — снаружи */
console.log("\n[2] карточки очереди в сетке kb-cands");
const cand = (id, why) => ({ id, kind: "extract", src: "каверна " + id, tgt: "cavity " + id, why,
  hits: 2, segments: ["1:2", "1:3"], sampleSrc: "…каверна…", sampleTgt: "…cavity…", lang: "RU→EN" });
hooks = []; hookIdx = 0;
hooks[0] = [cand(1, "wait"), cand(2, "wait")];   // items
hooks[2] = false;                                 // loading — до ответа очередь не рисуется
hooks[6] = 5;                                     // total > items.length → «Показать ещё»
let q = null; err = null;
try { q = TermQueue({ store, toast, version: 0 }); } catch (e) { err = e; }
check(!err, "TermQueue рендерится с двумя кандидатами" + (err ? ": " + err.message : ""));
const grids = find(q, n => cls(n) === "kb-cands");
check(grids.length === 1, "сетка kb-cands ровно одна");
const inGrid = grids[0] ? grids[0].children : [];
check(inGrid.length === 2 && inGrid.every(n => cls(n).split(" ").includes("card")),
  "внутри сетки ровно две карточки");
const gridText = texts(grids[0]).join(" | ");
// В режиме просмотра и оригинал, и перевод видны текстом (см. 2a).
check(gridText.includes("каверна 1") && gridText.includes("каверна 2"), "карточки — те самые кандидаты");
const qt = texts(q).join(" | ");
check(qt.includes("Показать ещё"), "«Показать ещё» есть при total > items");
check(!gridText.includes("Показать ещё"), "«Показать ещё» стоит СНАРУЖИ сетки");

/* 2a. Карточка с готовым переводом: две кнопки, поле правки скрыто */
console.log("\n[2a] карточка с переводом отвечается двумя кнопками");
check(gridText.includes("Верно") && gridText.includes("Не то") && !gridText.includes("В глоссарий"),
  "в режиме просмотра — «Верно» и «Не то», без «В глоссарий»");
check(gridText.includes("cavity 1"), "перевод виден текстом, а не в поле");
const inputs = (n) => find(n, x => x.type === "input" && cls(x) === "input");
check(inputs(grids[0]).length === 0, "поля ввода в режиме просмотра нет");
// «Не то» переводит карточку в режим правки: поле и прежние кнопки.
// editing — ПОСЛЕДНИЙ хук TermQueue (индекс 12): хук, добавленный раньше него, сдвинул бы этот индекс.
hooks[12] = { 1: true };
hookIdx = 0;
const q2 = TermQueue({ store, toast, version: 0 });
const cards2 = find(q2, n => cls(n) === "kb-cands")[0].children;
const t2 = texts(cards2[0]).join(" | ");
check(t2.includes("В глоссарий") && t2.includes("Отклонить") && !t2.includes("Верно"),
  "после «Не то» — «В глоссарий» / «Отклонить» и поле ввода");
check(inputs(cards2[0]).length === 1, "поле ввода открыто");
check(texts(cards2[1]).join(" | ").includes("Верно"), "соседняя карточка осталась в режиме просмотра");
hooks[12] = {};

hooks = []; hookIdx = 0;
// Ноль показанных при total > 0: так выглядит страница после отклонения
// всех загруженных (при total = 0 очередь не рисуется вовсе).
hooks[0] = []; hooks[2] = false; hooks[6] = 3;
const empty = TermQueue({ store, toast, version: 0 });
const emptyGrid = find(empty, n => cls(n) === "kb-cands");
check(emptyGrid.length === 1 && emptyGrid[0].children.length === 0, "пустая очередь — пустая сетка");
check(texts(empty).join(" | ").includes("Нерешённых кандидатов нет"), "пустое сообщение показано");
check(!texts(emptyGrid[0]).join("").includes("Нерешённых"), "и стоит снаружи сетки");

/* 3. Имена верхнего уровня не совпадают с ui.jsx */
console.log("\n[3] имена верхнего уровня");
const names = (src) => new Set((src.match(/^(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)/gm) || [])
  .map(s => s.replace(/^(?:function|const|let|var)\s+/, "")));
const uiNames = names(uiSrc);
const clash = [...names(kbSrc)].filter(n => uiNames.has(n));
check(clash.length === 0, "tab_glossary_tm.jsx не затирает имена из ui.jsx" + (clash.length ? ": " + clash.join(", ") : ""));

/* 4. CSS сеток на месте */
console.log("\n[4] стили");
const css = fs.readFileSync(path.join(path.dirname(root), "css", "styles.css"), "utf8");
check(/\.kb-decks \{[^}]*display: grid/.test(css) && /\.kb-decks \{[^}]*align-items: start/.test(css),
  "kb-decks — сетка с align-items: start (иначе панели растягиваются по строке)");
check(/\.kb-cands \{[^}]*auto-fill/.test(css), "kb-cands — сетка auto-fill");
check(/@media \(max-width: 1520px\) \{ \.kb-decks \{ grid-template-columns: repeat\(2/.test(css)
   && /@media \(max-width: 1180px\) \{ \.kb-decks \{ grid-template-columns: minmax\(0, 1fr\)/.test(css),
  "пороги kb-decks те же, что у .run-decks: 1520 → две колонки, 1180 → одна");

console.log();
if (fail.length) {
  console.log("ПРОВАЛЕНО: " + fail.length);
  fail.forEach(f => console.log("  - " + f));
  process.exit(1);
}
console.log("ВСЁ ПРОШЛО");
