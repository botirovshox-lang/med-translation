/* Экран «Экспорт»: рендер без браузера.
 *
 * Тот же приём, что и в test_editor_render.js: фронтенд собирается в браузере
 * (UMD + Babel standalone), поэтому сломанный компонент виден только там —
 * белым экраном. Файлы написаны на React.createElement, значит их можно
 * выполнить с заглушкой React и посмотреть, что собралось.
 *
 * Проверяется то, что легко потерять молча:
 *   1. формат «1в1» есть в списке и не подписан обещанием, которого не будет;
 *   2. обычный DOCX больше не обещает «сохраняет форматирование» — он
 *      собирается с нуля и оформления исходника не переносит;
 *   3. без приложенного исходника экран говорит об этом и даёт кнопку,
 *      а не прячет формат: пропавшее с экрана выглядит благополучнее, чем есть;
 *   4. с приложенным исходником видно, ЧТО приложено и сколько сегментов
 *      с ним связано — иначе «1в1» неотличим от неработающей кнопки;
 *   5. экран не обещает, что выгружаются ТОЛЬКО подтверждённые сегменты:
 *      условие ровно одно — непустой перевод, а статус роли не играет;
 *   6. с приложенным исходником формат по умолчанию — 1в1, и кнопка
 *      скачивания называет его. Оставленный на «новом файле» переключатель
 *      молча собирал документ с нуля: человек прикладывал исходник и получал
 *      голый текст, а понять это можно было, только открыв файл.
 *
 * Запуск: node tests/test_export_render.js
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
  useEffect() {},
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
global.API = { safeCall: async (fn) => fn() };

const root = process.argv[2] || "frontend/js";
for (const f of ["ui.jsx", "data.js", "tab_export_preflight.jsx"]) {
  (0, eval)(fs.readFileSync(path.join(root, f), "utf8") + "\n//# sourceURL=" + f);
}

const toast = { info() {}, warning() {}, error() {}, success() {} };

function render(sourceDocx) {
  hooks.length = 0;
  hookIdx = 0;
  const project = {
    id: 1, title: "Тест", src: "RU", tgt: "EN", domain: "medical",
    // Нарочно вперемешку: подтверждённый, машинный и вовсе непереведённый.
    // В файл идут первые два, и экран обязан называть именно это число.
    segments: [
      { id: 1, source: "жалобы", target: "complaints", status: "confirmed", risk: "low" },
      { id: 2, source: "кашель", target: "cough", status: "translated", risk: "low" },
      { id: 3, source: "одышка", target: "", status: "new", risk: "low" },
    ],
  };
  if (sourceDocx) project.sourceDocx = sourceDocx;
  const storeStub = {
    activeProject: project, projects: [project], exportHistory: [],
    statusCounts: () => ({ all: 3, new: 1, translated: 1, qa: 0, confirmed: 1, failed: 0, review: 0 }),
    patchProject() {}, go() {},
  };
  const tree = React.createElement(TabExport, { store: storeStub, toast });
  const out = [];
  (function walk(node) {
    if (node === null || node === undefined) return;
    if (typeof node === "string") { if (node.trim()) out.push(node.trim()); return; }
    if (typeof node === "number") { out.push(String(node)); return; }
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node !== "object") return;
    (node.children || []).forEach(walk);
  })(tree);
  return out.join(" | ");
}

// ── без исходника ───────────────────────────────────────────────────
const bare = render(null);
check(bare.indexOf("DOCX 1в1") !== -1, "формат «1в1» есть в списке и без исходника");
check(bare.indexOf("приложите его ниже") !== -1,
      "сказано, почему 1в1 сейчас не соберётся");
check(bare.indexOf("Приложить исходник") !== -1, "есть кнопка приложить файл");
check(bare.indexOf("Оформление исходника не переносится") !== -1,
      "обычный DOCX больше не обещает сохранить форматирование");
check(bare.indexOf("сохраняет форматирование") === -1,
      "прежнее обещание убрано насовсем");
check(bare.indexOf("переводы, проверки и статусы не изменятся") !== -1,
      "сказано, что привязка файла не трогает перевод");

// ── что именно попадёт в файл ───────────────────────────────────────
// Прежняя подпись обещала «из подтверждённых сегментов» — неправда для обоих
// форматов: условие ровно одно, непустой перевод. Рядом с «Подтверждено: 1»
// такая подпись читалась как условие экспорта.
check(bare.indexOf("подтверждённых сегментов") === -1,
      "экран не обещает выгрузку только подтверждённых");
check(bare.indexOf("независимо от статуса") !== -1,
      "сказано, что статус на попадание в файл не влияет");
check(bare.indexOf("Пойдёт в файл") !== -1, "названо число сегментов с переводом");
check(bare.indexOf("Останется на языке оригинала") !== -1,
      "непереведённые названы отдельно, а не растворились в общем счёте");

// ── с исходником ────────────────────────────────────────────────────
const withSrc = render({ file: "фтизиатрия.docx", at: "2026-08-24 15:00",
                         paras: 3346, segments: 2670 });
check(withSrc.indexOf("фтизиатрия.docx") !== -1, "видно, какой файл приложен");
check(withSrc.indexOf("3346") !== -1 && withSrc.indexOf("2670") !== -1,
      "видно, сколько абзацев и сколько сегментов с ними связано");
check(withSrc.indexOf("выделения внутри абзаца на месте") !== -1,
      "формат 1в1 подписан тем, что он на самом деле делает");
check(withSrc.indexOf("Заменить") !== -1, "исходник можно заменить");
check(withSrc.indexOf("Скачать DOCX 1в1") !== -1,
      "с исходником формат по умолчанию 1в1, и кнопка его называет");
check(bare.indexOf("Скачать DOCX") !== -1 && bare.indexOf("Скачать DOCX 1в1") === -1,
      "без исходника по умолчанию обычный DOCX — 1в1 собрать не из чего");

console.log("\n" + (fail.length ? "ПРОВАЛЕНО: " + fail.join("; ") : "ВСЁ ПРОШЛО"));
process.exit(fail.length ? 1 : 0);
