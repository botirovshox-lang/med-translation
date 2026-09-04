/* Экран «Профиль» и переключатель команд: рендер без браузера.
 *
 * Тот же приём, что в test_pricing_render.js: сборки нет, .jsx выполняются
 * в браузере, поэтому сломанный компонент виден только там — белым экраном,
 * а `node --check` ловит лишь синтаксис.
 *
 * Проверяется то, что легко потерять молча:
 *   1. язык интерфейса выбирается КАЖДЫМ, и список языков берётся из I18N,
 *      а не переписан в .jsx своим литералом (два списка разойдутся);
 *   2. приглашение видно с ДВУМЯ кнопками — принять и отклонить: одна
 *      кнопка означала бы, что отказ приходится изображать молчанием;
 *   3. активная команда названа, а кнопки «перейти» у неё нет — мёртвая
 *      кнопка неотличима от сломанной;
 *   4. переключатель в шапке появляется только при ДВУХ и более командах;
 *   5. состав команды рисуется, и у домашней записи участника нет кнопок
 *      «исключить» и «сменить роль» — её правит экран «Организация»;
 *   6. на русском языке TR(s) === s побитово: включённый перевод НИЧЕГО
 *      не меняет в поведении экранов. Это и есть страховка от того, чтобы
 *      локализация сломала логику.
 *
 * Запуск: node tests/test_profile_render.js
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

const TEAM = {
  team: { id: "shifo", name: "Клиника Шифо", active: true },
  myRole: "owner",
  members: [
    { id: 1, login: "anna", name: "Анна", email: "anna@example.com", role: "owner", home: true,
      initials: "АН", color: "#2c7be5", active: true },
    { id: 2, login: "bob", name: "Боб", email: "bob@example.com", role: "translator", home: false,
      initials: "БО", color: "#22b07d", active: true },
  ],
  invites: [{ id: "zzz", email: "zed@example.com", role: "translator", status: "pending" }],
};
const PROFILE = {
  ok: true,
  me: { id: 1, login: "anna", name: "Анна", email: "anna@example.com", emailVerified: true,
        role: "owner", initials: "АН", color: "#2c7be5", uiLang: "uz" },
  activeTeam: "shifo", activeRole: "owner",
  teams: [
    { id: "acme", name: "ACME", role: "owner", home: true, members: 1 },
    { id: "shifo", name: "Клиника Шифо", role: "owner", home: false, members: 2 },
  ],
  invites: [{ id: "i1", tenant: "other", teamName: "Другая команда", email: "anna@example.com",
              role: "translator", by: "Пётр", at: "2026-09-01", status: "pending" }],
  canCreateTeam: true, teamLimit: 5,
};
global.API = {
  safeCall: async (fn) => fn(),
  profile: async () => PROFILE,
  teamDetail: async () => TEAM,
  // app.jsx монтируется сам при загрузке файла и первым делом спрашивает
  // токен: без заглушек он падает до первой проверки.
  hasToken: () => false,
  me: async () => ({ ok: true, me: PROFILE.me, can: { owner: true, super: false },
                     teams: PROFILE.teams, tenant: { id: "shifo", name: "Клиника Шифо" },
                     invites: PROFILE.invites }),
  models: async () => ({ ok: true }),
  seed: async () => ({ projects: [], glossary: [], tm: [] }),
};

const root = process.argv[2] || "frontend/js";
for (const f of ["i18n.js", "ui.jsx", "tab_profile.jsx", "app.jsx"]) {
  // app.jsx в конце монтирует себя в DOM — подставляем корень-заглушку.
  if (f === "app.jsx") {
    global.document.getElementById = () => ({});
    global.ReactDOM = { createRoot: () => ({ render() {} }) };
  }
  (0, eval)(fs.readFileSync(path.join(root, f), "utf8") + "\n//# sourceURL=" + f);
}

const toast = { info() {}, warning() {}, error() {}, success() {} };

function texts(node, out) {
  out = out || [];
  if (node == null || node === false || node === true) return out;
  if (typeof node === "string" || typeof node === "number") { out.push(String(node)); return out; }
  if (Array.isArray(node)) { node.forEach(n => texts(n, out)); return out; }
  if (node.props) {
    for (const k of ["label", "title", "placeholder", "aria-label"]) {
      if (typeof node.props[k] === "string") out.push(node.props[k]);
    }
  }
  (node.children || []).forEach(n => texts(n, out));
  return out;
}

/* Компоненты дёргаются напрямую: TabProfile ждёт данные из useEffect,
   а наш useEffect их не выполняет — иначе тест зависел бы от порядка
   промисов, а не от разметки. */
console.log("=== 1. Язык интерфейса ===");
hooks.length = 0; hookIdx = 0;
let node = ProfileIdentity({ data: PROFILE, onSaved() {}, toast, theme: "light", onToggleTheme() {} });
let t = texts(node).join(" | ");
check(t.includes("Язык интерфейса"), "секция языка на экране");
const langNames = (window.I18N.langs || []).map(l => l.native);
check(langNames.length >= 2, "языков в каталоге не меньше двух");
check(langNames.every(n => t.includes(n)), "каждый язык из I18N.langs — кнопкой (свой список в .jsx разошёлся бы)");
check(t.includes("Тёмная тема"), "переключатель темы переехал в профиль");
const src = fs.readFileSync(path.join(root, "tab_profile.jsx"), "utf8");
check(!/O.?zbekcha/.test(src.replace(/I18N/g, "")) || /window\.I18N\)\s*&&\s*window\.I18N\.langs/.test(src),
      "названия языков не переписаны литералами в tab_profile.jsx");

console.log("=== 2. Приглашение: два ответа, не один ===");
hooks.length = 0; hookIdx = 0;
node = ProfileInvites({ data: PROFILE, onChange() {}, toast });
t = texts(node).join(" | ");
check(t.includes("Другая команда"), "название команды названо");
check(t.includes("Принять") && t.includes("Отклонить"), "есть и «Принять», и «Отклонить»");
check(t.includes("Пётр"), "видно, кто пригласил");
hooks.length = 0; hookIdx = 0;
check(ProfileInvites({ data: { invites: [] }, onChange() {}, toast }) === null,
      "без приглашений карточки нет вовсе");

console.log("=== 3. Мои команды ===");
hooks.length = 0; hookIdx = 0;
node = ProfileTeams({ data: PROFILE, onChange() {}, toast });
t = texts(node).join(" | ");
check(t.includes("ACME") && t.includes("Клиника Шифо"), "обе команды в списке");
check(t.includes("· сейчас здесь"), "активная команда помечена");
check(t.includes("· домашняя"), "домашняя помечена");
const goCount = (t.match(/Перейти/g) || []).length;
check(goCount === 1, "кнопка «Перейти» ровно у неактивной команды (мёртвых кнопок нет), а не " + goCount);
const leaveCount = (t.match(/Выйти/g) || []).length;
check(leaveCount === 1, "«Выйти» есть только у не-домашней команды, а не " + leaveCount);
hooks.length = 0; hookIdx = 0;
t = texts(ProfileTeams({ data: { ...PROFILE, canCreateTeam: false }, onChange() {}, toast })).join(" | ");
check(t.includes("Достигнут потолок команд"), "на потолке сказано словами, а не погашенной кнопкой");

console.log("=== 4. Переключатель в шапке ===");
hooks.length = 0; hookIdx = 0;
check(TeamSwitcher({ store: { teams: [PROFILE.teams[0]], tenant: { id: "acme" } } }) === null,
      "с одной командой переключателя нет");
hooks.length = 0; hookIdx = 0;
node = TeamSwitcher({ store: { teams: PROFILE.teams, tenant: { id: "shifo" } } });
check(node && node.props.value === "shifo", "с двумя — есть, и выбрана активная");
check(texts(node).includes("ACME"), "в списке чужая команда тоже");

console.log("=== 5. Состав команды ===");
hooks.length = 0; hookIdx = 0;
ProfileMembers({ data: PROFILE, toast });          // первый рендер: данных ещё нет
hooks[hookIdx - 1] === undefined;
hooks.length = 0; hookIdx = 0;
hooks[0] = TEAM;                                    // подставляем ответ сервера
node = ProfileMembers({ data: PROFILE, toast });
t = texts(node).join(" | ");
check(t.includes("Анна") && t.includes("Боб"), "оба участника видны");
check(t.includes("Пригласить"), "приглашение по почте — на месте");
check(t.includes("zed@example.com"), "ждущее решения приглашение названо");
check(t.includes("домашняя запись"), "у домашней записи сказано, что правится она не здесь");
const excl = (t.match(/Исключить/g) || []).length;
check(excl === 1, "«Исключить» есть только у не-домашнего участника, а не " + excl);
// Роли — три, и меняются селектом (одним списком из ui.jsx), а не парой
// кнопок «→ владелец / → переводчик», которые разошлись бы первой новой ролью.
check(t.includes("Редактор") && t.includes("Переводчик") && t.includes("Владелец"),
      "роль участника — селект с тремя ролями: владелец / редактор / переводчик");
check(!t.includes("→ владелец") && !t.includes("→ переводчик"), "прежних кнопок «→ роль» больше нет");
check(t.includes("переводчик"), "подпись роли участника — через roleLabel");

console.log("=== 6. На русском перевод — тождество ===");
window.I18N.register("uz", { "Пароль": "Parol" });
window.I18N.setLang("ru", true);
check(TR("Пароль") === "Пароль", "TR на русском возвращает исходную строку");
check(TR("чего нет в словаре") === "чего нет в словаре", "и незнакомую тоже");
window.I18N.setLang("uz", true);
check(TR("Пароль") === "Parol", "на узбекском — перевод из словаря");
check(TR("чего нет в словаре") === "чего нет в словаре", "нет перевода — показываем русский оригинал, а не пустоту");
check(window.I18N.missCount() > 0, "непереведённое считается (иначе про дыры никто не узнает)");
check(TRS("Осталось: 5 из 10") === "Осталось: 5 из 10", "TRS без словаря ничего не портит");
/* Куски сообщений СЕРВЕРА живут в своей таблице: из неё и только из неё
   TRS() собирает фразовую подстановку. Обрывки надписей интерфейса внутри
   серверного сообщения дали бы кашу. */
window.I18N.registerServer("uz", { "Месячный лимит расхода": "Oylik xarajat chegarasi" });
check(TRS("Месячный лимит расхода исчерпан: $1.00").startsWith("Oylik xarajat chegarasi"),
      "TRS переводит фразой внутри собранного сервером сообщения, числа не трогая");
check(TRS("Месячный лимит расхода исчерпан: $1.00").includes("$1.00"), "и число на месте");

console.log();
if (fail.length) {
  console.log("ПРОВАЛЕНО: " + fail.length);
  fail.forEach(f => console.log("  - " + f));
  process.exit(1);
}
console.log("ВСЁ ПРОШЛО");
