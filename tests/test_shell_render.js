/* Оболочка приложения: боковое меню и тонкая шапка — рендер без браузера.
 *
 * Зачем отдельный набор: сборки нет, .jsx выполняются в браузере, поэтому
 * ошибка в оболочке видна только там — БЕЛЫМ ЭКРАНОМ, причём во всём
 * приложении сразу, а не на одном экране. Остальные рендер-тесты грузят
 * app.jsx, но саму оболочку не вызывают: тела Sidebar и Topbar выполняются
 * только при рендере.
 *
 * Проверяется то, что легко потерять молча:
 *   1. в меню есть ВСЕ вкладки, которые видит этот пользователь, — при
 *      переезде с горизонтальной ленты потерять пункт проще всего, а
 *      пропавшая вкладка неотличима от удалённой функции;
 *   2. права соблюдены: «Организация» только владельцу, «Админ» только
 *      суперпользователю и только со служебного адреса;
 *   3. активный пункт помечен ровно один;
 *   4. счётчики те же, что были на вкладках (сегменты, замечания, термины,
 *      приглашения) — их считает tabBadge, один расчёт на меню и крошки;
 *   5. полоса страниц рисуется, только когда потолок ВЫДАН: «0 из 0»
 *      читалось бы как «всё кончилось», а это «без потолка»;
 *   6. крошки называют вкладку и проект;
 *   7. в шапке остались двери, которые были в прежней: поиск, тема,
 *      профиль, выход;
 *   8. на русском TR(s) === s побитово — включённый перевод ничего
 *      не меняет в поведении.
 *
 * Запуск: node tests/test_shell_render.js
 */
const fs = require("fs");
const path = require("path");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

const hooks = [];
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
const mem = {
  memory: {},
  getItem(k) { return this.memory[k] || null; },
  setItem(k, v) { this.memory[k] = String(v); },
  removeItem(k) { delete this.memory[k]; },
};
global.React = React;
global.useState = useState; global.useEffect = useEffect;
global.useRef = useRef; global.useMemo = useMemo; global.useCallback = useCallback;
global.createContext = createContext; global.useContext = useContext;
global.localStorage = mem;
global.sessionStorage = mem;
global.window = global;
global.document = { addEventListener() {}, removeEventListener() {}, querySelector() { return null; } };
global.API = {
  safeCall: async (fn) => fn(),
  hasToken: () => false,
  me: async () => ({ ok: true }),
  models: async () => ({ ok: true }),
  seed: async () => ({ projects: [], glossary: [], tm: [] }),
};

const root = process.argv[2] || "frontend/js";
for (const f of ["i18n.js", "ui.jsx", "app.jsx"]) {
  if (f === "app.jsx") {
    global.document.getElementById = () => ({});
    global.ReactDOM = { createRoot: () => ({ render() {} }) };
  }
  (0, eval)(fs.readFileSync(path.join(root, f), "utf8") + "\n//# sourceURL=" + f);
}

/* ---------- обход дерева ---------- */
function walk(node, fn) {
  if (node == null || node === false || node === true) return;
  if (Array.isArray(node)) { node.forEach(n => walk(n, fn)); return; }
  if (typeof node !== "object") return;
  fn(node);
  walk(node.children, fn);
}
function texts(node) {
  const out = [];
  walk(node, (n) => {
    (n.children || []).forEach(c => { if (typeof c === "string" || typeof c === "number") out.push(String(c)); });
    for (const k of ["label", "title", "aria-label"]) {
      if (n.props && typeof n.props[k] === "string") out.push(n.props[k]);
    }
  });
  return out;
}
function byClass(node, cls) {
  const out = [];
  walk(node, (n) => {
    const c = n.props && n.props.className;
    if (typeof c === "string" && c.split(" ").indexOf(cls) >= 0) out.push(n);
  });
  return out;
}

const PROJECT = { id: 1, title: "Фтизиатрия. Учебник", segments: [] };
function makeStore(over) {
  return Object.assign({
    tab: "editor",
    brand: "CAT Translator",
    activeProject: PROJECT,
    statusCounts: () => ({ all: 2711, failed: 4, qa: 7, new: 0, translated: 0, confirmed: 0, review: 0 }),
    glossary: new Array(1307),
    me: { id: 1, name: "Шохрух", initials: "ШО", color: "#2c7be5" },
    can: { owner: true, super: false, role: "owner" },
    teams: [{ id: "med", name: "Медиздат", role: "owner", home: true }],
    tenant: { id: "med", name: "Медиздат" },
    invites: [],
    caps: null, usage: null,
    go() {},
  }, over || {});
}

console.log("1. Меню: состав и права");
{
  const s = makeStore();
  const side = Sidebar({ store: s, theme: "light", onToggleTheme() {}, onLogout() {} });
  const items = byClass(side, "navi");
  const labels = items.map(n => texts(n).join(" "));
  const has = (t) => labels.some(l => l.indexOf(t) >= 0);
  check(items.length >= 7, "пунктов меню не меньше семи (сейчас " + items.length + ")");
  ["Редактор", "Знания", "Анализ", "Экспорт", "Импорт", "Профиль"].forEach(t =>
    check(has(t), "в меню есть «" + t + "»"));
  check(has("Организация"), "владелец видит «Организация»");
  check(!has("Админ"), "без служебного адреса «Админ» не показывается");

  const noOwner = Sidebar({ store: makeStore({ can: { owner: false, super: false, role: "translator" } }),
    theme: "light", onToggleTheme() {}, onLogout() {} });
  const noOwnerLabels = byClass(noOwner, "navi").map(n => texts(n).join(" "));
  check(!noOwnerLabels.some(l => l.indexOf("Организация") >= 0), "переводчику «Организация» не показывается");
}

console.log("2. Активный пункт ровно один");
{
  const side = Sidebar({ store: makeStore({ tab: "preflight" }), theme: "light", onToggleTheme() {}, onLogout() {} });
  const on = byClass(side, "navi").filter(n => (n.props.className || "").indexOf(" on") >= 0);
  check(on.length === 1, "помечен один пункт (сейчас " + on.length + ")");
  check(texts(on[0]).join(" ").indexOf("Анализ") >= 0, "помечен именно открытый экран");
}

console.log("3. Счётчики те же, что были на вкладках");
{
  const side = Sidebar({ store: makeStore({ invites: [{ id: "i1" }, { id: "i2" }] }),
    theme: "light", onToggleTheme() {}, onLogout() {} });
  const nums = byClass(side, "navi-n").map(n => String(n.children[0]));
  check(nums.indexOf("2711") >= 0, "у редактора число сегментов");
  check(nums.indexOf("11") >= 0, "у анализа сумма замечаний (4 + 7)");
  check(nums.indexOf("1307") >= 0, "у знаний размер глоссария");
  check(nums.indexOf("2") >= 0, "у профиля число приглашений");

  /* Красная пилюля (.navi-n.todo) означает РАБОТУ, которая ждёт человека.
     Число всего написанного ею быть не может: «2711» и «1307» — размер
     работы, с которым делать нечего, и, покрашенные тревогой, они заглушат
     вопрос на пять строк, ради которого пилюля и заведена. Сторожим обе
     стороны: забытый .todo (вопрос молчит) и лишний (размер кричит).
     Ключ — НАДПИСЬ пункта, а не число на пилюле: числа в наборе совпадают
     легко (сегментов ровно столько же, сколько приглашений), и по числу
     пункты затирали бы друг друга — проверка молча перестала бы смотреть
     на тот, ради которого заведена. */
  const kind = {};
  byClass(side, "navi").forEach(item => {
    const pill = byClass(item, "navi-n")[0];
    if (!pill) return;
    const name = (byClass(item, "navi-t")[0] || { children: [] }).children[0];
    kind[String(name)] = (pill.props.className || "").indexOf("todo") >= 0;
  });
  check(Object.keys(kind).length === 4, "пилюли нашлись у всех четырёх пунктов (сейчас "
    + Object.keys(kind).length + ")");
  check(kind["Анализ"] === true, "замечания помечены как ждущая работа");
  check(kind["Профиль"] === true, "приглашения помечены как ждущая работа");
  check(kind["Редактор"] === false, "число сегментов тревогой не красится");
  check(kind["Знания"] === false, "размер глоссария тревогой не красится");
}

console.log("4. Полоса страниц — только при выданном потолке");
{
  const off = Sidebar({ store: makeStore(), theme: "light", onToggleTheme() {}, onLogout() {} });
  check(byClass(off, "side-foot").length === 0, "без потолка полосы нет");

  const on = Sidebar({ store: makeStore({ caps: { pagesLimited: true, maxPages: 2000 }, usage: { pages: 1240 } }),
    theme: "light", onToggleTheme() {}, onLogout() {} });
  const foot = byClass(on, "side-foot");
  check(foot.length === 1, "с потолком полоса есть");
  check(texts(foot[0]).some(t => t.indexOf("760") >= 0), "названо, сколько осталось (2000 − 1240)");
  const bar = byClass(on, "sf-meter")[0];
  check(bar && bar.children[0].props.style.width === "62%", "полоса заполнена по расходу");
}

console.log("5. Шапка: крошки и двери");
{
  const top = Topbar({ store: makeStore({ tab: "export" }), theme: "light",
    onToggleTheme() {}, onLogout() {}, onSearch() {} });
  const t = texts(top).join(" | ");
  check(t.indexOf("Экспорт") >= 0, "в крошках названа вкладка");
  check(t.indexOf("Фтизиатрия. Учебник") >= 0, "в крошках назван проект");
  ["Поиск", "Профиль", "Выйти"].forEach(x => check(t.indexOf(x) >= 0, "в шапке осталась дверь «" + x + "»"));

  const noProj = Topbar({ store: makeStore({ activeProject: null }), theme: "light",
    onToggleTheme() {}, onLogout() {}, onSearch() {} });
  check(texts(noProj).join(" ").indexOf("/") < 0, "без проекта разделителя крошек нет");
}

console.log("6. Перевод ничего не меняет на русском");
{
  ["Работа", "Файлы", "Служебное", "Страницы", "Редактор", "Экспорт"].forEach(s =>
    check(TR(s) === s, "TR(\"" + s + "\") === s"));
}

console.log(fail.length ? "\nПРОВАЛЫ: " + fail.length + "\n" + fail.join("\n") : "\nВСЁ ПРОШЛО");
process.exit(fail.length ? 1 : 0);
