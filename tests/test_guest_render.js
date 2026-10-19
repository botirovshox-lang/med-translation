/* Экран гостя (guest.jsx, инвариант 43): собирается ли он вообще и говорит ли
 * человеку то, что обещано.
 *
 * Сборки у фронтенда нет — сломанный компонент виден только БЕЛЫМ ЭКРАНОМ,
 * а экран гостя — первый, что видит человек с лендинга. Тест выполняет файл
 * с заглушкой React и смотрит, что собралось.
 *
 * Что сторожится:
 *   1. Когда показывать экран гостя вместо входа (`guestWanted`).
 *   2. Первый экран: одна главная кнопка, согласие со ссылками на оферту
 *      и политику, дверь «у меня есть аккаунт»; при капче кнопка ждёт её.
 *   3. Результат гостя: «Скачать перевод» ведёт к почте и коду, стена
 *      объясняет, что продаётся (файл в вёрстке), строки видны рядом.
 *   4. Клиент из гостя: «Скачать файл», пароль задаётся без нынешнего,
 *      есть выход в приложение.
 *   5. Формат выгрузки — «как в оригинале» там, где он есть.
 *   6. Загрузчик ставит guest.jsx ДО app.jsx (экран рисуется без вкладок).
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");
const JS = path.join(ROOT, "frontend", "js");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

let hooks, hookIx, effects;
const React = {
  createElement(type, props, ...kids) {
    const ch = [];
    kids.forEach(function push(k) {
      if (Array.isArray(k)) k.forEach(push);
      else if (k !== null && k !== undefined && k !== false && k !== true) ch.push(k);
    });
    return { type, props: props || {}, children: ch };
  },
};
function useState(init) {
  const i = hookIx++;
  if (!(i in hooks)) hooks[i] = typeof init === "function" ? init() : init;
  return [hooks[i], (v) => { hooks[i] = typeof v === "function" ? v(hooks[i]) : v; }];
}
function useRef(init) {
  const i = hookIx++;
  if (!(i in hooks)) hooks[i] = { current: init };
  return hooks[i];
}
function useEffect(fn, deps) { effects.push({ fn, deps }); }

function walk(node, out) {
  out = out || [];
  if (!node || typeof node !== "object") return out;
  if (typeof node.type === "function") {
    const savedH = hooks, savedI = hookIx;
    hooks = node.__hooks || (node.__hooks = {}); hookIx = 0;
    let inner = null;
    const props = (node.children && node.children.length)
      ? Object.assign({}, node.props, { children: node.children.length === 1 ? node.children[0] : node.children })
      : node.props;
    try { inner = node.type(props); } catch (e) { inner = { type: "error", props: {}, children: [String(e)] }; }
    hooks = savedH; hookIx = savedI;
    out.push(node);
    return walk(inner, out);
  }
  out.push(node);
  (node.children || []).forEach(c => walk(c, out));
  return out;
}
function texts(tree) {
  return walk(tree).flatMap(n => (n.children || []).filter(c => typeof c === "string")).join(" | ");
}
function byText(tree, s) {
  return walk(tree).filter(n => (n.children || []).some(c => typeof c === "string" && c.indexOf(s) >= 0));
}
function btnOf(tree, s) {
  return walk(tree).find(n => (n.type && (n.type.name === "Btn" || n.type === "button"))
    && texts(n).indexOf(s) >= 0) || null;
}

const store = { local: {}, session: {} };
const mkStorage = (o) => ({
  getItem: (k) => (k in o ? o[k] : null), setItem: (k, v) => { o[k] = String(v); },
  removeItem: (k) => { delete o[k]; },
});
let hasToken = false;
const sandbox = {
  React, useState, useEffect, useRef,
  console, setTimeout, clearTimeout, URLSearchParams, JSON, Number, String, Math, Promise,
  TR: (s) => s, TRS: (s) => s,
  Icon: function Icon(p) { return React.createElement("icon", p); },
  Btn: function Btn(p) { return React.createElement("button", Object.assign({}, p, { children: undefined }), p.children); },
  Input: function Input(p) { return React.createElement("input", p); },
  Select: function Select(p) { return React.createElement("select", p, p.children); },
  Spinner: function Spinner() { return React.createElement("spinner", {}); },
  ProgressBar: function ProgressBar(p) { return React.createElement("pbar", p); },
  Modal: function Modal(p) { return React.createElement("modal", { title: p.title }, p.children); },
  localStorage: mkStorage(store.local),
  sessionStorage: mkStorage(store.session),
  document: { getElementById: () => null, createElement: () => ({ addEventListener() {} }), head: { appendChild() {} } },
  window: {
    location: { search: "" },
    addEventListener() {}, removeEventListener() {},
    API: { hasToken: () => hasToken },
    I18N: { lang: "ru" },
  },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
const src = fs.readFileSync(path.join(JS, "guest.jsx"), "utf8");
vm.runInContext(src + "\n;globalThis.__G = { GuestApp, GuestClaim, guestWanted, guestFormat, guestPhaseText };", sandbox);
const G = sandbox.__G;

function render(comp, props, preset) {
  hooks = Object.assign({}, preset || {}); hookIx = 0; effects = [];
  const node = { type: comp, props: props || {}, __hooks: hooks };
  return node;
}
/* Порядок хуков GuestApp: info, stage, file, langs, captcha, err, phase, pct,
   project, me, claim, view, pw, alive. */
const INFO = { enabled: true, turnstile: "", freePages: 1, signupPages: 1, mediaSec: 60, mediaMb: 500, maxMb: 32,
               brand: "Simple", languages: [{ code: "RU", native: "Русский" }, { code: "EN", native: "English" }] };

console.log("=== 1. Когда экран гостя ===");
sandbox.window.location.search = "?try=1";
check(G.guestWanted() === true, "?try=1 без токена — экран гостя");
sandbox.window.location.search = "?start=translate&src=RU&tgt=EN";
check(G.guestWanted() === true, "с формы лендинга — экран гостя, а не регистрация");
sandbox.window.location.search = "";
check(G.guestWanted() === false, "просто адрес без следов гостя — вход");
store.local["mct-guest"] = JSON.stringify({ key: "k" });
check(G.guestWanted() === true, "гость этого браузера — его перевод");
store.session["mct-guest-off"] = "1";
check(G.guestWanted() === false, "«у меня есть аккаунт» гасит экран гостя до конца вкладки");
delete store.session["mct-guest-off"];
hasToken = true;
check(G.guestWanted() === false, "вошедший видит приложение");
store.session["mct-guest-view"] = "1";
check(G.guestWanted() === true, "отметка вида гостя переживает перезагрузку");
delete store.session["mct-guest-view"]; delete store.local["mct-guest"]; hasToken = false;

console.log("=== 2. Первый экран ===");
let t = render(G.GuestApp, { toast: {}, onExit() {} }, { 0: INFO, 1: "pick", 3: { src: "RU", tgt: "" } });
let all = texts(t);
check(all.indexOf("Переведём первую страницу бесплатно") >= 0, "заголовок обещает первую страницу бесплатно");
let go = btnOf(t, "Перевести бесплатно");
check(go && go.props.disabled, "без файла и языка главная кнопка погашена");
check(walk(t).some(n => n.type === "a" && n.props.href === "/terms") && walk(t).some(n => n.type === "a" && n.props.href === "/privacy"),
      "согласие — со ссылками на оферту и политику");
check(all.indexOf("поставщики ИИ за рубежом") >= 0, "названо: текст уходит поставщикам ИИ за рубежом");
check(!!btnOf(t, "У меня есть аккаунт — войти"), "дверь «у меня есть аккаунт»");
t = render(G.GuestApp, { toast: {}, onExit() {} }, { 0: INFO, 1: "pick", 2: { name: "a.docx", size: 10 }, 3: { src: "RU", tgt: "EN" } });
go = btnOf(t, "Перевести бесплатно");
check(go && !go.props.disabled, "файл и язык выбраны — кнопка доступна");
t = render(G.GuestApp, { toast: {}, onExit() {} }, { 0: Object.assign({}, INFO, { turnstile: "site" }), 1: "pick",
  2: { name: "a.docx", size: 10 }, 3: { src: "RU", tgt: "EN" }, 4: "" });
go = btnOf(t, "Перевести бесплатно");
check(go && go.props.disabled, "капча включена и не пройдена — кнопка ждёт");
check(walk(t).some(n => n.type && n.type.name === "GuestCaptcha"), "капча нарисована");
t = render(G.GuestApp, { toast: {}, onExit() {} }, { 0: INFO, 1: "pick", 2: { name: "talk.mp4", size: 10 }, 3: { src: "RU", tgt: "EN" } });
check(texts(t).indexOf("первую минуту видео") >= 0, "у видео сказано: бесплатно — первая минута");

console.log("=== 3. Результат гостя ===");
const P = { id: 5, src: "RU", tgt: "EN", importKind: "docx", fileName: "a.docx",
            trialExcerpt: { filePages: 4.8, pages: 0.9 },
            segments: [{ id: 1, source: "Привет", target: "Hello" }, { id: 2, source: "Мир", target: "" }] };
t = render(G.GuestApp, { toast: {}, onExit() {} }, { 0: INFO, 1: "done", 8: P, 9: { guest: true } });
all = texts(t);
check(!!btnOf(t, "Скачать перевод"), "главная кнопка — «Скачать перевод»");
check(all.indexOf("исходной вёрстке") >= 0 && all.indexOf("почта и код") >= 0,
      "стена говорит, что продаётся: файл в вёрстке, после почты и кода");
check(all.indexOf("Переведена первая страница из ") >= 0, "сказано, что переведена первая страница из N");
check(all.indexOf("Не переведено строк: ") >= 0, "непереведённое названо числом");
check(all.indexOf("Hello") >= 0 && all.indexOf("Привет") >= 0, "оригинал и перевод рядом");
check(!byText(t, "Задайте пароль").length && !btnOf(t, "Открыть приложение"), "гостю ни пароля, ни приложения");
t = render(G.GuestApp, { toast: {}, onExit() {} }, { 0: INFO, 1: "done", 8: P, 9: { guest: true }, 10: true });
check(walk(t).some(n => n.type && n.type.name === "GuestClaim"), "нажатие «скачать» у гостя — окно почты и кода");

console.log("=== 4. Клиент из гостя ===");
t = render(G.GuestApp, { toast: {}, onExit() {} }, { 0: INFO, 1: "done", 8: P, 9: { guest: false, noPassword: true } });
check(!!btnOf(t, "Скачать файл"), "«Скачать файл» без стены");
check(byText(t, "Задайте пароль, чтобы вернуться").length > 0, "предложено задать пароль");
check(!!btnOf(t, "Открыть приложение"), "выход в приложение");
check(walk(t).some(n => n.type && n.type.name === "GuestRest"), "предложение перевести весь документ");

console.log("=== 5. Окно почты и кода ===");
t = render(G.GuestClaim, { onClose() {}, onDone() {}, onLogin() {} }, { 2: "" });
let b = btnOf(t, "Получить код");
check(b && b.props.disabled, "без почты код не просим");
t = render(G.GuestClaim, { onClose() {}, onDone() {}, onLogin() {} }, { 1: "a@b.io" });
b = btnOf(t, "Получить код");
check(b && !b.props.disabled, "почта есть — можно просить код");
t = render(G.GuestClaim, { onClose() {}, onDone() {}, onLogin() {} }, { 0: "code", 2: "123" });
b = btnOf(t, "Подтвердить и скачать");
check(b && b.props.disabled, "код короче шести цифр — подтверждать рано");
check(walk(t).some(n => n.type && n.type.name === "Input" && n.props.autoComplete === "one-time-code"),
      "поле кода — one-time-code (телефон подставит из письма)");

console.log("=== 6. Формат выгрузки ===");
check(G.guestFormat({ media: {} }) === "original", "видео — субтитры .srt");
check(G.guestFormat({ importKind: "scan" }) === "pdf" && G.guestFormat({ importKind: "pdf" }) === "pdf", "PDF и скан — PDF как в оригинале");
check(G.guestFormat({ importKind: "docx", fileName: "a.docx" }) === "docx_layout", ".docx — 1в1");
check(G.guestFormat({ importKind: "xlsx", fileName: "a.xlsx", writeback: true }) === "original", "таблица — своим файлом");

console.log("=== 7. Загрузчик ===");
const ix = fs.readFileSync(path.join(ROOT, "frontend", "index.html"), "utf8");
const a = ix.indexOf('"js/guest.jsx"'), b2 = ix.indexOf('"js/app.jsx"');
check(a > 0 && a < b2, "guest.jsx грузится до app.jsx");

console.log(fail.length ? "ПРОВАЛЕНО: " + fail.length : "ВСЁ ПРОШЛО");
process.exit(fail.length ? 1 : 0);
