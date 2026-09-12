/* Экран «Проекты» (tab_import.jsx) — рендер без браузера.
 *
 * Зачем отдельный набор: экран собирается в браузере, и ошибка в нём видна
 * только белым экраном на первом же входе — это первое, что открывает
 * человек. Проверяется то, что легко потерять молча:
 *   1. список проектов: каждая папка — карточка с названием, парой языков,
 *      числом файлов и словарями; файл без папки (virtual) выглядит проектом;
 *   2. открытая папка: файлы карточками (каждый открывает перевод), блок
 *      «Добавить файл» и блок «Словари проекта» с очерёдностью
 *      («сюда пишутся новые слова» — у первого);
 *   3. папка без списка словарей честно говорит «подключены все»;
 *   4. окно нового проекта предлагает свой словарь и мультивыбор существующих;
 *   5. имена верхнего уровня не затирают ui.jsx (одна глобальная область).
 *
 * Запуск: node tests/test_projects_render.js
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
    if (typeof type === "function") return type(Object.assign({}, props, kids.length ? { children: kids } : {}));
    return { type, props: props || {}, children: kids };
  },
  useState(init) {
    const i = hookIdx++;
    if (!(i in hooks)) hooks[i] = typeof init === "function" ? init() : init;
    return [hooks[i], (v) => { hooks[i] = typeof v === "function" ? v(hooks[i]) : v; }];
  },
  useEffect() {},
  useRef(v) { return { current: v === undefined ? null : v }; },
  useMemo(f) { return f(); },
  useCallback(f) { return f; },
  Fragment: "Fragment",
  createContext(v) { return { _v: v, Provider: "Provider", Consumer: "Consumer" }; },
  useContext() { return { info() {}, warning() {}, error() {}, success() {} }; },
};
const { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } = React;
global.React = React;
global.useState = useState; global.useEffect = useEffect;
global.useRef = useRef; global.useMemo = useMemo; global.useCallback = useCallback;
global.createContext = createContext; global.useContext = useContext;
const mem = { memory: {}, getItem(k) { return this.memory[k] || null; }, setItem(k, v) { this.memory[k] = String(v); }, removeItem(k) { delete this.memory[k]; } };
global.localStorage = mem; global.sessionStorage = mem;
global.window = global;
global.document = { addEventListener() {}, removeEventListener() {}, querySelector() { return null; } };
global.API = { safeCall: async (fn) => fn(), models: async () => null, quotes: async () => ({ quotes: [] }) };
global.prompt = () => null;

const root = process.argv[2] || "frontend/js";
const uiSrc = fs.readFileSync(path.join(root, "ui.jsx"), "utf8");
const impSrc = fs.readFileSync(path.join(root, "tab_import.jsx"), "utf8");
for (const [f, src] of [["i18n.js", fs.readFileSync(path.join(root, "i18n.js"), "utf8")], ["ui.jsx", uiSrc], ["tab_import.jsx", impSrc]]) {
  (0, eval)(src + "\n//# sourceURL=" + f);
}

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
const toast = { info() {}, warning() {}, error() {}, success() {} };

const seg = (status) => ({ id: 1, source: "a", target: "b", status, comments: [] });
const projects = [
  { id: 101, title: "Учебник", src: "RU", tgt: "EN", domain: "medical", segments: [seg("confirmed"), seg("new")] },
  { id: 103, title: "Приложение 1", src: "RU", tgt: "EN", domain: "legal", folder: 102, segments: [seg("confirmed")], sourceDocx: { file: "a.docx" } },
  { id: 104, title: "Приложение 2", src: "RU", tgt: "EN", domain: "legal", folder: 102, segments: [] },
];
const folders = [
  { id: 102, title: "Договор поставки", src: "RU", tgt: "EN", domain: "legal", dicts: ["d1", "old"], files: [103, 104] },
  { id: 101, title: "Учебник", src: "RU", tgt: "EN", domain: "medical", files: [101], virtual: true },
];
const dicts = [
  { id: "d1", title: "Словарь договора", count: 3, pairs: { "RU→EN": 3 } },
  { id: "old", title: "Старый словарь", count: 1307, pairs: { "RU→EN": 1307 } },
];
function makeStore(over) {
  return Object.assign({
    projects, folders, dicts, viewFolder: null,
    can: { owner: true }, glossary: [],
    statusCounts: (p) => { const out = { all: p.segments.length, new: 0, translated: 0, qa: 0, confirmed: 0, failed: 0, review: 0 };
      p.segments.forEach(s => { out[s.status] = (out[s.status] || 0) + 1; }); return out; },
    openFolder() {}, setViewFolder() {}, openProject() {}, go() {}, addFolder() {}, patchFolder() {}, removeFolder() {},
    addProject() {}, deleteProject() {}, patchProject() {}, setDicts() {},
  }, over || {});
}

console.log("[1] Список проектов");
{
  hooks = []; hookIdx = 0;
  let tree = null, err = null;
  try { tree = TabImport({ store: makeStore(), toast }); } catch (e) { err = e; }
  check(!err, "рендер без исключения" + (err ? ": " + err.message : ""));
  const cards = find(tree, n => cls(n).split(" ").includes("card-hover"));
  check(cards.length === 2, "две карточки проектов (папка и файл без папки), а не " + cards.length);
  const t = texts(tree).join(" | ");
  check(t.includes("Договор поставки") && t.includes("Учебник"), "названы оба проекта");
  check(t.includes("2 файла") && t.includes("1 файл"), "число файлов у каждого: " + (t.match(/\d+ файл\S*/g) || []).join(", "));
  check(t.includes("Словарь договора") && t.includes("Старый словарь"), "словари папки названы на карточке");
  check(t.includes("все словари"), "у папки без списка словарей сказано «все словари»");
  check(t.includes("Новый проект"), "есть кнопка «Новый проект»");
}

console.log("\n[2] Открытая папка: файлы, добавление, словари");
{
  hooks = []; hookIdx = 0;
  let tree = null, err = null;
  try { tree = TabImport({ store: makeStore({ viewFolder: 102 }), toast }); } catch (e) { err = e; }
  check(!err, "рендер без исключения" + (err ? ": " + err.message : ""));
  const t = texts(tree).join(" | ");
  check(t.includes("Приложение 1") && t.includes("Приложение 2"), "оба файла на месте");
  check((t.match(/Переводить/g) || []).length === 2, "у каждого файла кнопка «Переводить»");
  check(t.includes("вернём в том же виде"), "файл с исходником помечен");
  check(t.includes("Добавить файл") && t.includes("Добавить в проект"), "блок добавления файла есть");
  check(t.includes("Словари проекта"), "блок словарей есть");
  const first = t.indexOf("Словарь договора"), second = t.indexOf("Старый словарь", t.indexOf("Словари проекта"));
  check(first >= 0 && second > first, "порядок словарей — как в папке (первый — словарь договора)");
  check(t.includes("сюда пишутся новые слова"), "первый словарь помечен как место новых слов");
  check(t.includes("Удалить проект"), "владельцу есть удаление проекта");
  check(!t.includes("Пока подключены все словари"), "у папки со списком нет предупреждения «все»");
  check(find(tree, n => n.type === "input" && n.props.type === "file").length === 1, "поле выбора файла одно");
}

console.log("\n[3] Папка без списка словарей — честно «подключены все»");
{
  hooks = []; hookIdx = 0;
  const tree = TabImport({ store: makeStore({ viewFolder: 101 }), toast });
  const t = texts(tree).join(" | ");
  check(t.includes("Пока подключены все словари"), "предупреждение показано");
  check(t.includes("Словарь договора") && t.includes("Старый словарь"), "все словари организации перечислены отмеченными");
}

console.log("\n[4] Окно нового проекта");
{
  hooks = []; hookIdx = 0;
  const tree = ImpNewFolder({ store: makeStore(), toast, meta: { langs: [["RU", "Русский"], ["EN", "Английский"]],
    domains: [["general", "Общая"], ["legal", "Право"]], domainDefault: "general" }, onClose() {} });
  const t = texts(tree).join(" | ");
  check(t.includes("Завести свой словарь"), "предложен свой словарь");
  check(t.includes("Словарь договора") && t.includes("Старый словарь"), "существующие словари — на выбор");
  check(find(tree, n => n.type === "input" && n.props.type === "checkbox").length === 3, "галочки: свой + два существующих");
  check(t.includes("Тема"), "тема названа простым словом");
}

console.log("\n[5] Имена верхнего уровня");
{
  const names = (src) => [...src.matchAll(/^(?:function\s+([A-Za-z_]\w*)|const\s+([A-Za-z_]\w*)\s*=)/gm)].map(m => m[1] || m[2]);
  const ui = new Set(names(uiSrc));
  const clash = names(impSrc).filter(n => ui.has(n));
  check(clash.length === 0, "tab_import.jsx не затирает имена из ui.jsx" + (clash.length ? ": " + clash.join(", ") : ""));
  check(!impSrc.includes("function ProjectCard("), "прежний ProjectCard убран (имя без префикса экрана)");
}

console.log("");
if (fail.length) { console.log("ПРОВАЛЕНО " + fail.length + ":"); fail.forEach(f => console.log("  - " + f)); process.exit(1); }
console.log("ВСЁ ПРОШЛО");
