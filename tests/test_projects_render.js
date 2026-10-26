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
  check(t.includes("Добавить ещё файл") && t.includes("Выбрать файл"), "блок добавления файла есть, с кнопкой «Выбрать файл»");
  check(!t.includes("Добавить в проект"), "пока файл не выбран, погашенной «Добавить в проект» нет");
  check(t.indexOf("Переводить") < t.indexOf("Добавить ещё файл") && t.indexOf("Добавить ещё файл") < t.indexOf("Словари проекта"),
        "порядок: файлы с «Переводить» → добавить файл → словари");
  check(t.includes("Словари проекта"), "блок словарей есть");
  const first = t.indexOf("Словарь договора"), second = t.indexOf("Старый словарь", t.indexOf("Словари проекта"));
  check(first >= 0 && second > first, "свёрнутые словари называют подключённые по порядку (первый — словарь договора)");
  check(t.includes("Настроить") && !t.includes("сюда пишутся новые слова"), "словари свёрнуты, настройка — по кнопке");
  check(t.includes("Удалить проект") && t.lastIndexOf("Удалить проект") > t.indexOf("Словари проекта"), "владельцу есть удаление проекта — внизу экрана");
  check(!t.includes("Пока подключены все словари"), "у папки со списком нет предупреждения «все»");
  check(find(tree, n => n.type === "input" && n.props.type === "file").length === 1, "поле выбора файла одно");

  /* Раскрытые словари: ImpFolderDicts — хуки picked, dirty, busy, open. */
  hooks = []; hooks[3] = true; hookIdx = 0;
  const dt = texts(ImpFolderDicts({ folder: folders[0], store: makeStore(), toast })).join(" | ");
  const a = dt.indexOf("Словарь договора"), b = dt.indexOf("Старый словарь");
  check(a >= 0 && b > a, "раскрытые: порядок словарей — как в папке");
  check(dt.includes("сюда пишутся новые слова"), "первый словарь помечен как место новых слов");
}

console.log("\n[3] Папка без списка словарей — честно «подключены все»");
{
  hooks = []; hookIdx = 0;
  let t = texts(TabImport({ store: makeStore({ viewFolder: 101 }), toast })).join(" | ");
  check(t.includes("все словари"), "свёрнутые: сказано «все словари»");
  hooks = []; hooks[3] = true; hookIdx = 0;
  t = texts(ImpFolderDicts({ folder: folders[1], store: makeStore(), toast })).join(" | ");
  check(t.includes("Пока подключены все словари"), "раскрытые: предупреждение показано");
  check(t.includes("Словарь договора") && t.includes("Старый словарь"), "все словари организации перечислены отмеченными");
}

console.log("\n[4] Окно нового проекта");
{
  /* Тема и словари — под «Ещё настройки» (хук 8 — more). Свёрнуто: только
     название и языки. */
  hooks = []; hookIdx = 0;
  const lite = texts(ImpNewFolder({ store: makeStore(), toast, meta: { langs: [["RU", "Русский"], ["EN", "Английский"]],
    domains: [["general", "Общая"]], domainDefault: "general" }, onClose() {} })).join(" | ");
  check(!lite.includes("Завести свой словарь") && !lite.includes("Тема") && lite.includes("Ещё настройки"),
        "в свёрнутом окне только название и языки, остальное — «Ещё настройки»");
  hooks = []; hooks[8] = true; hookIdx = 0;
  const tree = ImpNewFolder({ store: makeStore(), toast, meta: { langs: [["RU", "Русский"], ["EN", "Английский"]],
    domains: [["general", "Общая"], ["legal", "Право"]], domainDefault: "general" }, onClose() {} });
  const t = texts(tree).join(" | ");
  check(t.includes("Завести свой словарь"), "предложен свой словарь");
  check(t.includes("Словарь договора") && t.includes("Старый словарь"), "существующие словари — на выбор");
  check(find(tree, n => n.type === "input" && n.props.type === "checkbox").length === 3, "галочки: свой + два существующих");
  check(t.includes("Тема"), "тема названа простым словом");
}

console.log("\n[4a] Хватит ли страниц на файл — до нажатия «Добавить»");
{
  /* pay.jsx здесь не загружен: подсказка обязана жить и без него. */
  global.payBalance = () => ({ limited: true, pagesLeft: 3, over: false });
  global.usePayValue = () => null;
  hooks = []; hookIdx = 0;
  let t = texts(ImpPayHint({ store: makeStore({ can: { owner: true }, go() {} }), pages: 12 })).join(" | ");
  check(t.includes("Не хватает 9 стр.") && t.includes("Оплатить"), "не хватает — сказано сколько и кнопка «Оплатить»");
  global.payBalance = () => ({ limited: true, pagesLeft: 50, over: true });
  hooks = []; hookIdx = 0;
  t = texts(ImpPayHint({ store: makeStore({ can: { owner: false } }), pages: 12 })).join(" | ");
  check(t.includes("приостановлены") && t.includes("Попросите владельца") && !t.includes("лимит"),
        "переводы приостановлены — не владельцу «попросите владельца», без слова «лимит»");
  global.payBalance = () => ({ limited: true, pagesLeft: 50, over: false });
  hooks = []; hookIdx = 0;
  t = texts(ImpPayHint({ store: makeStore({ can: { owner: true } }), pages: 12 })).join(" | ");
  check(t.includes("Хватает") && !t.includes("Оплатить"), "хватает — спокойная строка без кнопки");
  delete global.payBalance; delete global.usePayValue;
}

console.log("\n[5] Имена верхнего уровня");
{
  const names = (src) => [...src.matchAll(/^(?:function\s+([A-Za-z_]\w*)|const\s+([A-Za-z_]\w*)\s*=)/gm)].map(m => m[1] || m[2]);
  const ui = new Set(names(uiSrc));
  const clash = names(impSrc).filter(n => ui.has(n));
  check(clash.length === 0, "tab_import.jsx не затирает имена из ui.jsx" + (clash.length ? ": " + clash.join(", ") : ""));
  check(!impSrc.includes("function ProjectCard("), "прежний ProjectCard убран (имя без префикса экрана)");
}

(async () => {
console.log("\n[1a] Первый файл: одна зона, один вопрос, одна кнопка");
{
  hooks = []; hookIdx = 0;
  let tree = TabImport({ store: makeStore({ folders: [], projects: [] }), toast });
  let t = texts(tree).join(" | ");
  check(t.includes("Перетащите файл сюда"), "без проектов — зона «Перетащите файл сюда»");
  check(!t.includes("Проектов пока нет"), "вместо пустого «Проектов пока нет» — сразу куда положить файл");
  check(!find(tree, n => n.type === "button" && texts(n).join("") === "Перевести").length, "до выбора файла кнопки «Перевести» нет");

  /* ImpFirstFile: hooks — file, src, tgt, busy, dragging. */
  const raw = { name: "Договор.docx", size: 2048 };
  hooks = [raw, "RU", ""]; hookIdx = 0;
  tree = ImpFirstFile({ store: makeStore({ folders: [] }), toast, meta: { langs: [["RU", "Русский"], ["UZ", "Узбекский"]] } });
  t = texts(tree).join(" | ");
  check(t.includes("На какой язык переводим?"), "спрошено, на какой язык переводим");
  let btn = find(tree, n => n.type === "button" && texts(n).join("") === "Перевести")[0];
  check(btn && btn.props.disabled, "пока язык перевода не выбран — «Перевести» погашена (умолчания нет намеренно)");

  hooks = [raw, "RU", "UZ"]; hookIdx = 0;
  const opened = [], made = [];
  global.API.createFolder = async (body) => { made.push(body); return { id: 555, title: body.title, src: body.src, tgt: body.tgt }; };
  global.API.listDicts = async () => null;
  tree = ImpFirstFile({ store: makeStore({ folders: [], openFolder: (id) => opened.push(id) }), toast, meta: { langs: [] } });
  btn = find(tree, n => n.type === "button" && texts(n).join("") === "Перевести")[0];
  check(btn && !btn.props.disabled, "язык выбран — «Перевести» доступна");
  await btn.props.onClick();
  check(made.length === 1 && made[0].title === "Договор" && made[0].tgt === "UZ" && made[0].newDict === "Договор",
        "проект заведён по нажатию: имя файла, выбранная пара, свой словарь");
  check(opened.join() === "555", "и открыт");
  const d = impDraft(555);
  check(d.autoAdd === true && d.file && d.file.raw === raw && d.tgt === "UZ",
        "файл и пара лежат в черновике проекта с отметкой «добавить самому»");
  check(d.autoRun === true, "человек нажал «Перевести» — после загрузки перевод стартует сам (autoRun)");
}


console.log("\n[1b] Файл с лендинга: вопросы уже заданы, второй раз их не задаём");
{
  /* Форма на лендинге спросила файл и язык; после регистрации экран
     «Проекты» обязан подставить оба (store.handoff), а не спрашивать снова. */
  const raw = { name: "Статья.docx", size: 4096 };
  const meta = { langs: [["RU", "Русский"], ["EN", "Английский"], ["UZ", "Узбекский"]] };
  let cleared = 0;
  hooks = []; hookIdx = 0;
  let tree = TabImport({ store: makeStore({ folders: [{ id: 1, title: "Старое", files: [] }], projects: [],
    handoff: { file: raw, name: raw.name, src: "RU", tgt: "EN" } }), toast });
  let t = texts(tree).join(" | ");
  check(t.includes("Статья.docx"), "проекты уже есть, а файл с сайта всё равно первым на экране");

  hooks = []; hookIdx = 0;
  const made = [], opened = [];
  global.API.createFolder = async (body) => { made.push(body); return { id: 777, title: body.title, src: body.src, tgt: body.tgt }; };
  global.API.listDicts = async () => null;
  const hfCalls = [];
  global.MCT_HANDOFF = { update: (p) => { hfCalls.push("update:" + JSON.stringify(p)); return Promise.resolve(); },
                         drop: () => { hfCalls.push("drop"); return Promise.resolve(); } };
  const st = makeStore({ folders: [], openFolder: (id) => opened.push(id),
    handoff: { file: raw, name: raw.name, src: "RU", tgt: "EN" }, clearHandoff: () => { cleared++; } });
  tree = ImpFirstFile({ store: st, toast, meta });
  t = texts(tree).join(" | ");
  check(t.includes("Статья.docx") && t.includes("Файл с сайта"), "файл подставлен и назван «с сайта»");
  const btn = find(tree, n => n.type === "button" && texts(n).join("") === "Перевести")[0];
  check(btn && !btn.props.disabled, "пара подставлена — кнопка открыта сразу");
  await btn.props.onClick();
  check(made.length === 1 && made[0].src === "RU" && made[0].tgt === "EN" && made[0].title === "Статья",
        "проект заведён на паре с сайта");
  check(cleared === 1 && opened.join() === "777", "экран первого файла отработал, папка открыта");
  check(hfCalls.join() === 'update:{"folder":777}',
        "файл с сайта НЕ стёрт из браузера при заведении папки — только запомнена папка: " + hfCalls.join());
  check(impDraft(777).fromHandoff === true && impDraft(777).autoRun === true, "черновик знает, что файл с сайта и что перевод стартует сам");

  /* Возврат с кассы: папка уже есть — вторую не заводим. */
  hooks = []; hookIdx = 0; made.length = 0; opened.length = 0;
  tree = ImpFirstFile({ store: makeStore({ folders: [{ id: 777, title: "Статья", files: [] }], openFolder: (id) => opened.push(id),
    handoff: { file: raw, name: raw.name, src: "RU", tgt: "EN", folder: 777 }, clearHandoff: () => {} }), toast, meta });
  await find(tree, n => n.type === "button" && texts(n).join("") === "Перевести")[0].props.onClick();
  check(made.length === 0 && opened.join() === "777", "возврат с кассы: прежняя папка открыта, новой нет");

  /* Файл не доехал (браузер не дал хранилище) — пара всё равно подставлена,
     и человеку сказано, что файл надо выбрать ещё раз. */
  hooks = []; hookIdx = 0;
  tree = ImpFirstFile({ store: makeStore({ folders: [], handoff: { file: null, src: "RU", tgt: "UZ" } }), toast, meta });
  t = texts(tree).join(" | ");
  check(t.includes("Выберите файл ещё раз"), "без файла — просьба выбрать его ещё раз");
  check(hooks[2] === "UZ", "язык перевода с сайта подставлен и без файла");

  /* Код, которого нет в каталоге сервера (лендинг собран отдельно и мог
     отстать), не подставляется: пустой выбор честнее неизвестной пары. */
  hooks = []; hookIdx = 0;
  ImpFirstFile({ store: makeStore({ folders: [], handoff: { file: raw, src: "RU", tgt: "XX" } }), toast, meta });
  check(hooks[2] === "", "неизвестный код языка не подставлен");
}

console.log("\n[6] Удаление файла ждёт сервер: отказ назван, файл не пропал");
{
  /* Прежде файл уходил с экрана сразу, а отказ сервера (409 — идёт прогон)
     глотал safeCall: на экране пусто, на сервере файл жив. */
  hooks = []; hookIdx = 0;
  hooks[0] = true;                                   // окно «Удалить файл?» открыто
  const errs = [], warns = [];
  const tst = { info() {}, success() {}, warning: (t) => warns.push(t), error: (t, m) => errs.push(t + " | " + m) };
  const st = makeStore({ deleteProject: async () => ({ ok: false, error: "Идёт прогон — дождитесь конца" }) });
  const tree = ImpFileCard({ project: projects[1], store: st, toast: tst });
  const del = find(tree, n => n.type === "button" && texts(n).join("") === "Удалить")[0];
  await del.props.onClick();
  check(errs.length === 1 && errs[0].indexOf("Идёт прогон") !== -1 && !warns.length,
        "отказ сервера — ошибкой его словами, «Файл удалён» не сказано: " + errs.join(" / "));
}

console.log("\n[7] Дубль при загрузке (409): «Открыть проект» по полям ответа");
{
  const d = impDraft(102);
  d.file = { name: "t.docx", size: "1 КБ", raw: { name: "t.docx" } };
  d.probe = { ok: true, exact: [], similar: [] };
  const errs = [];
  const tst = { info() {}, success() {}, warning() {}, error: (t, m) => errs.push(t + " | " + m) };
  const opened = [];
  const st = makeStore({ openProject: (id) => opened.push(id) });
  global.API.uploadProject = async () => {
    const e = new Error("Этот файл уже загружен на ту же пару языков. Откройте готовый проект или замените файл повторным импортом");
    e.status = 409;
    e.data = { code: "duplicate", project: { id: 104, title: "Приложение 2", folder: 102 } };
    throw e;
  };
  hooks = []; hookIdx = 0;
  const folder = folders[0];
  const meta = { langs: [["RU", "Русский"], ["EN", "Английский"]] };
  let tree = ImpAddFile({ folder, store: st, toast: tst, meta });
  await find(tree, n => n.type === "button" && texts(n).join("").indexOf("Добавить в проект") !== -1)[0].props.onClick();
  hookIdx = 0;
  tree = ImpAddFile({ folder, store: st, toast: tst, meta });
  const t = texts(tree).join(" | ");
  check(errs.length === 1 && errs[0].indexOf("повторным импортом") !== -1, "ошибка названа словами сервера");
  check(t.indexOf("Приложение 2") !== -1, "проект-дубль назван по полю ответа, а не по тексту");
  const open = find(tree, n => n.type === "button" && texts(n).join("") === "Открыть проект")[0];
  check(!!open, "есть кнопка «Открыть проект»");
  if (open) open.props.onClick();
  check(opened.join() === "104", "она открывает проект-дубль: " + opened.join());
}

console.log("\n[7a] Не хватило страниц (402): файл ждёт оплаты, потом проект и перевод сами");
{
  const d = impDraft(102);
  d.file = { name: "big.docx", size: "1 МБ", raw: { name: "big.docx" } };
  d.probe = { ok: true, exact: [], similar: [] };
  d.fromHandoff = true; d.autoRun = true; d.payWait = false;
  const errs = [], warns = [], hfCalls = [], armed = [], opened = [];
  global.MCT_HANDOFF = { update: (p) => { hfCalls.push("update:" + JSON.stringify(p)); return Promise.resolve(); },
                         drop: () => { hfCalls.push("drop"); return Promise.resolve(); } };
  global.edAutoRunArm = (pid) => armed.push(pid);
  const tst = { info() {}, success() {}, warning: (t) => warns.push(t), error: (t, m) => errs.push(t + " | " + m) };
  const st = makeStore({ openProject: (id) => opened.push(id) });
  global.API.uploadProject = async () => { const e = new Error("страниц не хватает"); e.status = 402; throw e; };
  hooks = []; hookIdx = 0;
  const folder = folders[0];
  const meta = { langs: [["RU", "Русский"], ["EN", "Английский"]] };
  let tree = ImpAddFile({ folder, store: st, toast: tst, meta });
  await find(tree, n => n.type === "button" && texts(n).join("").indexOf("Добавить в проект") !== -1)[0].props.onClick();
  check(d.payWait === true && d.file && d.file.raw, "402: файл остался в черновике и ждёт оплаты");
  check(!errs.length && warns.indexOf("Файл ждёт оплаты") !== -1, "сказано «ждёт оплаты», а не «файл не добавлен»");
  check(hfCalls.join() === 'update:{"folder":102,"payWait":true}', "в браузере отмечено «ждём оплату» и папка (переживёт кассу): " + hfCalls.join());
  hfCalls.length = 0;
  global.API.uploadProject = async () => ({ id: 909, title: "big", segments: [{ id: 1 }], folder: 102 });
  hookIdx = 0;
  tree = ImpAddFile({ folder, store: st, toast: tst, meta });
  await find(tree, n => n.type === "button" && texts(n).join("").indexOf("Добавить в проект") !== -1)[0].props.onClick();
  check(hfCalls.join() === "drop", "проект заведён — файл с сайта снят из браузера");
  check(armed.join() === "909" && opened.join() === "909", "и перевод поставлен сам (edAutoRunArm), файл открыт");
  check(!d.payWait && !d.autoRun, "отметки ожидания сняты");

  /* Файл выбран в приложении (не с лендинга): на время оплаты он тоже
     кладётся в браузер — касса уводит со страницы. */
  d.file = { name: "own.docx", size: "1 МБ", raw: { name: "own.docx" } };
  d.fromHandoff = false; d.payWait = false; d.fly = false; d.probe = { ok: true, exact: [], similar: [] };
  hfCalls.length = 0;
  global.MCT_HANDOFF.put = (r) => { hfCalls.push("put:" + r.file.name); return Promise.resolve(); };
  global.API.uploadProject = async () => { const e = new Error("страниц не хватает"); e.status = 402; throw e; };
  hooks = []; hookIdx = 0;
  tree = ImpAddFile({ folder, store: st, toast: tst, meta });
  await find(tree, n => n.type === "button" && texts(n).join("").indexOf("Добавить в проект") !== -1)[0].props.onClick();
  check(hfCalls.join() === 'put:own.docx,update:{"folder":102,"payWait":true}' && d.fromHandoff === true,
        "свой файл положен в браузер до оплаты: " + hfCalls.join());

  /* Другой отказ (не 402): копия в браузере снимается, решает человек. */
  hfCalls.length = 0; d.payWait = false; d.fly = false;
  global.API.uploadProject = async () => { const e = new Error("не разобрался"); e.status = 415; throw e; };
  hooks = []; hookIdx = 0;
  tree = ImpAddFile({ folder, store: st, toast: tst, meta });
  await find(tree, n => n.type === "button" && texts(n).join("").indexOf("Добавить в проект") !== -1)[0].props.onClick();
  check(hfCalls.join() === "drop" && !d.fromHandoff, "отказ не по оплате — файл снят из браузера");
  delete global.edAutoRunArm;
}

console.log("\n[8] Файл-картинка: чтение ведёт в «Перевод», причина названа");
{
  hooks = []; hookIdx = 0;
  const opened = [], went = [];
  const pic = { id: 110, title: "photo", src: "RU", tgt: "AR", importKind: "image", segments: [], imagesSkipped: "limit" };
  const st = makeStore({ openProject: (id) => opened.push(id), go: (k) => went.push(k) });
  const tree = ImpFileCard({ project: pic, store: st, toast });
  const t = texts(tree).join(" | ");
  check(t.indexOf("лимит расхода организации исчерпан") !== -1, "сказано, почему текст сам не прочитался");
  const b = find(tree, n => n.type === "button" && texts(n).join("") === "Прочитать текст с картинок")[0];
  check(!!b, "кнопка «Прочитать текст с картинок» есть");
  if (b) b.props.onClick();
  check(opened.join() === "110" && went.indexOf("export") < 0, "она открывает файл в «Переводе», а не на «Скачать»");
}

console.log("");
if (fail.length) { console.log("ПРОВАЛЕНО " + fail.length + ":"); fail.forEach(f => console.log("  - " + f)); process.exit(1); }
console.log("ВСЁ ПРОШЛО");
})();
