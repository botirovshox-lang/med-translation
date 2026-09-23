/* Знакомство и виджет поддержки: собираются ли они вообще.
 *
 * Сборки у фронтенда нет — `.jsx` грузятся тегами и выполняются как есть,
 * поэтому сломанный компонент виден только БЕЛЫМ ЭКРАНОМ у человека,
 * а `node --check` ловит один синтаксис. Этот тест выполняет файл
 * с заглушкой React (без Babel и npm) и смотрит, что собралось.
 *
 * Что сторожится и почему именно это:
 *   1. Тур показывается ТОЛЬКО когда сервер сказал «не пройдено».
 *      Заглушка `me` в app.jsx несёт tourDone: true намеренно — иначе
 *      затемнение на весь экран мигает человеку, который тур давно закрыл.
 *   2. «Прошёл» пишется НА ЗАПИСЬ (POST /api/profile), а не в localStorage:
 *      иначе тур встречал бы человека заново на каждом компьютере.
 *   3. Шаг без цели в DOM не рисует дыру в пустоте: подсказка встаёт
 *      по центру. Врать стрелкой, указывающей в никуда, хуже, чем
 *      не указывать вовсе.
 *   4. Виджет поддержки рисуется ВСЕГДА (он нужен на любом экране),
 *      закрытым, и не опрашивает сервер, пока нечего ждать.
 *   5. Цели тура ищутся по data-tour — метка есть в app.jsx на пунктах меню.
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

/* ---- Заглушка React: собираем дерево описаний, а не рисуем ---- */
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
  Fragment: "Fragment",
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
function useMemo(fn) { return fn(); }
function useCallback(fn) { return fn; }

/* Плоский обход дерева. Вложенные КОМПОНЕНТЫ раскрываются на месте:
   заглушка createElement их не зовёт, а спрашиваем мы про разметку,
   которую они рисуют (OnboardingLayer возвращает WelcomeTour
   и SupportWidget, и без раскрытия дерево пусто). Хуки у каждого свои —
   поэтому вложенный компонент получает свой набор. */
function walk(node, out) {
  out = out || [];
  if (!node || typeof node !== "object") return out;
  if (typeof node.type === "function") {
    const savedH = hooks, savedI = hookIx;
    hooks = node.__hooks || (node.__hooks = {}); hookIx = 0;
    let inner = null;
    try { inner = node.type(node.props); } catch (e) { /* пусть видно по пустому дереву */ }
    hooks = savedH; hookIx = savedI;
    out.push(node);
    return walk(inner, out);
  }
  out.push(node);
  (node.children || []).forEach(c => walk(c, out));
  return out;
}
function byClass(tree, cls) {
  return walk(tree).filter(n => n.props && typeof n.props.className === "string"
    && n.props.className.split(/\s+/).includes(cls));
}
function texts(tree) {
  return walk(tree).flatMap(n => (n.children || []).filter(c => typeof c === "string"));
}

/* ---- Окружение файла: всё, что он берёт из соседей ---- */
const calls = [];
const sandbox = {
  React, useState, useEffect, useRef, useMemo, useCallback,
  console, setTimeout, clearTimeout, cancelAnimationFrame: () => {},
  requestAnimationFrame: () => 1,
  TR: (s) => s,
  TRS: (s) => s,
  Icon: function Icon(p) { return React.createElement("icon", p); },
  IconBtn: function IconBtn(p) { return React.createElement("iconbtn", p); },
  Date,
  document: {
    hidden: false,
    querySelector: () => sandbox.__target,
    addEventListener() {}, removeEventListener() {},
  },
  window: {
    innerHeight: 900, innerWidth: 1400,
    addEventListener() {}, removeEventListener() {},
    API: {
      support: () => { calls.push("support"); return Promise.resolve({ ok: true, thread: { msgs: [], unread: 0 }, live: true }); },
      supportSend: (t) => { calls.push("send:" + t); return Promise.resolve({ ok: true, thread: { msgs: [] } }); },
      supportRead: () => { calls.push("read"); return Promise.resolve({ ok: true, thread: { msgs: [], unread: 0 } }); },
      profileSave: (b) => { calls.push("profileSave:" + JSON.stringify(b)); return Promise.resolve({ ok: true, me: {} }); },
    },
  },
  __target: null,
};
sandbox.globalThis = sandbox;

const src = fs.readFileSync(path.join(JS, "onboarding.jsx"), "utf8");
vm.createContext(sandbox);
/* `const` и `function` верхнего уровня НЕ становятся свойствами sandbox —
   они живут в области самого скрипта. В браузере это одна глобальная
   область (файлы грузятся тегами, см. CLAUDE.md), а здесь её надо
   воспроизвести: дописываем к файлу вынос имён наружу. */
const EXPORTS = ["SupportWidget", "WelcomeTour", "OnboardingLayer",
                 "TOUR_STEPS", "SUP_POLL_MS", "tourRect", "supTime"];
const tail = "\n" + EXPORTS.map(n =>
  `try { globalThis.${n} = ${n}; } catch (e) {}`).join("\n");
try {
  vm.runInContext(src + tail, sandbox, { filename: "onboarding.jsx" });
} catch (e) {
  console.log("  FAIL onboarding.jsx не выполнился: " + e.message);
  process.exit(1);
}

function render(Comp, props, target) {
  hooks = {}; hookIx = 0; effects = [];
  sandbox.__target = target || null;
  const tree = Comp(props);
  return tree;
}

const store = { me: null, setMe() {} };
const toast = { error() {}, success() {} };

console.log("=== 1. Файл собрался и объявил, что обещал ===");
for (const name of ["SupportWidget", "WelcomeTour", "OnboardingLayer", "TOUR_STEPS"]) {
  check(typeof sandbox[name] !== "undefined", "объявлен " + name);
}
check(Array.isArray(sandbox.TOUR_STEPS) && sandbox.TOUR_STEPS.length >= 3,
  "шагов знакомства 3–4 (" + (sandbox.TOUR_STEPS || []).length + ")");
check(sandbox.TOUR_STEPS.every(s => s.sel && s.title && s.text),
  "у каждого шага есть цель, заголовок и объяснение");

console.log("=== 2. Тур молчит, пока сервер не ответил ===");
/* me === null — ответ /auth/me ещё не пришёл. Показать тур здесь значит
   мигнуть затемнением человеку, который его уже закрывал. */
let tree = render(sandbox.OnboardingLayer, { store: { me: null }, toast });
check(byClass(tree, "tour").length === 0, "без ответа сервера знакомства нет");
check(byClass(tree, "sup").length === 1, "виджет поддержки при этом есть");

console.log("=== 3. Пройденное знакомство не показывается ===");
tree = render(sandbox.OnboardingLayer, { store: { me: { tourDone: true } }, toast });
check(byClass(tree, "tour").length === 0, "tourDone: true — тура нет");

console.log("=== 4. Новому человеку знакомство показывается ===");
tree = render(sandbox.OnboardingLayer, { store: { me: { tourDone: false } }, toast });
check(byClass(tree, "tour").length === 1, "tourDone: false — тур нарисован");
const tip = byClass(tree, "tour-tip")[0];
check(!!tip, "подсказка шага есть");
const tt = texts(tree).join(" ");
check(tt.includes(sandbox.TOUR_STEPS[0].title), "показан ПЕРВЫЙ шаг");
check(tt.includes("Пропустить"), "есть «Пропустить» — закрыть можно сразу");
check(tt.includes("Далее"), "есть «Далее»");

console.log("=== 5. Шаг без цели в DOM не рисует дыру в пустоте ===");
/* querySelector вернул null: пункта меню нет (роль не та, узкий экран). */
check(byClass(tree, "tour-ring").length === 0, "без цели подсветки нет");
check(byClass(tree, "tour-veil").length === 1, "затемнение при этом одно, на весь экран");
check(tip.props.style && tip.props.style.transform, "подсказка встаёт по центру");

console.log("=== 6. Цель найдена — подсветка по её рамке ===");
const rect = { top: 120, left: 40, width: 180, height: 36 };
tree = render(sandbox.OnboardingLayer, { store: { me: { tourDone: false } }, toast },
  { getBoundingClientRect: () => rect });
check(byClass(tree, "tour-ring").length === 1, "кольцо подсветки нарисовано");
check(byClass(tree, "tour-veil").length === 4,
  "затемнение — четыре куска вокруг цели (сама цель остаётся нажимаемой)");
const ring = byClass(tree, "tour-ring")[0];
check(ring.props.style.top === (rect.top - 6) + "px"
  && ring.props.style.left === (rect.left - 6) + "px",
  "кольцо стоит по рамке цели с запасом");

console.log("=== 7. «Прошёл» пишется НА ЗАПИСЬ, а не в localStorage ===");
calls.length = 0;
const skip = walk(tree).find(n => n.props && n.props.onClick
  && (n.children || []).includes("Пропустить"));
check(!!skip, "у «Пропустить» есть обработчик");
if (skip) skip.props.onClick();
check(calls.some(c => c.startsWith("profileSave:")), "закрытие тура шлёт POST /api/profile");
check(calls.some(c => c.includes('"tourDone":true')), "и шлёт ровно tourDone: true");
/* Комментарий про localStorage в файле ЕСТЬ и должен остаться — там
   объяснено, почему флаг живёт на записи. Сторожим ВЫЗОВ, а не слово. */
const codeOnly = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
check(!/localStorage\s*\./.test(codeOnly) && !/localStorage\s*\[/.test(codeOnly),
  "localStorage в знакомстве не ЧИТАЕТСЯ и не пишется (флаг живёт на записи)");

console.log("=== 8. Виджет поддержки: закрыт, но считает непрочитанное ===");
tree = render(sandbox.SupportWidget, { store, toast });
check(byClass(tree, "sup-fab").length === 1, "кнопка-значок нарисована");
check(byClass(tree, "sup-panel").length === 0, "панель закрыта по умолчанию");
const fab = byClass(tree, "sup-fab")[0];
check(fab.props["aria-label"], "у значка есть подпись для читалки");
check(fab.props["aria-expanded"] === false, "и объявлено, что он закрыт");

console.log("=== 9. Есть ответ — на значке горит счётчик ===");
hooks = {}; hookIx = 0; effects = [];
sandbox.__target = null;
hooks[1] = { unread: 3, msgs: [{ by: "support", text: "ответ", at: 0 }] };  // thread
tree = (function () { hookIx = 0; return sandbox.SupportWidget({ store, toast }); })();
const dot = byClass(tree, "sup-dot")[0];
check(!!dot, "счётчик непрочитанного нарисован");
check(dot && (dot.children || []).includes(3), "и показывает ЧИСЛО, а не точку");

console.log("=== 10. Открытый виджет: переписка и поле ввода ===");
hooks = { 0: true, 1: { unread: 0, msgs: [
  { by: "user", text: "не грузится PDF", at: 0 },
  { by: "support", text: "пришлите номер", at: 0 }] }, 2: "", 3: false, 4: true };
hookIx = 0; effects = [];
tree = sandbox.SupportWidget({ store, toast });
check(byClass(tree, "sup-panel").length === 1, "панель открыта");
check(byClass(tree, "sup-msg").length === 2, "оба сообщения нарисованы");
check(byClass(tree, "mine").length === 1 && byClass(tree, "theirs").length === 1,
  "своё и чужое различаются классом, а не только текстом");
check(walk(tree).some(n => n.type === "textarea"), "есть поле ввода");
check(walk(tree).some(n => n.type === "form"), "отправка формой — Enter работает сам");

console.log("=== 11. Метки целей тура есть в самом приложении ===");
const app = fs.readFileSync(path.join(JS, "app.jsx"), "utf8");
check(app.includes('"data-tour"'), "app.jsx проставляет data-tour на пунктах меню");
check(app.includes("OnboardingLayer"), "app.jsx рисует слой знакомства и поддержки");
/* Заглушка me обязана нести tourDone: true — см. пункт 2. */
check(/useState\(\{[^}]*tourDone:\s*true/.test(app),
  "заглушка me несёт tourDone: true (иначе тур мигает до ответа сервера)");
check(app.includes("me, setMe,"), "setMe отдан наружу: тур обновляет копию браузера");
const boot = fs.readFileSync(path.join(ROOT, "frontend", "index.html"), "utf8");
check(boot.includes("js/onboarding.jsx"), "загрузчик подключает onboarding.jsx");

console.log("=== 12. Вкладка «Обучение» ===");
/* Вкладка собирается тем же приёмом: выполняем файл с заглушкой React
   и смотрим, что нарисовалось. Содержание приходит с сервера, поэтому
   подсовываем ответ /api/tutorial и проверяем, что ВСЁ из него доехало
   до разметки — молча потерянный шаг иначе виден только глазами. */
const learnSrc = fs.readFileSync(path.join(JS, "tab_learn.jsx"), "utf8");
const CONTENT = {
  ok: true, lang: "ru", h1: "Обучение", lede: "Весь путь…",
  facts: ["Пять шагов", "Без настройки"],
  stepWord: "Шаг",
  steps: [
    { key: "upload", title: "Принесите файл", paras: ["Вкладка <b>Проекты</b>."],
      svg: '<figure class="shot-wrap"><svg class="shot"></svg></figure>' },
    { key: "run", title: "Нажмите одну кнопку", paras: ["Большая кнопка внизу."], svg: "" },
  ],
  faqHead: "Частые вопросы",
  faq: [{ q: "Какие форматы?", a: "Word, PDF, Excel." }],
  actions: { tour: "Показать знакомство заново", tourNote: "Тур по интерфейсу.",
             support: "Написать в поддержку", supportNote: "Мы читаем всё.",
             print: "Открыть отдельной страницей", printNote: "Для печати." },
};
const fired = [];
sandbox.Expander = function Expander(p) {
  return React.createElement("div", { className: "expander" },
    React.createElement("button", { className: "expander-head" }, p.title), p.children);
};
sandbox.window.API.tutorial = () => Promise.resolve(CONTENT);
sandbox.window.dispatchEvent = (e) => { fired.push(e && e.type); return true; };
sandbox.Event = function (t) { this.type = t; };
vm.runInContext(learnSrc + "\ntry { globalThis.TabLearn = TabLearn; } catch (e) {}",
  sandbox, { filename: "tab_learn.jsx" });
check(typeof sandbox.TabLearn === "function", "tab_learn.jsx собрался и объявил TabLearn");

/* Первый кадр — до ответа сервера: «Загружаем…», а не пустота. */
hooks = {}; hookIx = 0; effects = [];
let ltree = sandbox.TabLearn({ store, toast });
check(texts(ltree).join(" ").includes("Загружаем"), "пока грузится — говорит об этом");

/* Ответ пришёл: hooks[0] — data, hooks[1] — failed. */
hooks = { 0: CONTENT, 1: false }; hookIx = 0; effects = [];
ltree = sandbox.TabLearn({ store, toast });
const ltxt = texts(ltree).join(" ");
check(ltxt.includes("Обучение"), "заголовок — с сервера, а не из кода вкладки");
check(byClass(ltree, "learn-step").length === CONTENT.steps.length,
  "нарисованы ВСЕ шаги ответа (" + CONTENT.steps.length + ")");
check(byClass(ltree, "learn-facts").length === 1, "короткие факты показаны");
check(byClass(ltree, "learn-act").length === 3, "три действия: тур, поддержка, печать");
check(byClass(ltree, "learn-shot").length === 1,
  "рисунок вставлен только там, где он есть (шаг без svg его не рисует)");
const shot = byClass(ltree, "learn-shot")[0];
check(shot && shot.props.dangerouslySetInnerHTML
  && shot.props.dangerouslySetInnerHTML.__html.includes("<svg"),
  "SVG уходит в разметку как есть — второго рисовальщика в браузере нет");
check(byClass(ltree, "expander").length === CONTENT.faq.length,
  "частые вопросы — общей раскрывашкой Expander, а не своей копией");
check(ltxt.includes("Частые вопросы"), "заголовок раздела вопросов с сервера");

/* Кнопки шлют СОБЫТИЯ: виджет поддержки и тур слушают их сами. */
const acts = byClass(ltree, "learn-act").filter(n => n.type === "button");
check(acts.length === 2, "тур и поддержка — кнопки, а печатная версия — ссылка");
fired.length = 0;
acts.forEach(b => b.props.onClick());
check(fired.includes("mct-tour-open"), "кнопка тура шлёт mct-tour-open");
check(fired.includes("mct-support-open"), "кнопка поддержки шлёт mct-support-open");
const link = byClass(ltree, "learn-act").find(n => n.type === "a");
check(link && link.props.href === "/tutorial", "печатная версия ведёт на /tutorial");
check(link && link.props.rel === "noopener", "внешняя ссылка с rel=noopener");

/* Сервер не ответил — говорим об этом, а не показываем пустой экран. */
hooks = { 0: null, 1: true }; hookIx = 0; effects = [];
ltree = sandbox.TabLearn({ store, toast });
check(texts(ltree).join(" ").includes("Не удалось"), "сбой назван словами");
check(byClass(ltree, "learn-step").length === 0, "и шагов при этом нет");

/* Пункт меню и загрузчик. */
check(/key:\s*"learn"/.test(app), "пункт «Обучение» есть в TABS");
check(/learn:\s*TabLearn/.test(app), "вкладка привязана к компоненту");
check(boot.includes("js/tab_learn.jsx"), "загрузчик подключает tab_learn.jsx");
/* Тур обязан уметь показаться ПО ПРОСЬБЕ — иначе кнопка ничего не делает. */
check(src.includes("mct-tour-open"), "знакомство слушает просьбу показаться заново");
check(src.includes("mct-support-open"), "виджет поддержки слушает просьбу открыться");

if (fail.length) {
  console.log("\nПРОВАЛЕНО: " + fail.length);
  fail.forEach(f => console.log("  - " + f));
  process.exit(1);
}
console.log("\nВСЁ ПРОШЛО");
