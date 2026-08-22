/* Карточка составного прогона: рендер без браузера.
 *
 * Фронтенд собирается в браузере (UMD + Babel standalone), поэтому сломанный
 * компонент виден только там — белым экраном. node --check ловит лишь синтаксис,
 * а обращение к несуществующей переменной, к полю undefined или к пропу,
 * который больше не передают, проходит мимо него.
 *
 * Babel и React сюда не ставим: файлы написаны на React.createElement, значит
 * их можно выполнить с заглушкой React и посмотреть, что собралось. Заодно
 * проверяется главный инвариант таблицы: состав «отдельного» запуска шага
 * по умолчанию совпадает с составом общего прогона. Разойдись они — под
 * соседними кнопками стояли бы противоречащие друг другу числа.
 *
 * Запуск: node tests/test_editor_render.js
 */
const fs = require("fs");
const path = require("path");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

const hooks = [];
const effects = [];
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
      // Дочерние компоненты вызываем по-настоящему: половина ошибок именно там.
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
  useContext(c) { return { info() {}, warning() {}, error() {}, success() {} }; },
};
const { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } = React;

const store = {
  memory: {},
  getItem(k) { return this.memory[k] || null; },
  setItem(k, v) { this.memory[k] = String(v); },
  removeItem(k) { delete this.memory[k]; },
};
global.React = React;
global.useState = useState; global.useEffect = useEffect;
global.useRef = useRef; global.useMemo = useMemo; global.useCallback = useCallback;
global.createContext = createContext; global.useContext = useContext;
global.localStorage = store;
global.sessionStorage = store;
global.window = global;
global.document = { addEventListener() {}, removeEventListener() {}, querySelector() { return null; } };
// Разбор прогона приходит с сервера — подсовываем ответ той же формы.
function planStep(step, label, model, ids, runs, skips, note) {
  return { step, label, model, modelLabel: model, ids, count: ids.length,
           runs: runs || [], skips: skips || [], note: note || null };
}
global.API = {
  safeCall: async (fn) => fn(),
  runPlan: async () => ({
    steps: [
      planStep("translate", "перевод", "GPT-5.5", [6], [{ reason: "ещё не переведён", count: 1 }], [{ reason: "уже переведён", count: 6 }]),
      planStep("backcheck", "back-check", "GPT-5.6 Luna", [1, 2, 3, 5, 6, 7], [{ reason: "ещё не проверялся", count: 5 }, { reason: "появится после перевода", count: 1 }], [{ reason: "уже проверен этим переводом: GPT-5.6 Luna", count: 1 }]),
      planStep("termcheck", "проверка терминов", "GPT-5.6 Terra", [1, 3, 4, 5, 6], [{ reason: "ещё не проверялся", count: 4 }, { reason: "прошлая проверка слабее выбранной: GPT-5.6 Luna", count: 1 }], [{ reason: "уже проверен моделью не слабее: GPT-5.6 Sol", count: 2 }]),
      planStep("repair", "ремонт", "GPT-5.6 Terra", [3], [{ reason: "есть находки", count: 1 }], [{ reason: "чинить нечего — находок нет", count: 5 }, { reason: "этот же текст уже чинили", count: 1 }], "Считано по нынешним находкам. Проверки в этом же прогоне могут добавить ещё."),
      planStep("medical_qa", "Medical QA", "GPT-5.6 Luna", [1, 2, 3, 4, 5, 6, 7], [{ reason: "нет свежего результата", count: 7 }], [], "Считано по нынешнему тексту."),
    ],
    ids: [1, 2, 3, 4, 5, 6, 7], total: 7, scope: 7,
  }),
  models: async () => ({
    models: [
      { id: "gpt-5.6-sol", label: "GPT-5.6 Sol", in: 5, out: 30, api: "modern", rank: 6 },
      { id: "gpt-5.6-terra", label: "GPT-5.6 Terra", in: 2, out: 12, api: "modern", rank: 5 },
      { id: "gpt-5.6-luna", label: "GPT-5.6 Luna", in: 0.2, out: 1.2, api: "modern", rank: 4 },
      { id: "gpt-5.5", label: "GPT-5.5", in: 5, out: 30, api: "modern", rank: 5 },
      { id: "gpt-4o", label: "GPT-4o", in: 2.5, out: 10, api: "classic", rank: 2 },
    ],
    default: "gpt-4o", backcheckDefault: "gpt-5.6-luna", termcheckDefault: "gpt-5.6-terra",
    repairDefault: "gpt-5.6-terra", judgeDefault: "gpt-5.6-terra", judgeZone: [50, 97],
    domains: [{ id: "medical", label: "Медицина" }], domainDefault: "medical",
    backcheckBands: [], available: true,
  }),
  glossaryImpact: async () => ({ ok: true, terms: [], segments: [], pending: [], confirmed: [] }),
  autoApprovePreview: async () => null,
  listJobs: async () => ({ jobs: [] }),
};

const root = process.argv[2] || "frontend/js";
for (const f of ["ui.jsx", "data.js", "tab_editor_detail.jsx", "tab_editor.jsx"]) {
  const code = fs.readFileSync(path.join(root, f), "utf8");
  // Файлы грузятся тегами <script> — то есть в одну общую область видимости.
  (0, eval)(code + "\n//# sourceURL=" + f);
}

// Панель сегмента к делу не относится и требует своих данных — глушим её,
// чтобы проверять именно карточку прогона.
global.SegDetail = () => null;

// ── Проект, похожий на боевой: разные состояния проверок ──
const seg = (id, extra) => Object.assign({
  id, source: "жалобы на кашель " + id, target: "complaints of cough " + id,
  status: "translated", risk: "medium", provider: "gpt-5.5",
}, extra || {});
const project = {
  id: 1, title: "Тест", src: "RU", tgt: "EN", domain: "medical",
  segments: [
    seg(1),
    seg(2, { termcheck: { model: "gpt-5.6-sol", findings: [], stale: false } }),
    seg(3, { termcheck: { model: "gpt-5.6-luna", findings: [{ severity: "major", tgt_term: "x" }], stale: false } }),
    seg(4, { backcheck: { model: "gpt-5.6-luna", score: 91, stale: false, back: "жалобы", reasons: [], terms_lost: [] } }),
    seg(5, { status: "confirmed", confirmedBy: "human" }),
    seg(6, { status: "new", target: "" }),
    seg(7, { repair: { applied: true, tried: true }, backcheck: { model: "gpt-5.6-luna", score: 60, stale: false, reasons: ["расхождение чисел"], terms_lost: [] } }),
  ],
};
const storeStub = {
  activeProject: project,
  segmentFilter: null,
  statusCounts: () => ({ all: 7, new: 1, translated: 4, qa: 0, confirmed: 1, failed: 0, review: 1 }),
  setSegmentFilter() {}, gotoSegId: null, refreshProject() {}, projects: [project],
};
const toast = { info() {}, warning() {}, error() {}, success() {} };

// ── Считаем строки таблицы так же, как компонент, и рисуем карточку ──
function walk(node, depth, out) {
  if (node === null || node === undefined || typeof node !== "object") {
    if (typeof node === "number") out.push("  ".repeat(depth) + "#" + node);
    else if (typeof node === "string" && node.trim()) out.push("  ".repeat(depth) + node.trim().slice(0, 110));
    return;
  }
  if (Array.isArray(node)) { node.forEach(n => walk(n, depth, out)); return; }
  const tag = typeof node.type === "string" ? node.type : "?";
  const cls = node.props && node.props.className ? "." + node.props.className : "";
  if (["div", "span", "b", "button", "select", "option", "label", "input"].indexOf(tag) === -1) return;
  if (tag === "option") return;
  out.push("  ".repeat(depth) + "<" + tag + cls + ">");
  (node.children || []).forEach(c => walk(c, depth + 1, out));
}

(async () => {
try {
  hookIdx = 0;
  TabEditor({ store: storeStub, toast });          // первый проход: собираем эффекты
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
  hookIdx = 0; effects.length = 0;
  const el = TabEditor({ store: storeStub, toast });   // второй: уже с разбором
  const out = [];
  walk(el, 0, out);
  const text = out.join("\n");
  check(out.length > 100, "вкладка редактора отрисовалась (" + out.length + " узлов)");

  console.log("\n=== 1. Таблица шагов на месте ===");
  for (const m of ["Перевести и проверить", "Шаг", "Модель", "Сегм.", "≈ цена"])
    check(text.indexOf(m) !== -1, "колонка/заголовок: " + m);
  for (const m of ["Перевод", "Back-check", "Термины", "Ремонт", "Medical QA"])
    check(text.indexOf(m) !== -1, "строка шага: " + m);
  check(text.indexOf("Ориентировочно") !== -1, "общая смета под таблицей");
  check(text.indexOf("от back-check") !== -1,
        "у Medical QA вместо выбора модели написано, чью она берёт");

  console.log("\n=== 2. Настройки шагов переехали в таблицу ===");
  check(text.indexOf("Отдельные прогоны") === -1,
        "свёрнутого блока «Отдельные прогоны» больше нет — искать галочки негде");

  // ── Раскрываем строку так, как это сделал бы человек: жмём шеврон ──
  const found = [];
  (function find(n) {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(find);
    const p = n.props || {};
    if (p.onClick && /Подробнее/.test(p["aria-label"] || "")) found.push(p.onClick);
    (n.children || []).forEach(find);
  })(el);
  check(found.length === 5, "у каждого шага есть раскрытие (" + found.length + " из 5)");

  console.log("\n=== 3. Раскрытая строка объясняет состав и даёт запуск ===");
  found[2]();                                    // третья строка — «Термины»
  hookIdx = 0;
  const out2 = [];
  walk(TabEditor({ store: storeStub, toast }), 0, out2);
  const t2 = out2.join("\n");
  check(/в общий прогон:.*ещё не проверялся/.test(t2), "названо, кого шаг возьмёт");
  check(/пропустит:.*не слабее: GPT-5\.6 Sol/.test(t2), "и почему пропустит остальных");
  check(t2.indexOf("Что проверять отдельным прогоном:") !== -1, "группы для точечного запуска на месте");
  check(t2.indexOf("Запустить только этот шаг") !== -1, "и кнопка запуска только этого шага");

  console.log("\n=== 4. Главный инвариант: два числа под соседними кнопками сходятся ===");
  // Общий прогон берёт 5 сегментов (разбор сервера), и отдельный запуск по
  // умолчанию обязан взять столько же: галочки групп выставлены по тому же
  // правилу рангов. Разойдись они — человек снова гадал бы, какому числу верить.
  const solo = /Запустить: (\d+) сегм\./.exec(t2);
  check(!!solo, "у кнопки отдельного запуска написано количество");
  check(solo && Number(solo[1]) === 5,
        "отдельный запуск по умолчанию = состав общего прогона (" +
        (solo ? solo[1] : "?") + " против 5)");
  check(t2.indexOf("проверено, замечаний нет: GPT-5.6 Sol") !== -1,
        "группа с вердиктом сильной модели показана");

  console.log("\n=== 5. Проверка моделью-автором — не проверка: группа self ===");
  // Сервер (_backcheck_cached) не зачитывает back-check, сделанный моделью,
  // которая сама и переводила: она возвращает свой замысел. Общий прогон
  // берёт такой сегмент заново — значит и отдельный запуск по умолчанию
  // обязан его включать, иначе составы под соседними кнопками разойдутся.
  project.segments[3].backcheck.model = "gpt-5.5";   // provider у сегмента тоже gpt-5.5
  hookIdx = 0;
  const el3 = TabEditor({ store: storeStub, toast });
  const clicks = [];
  (function find(n) {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(find);
    const p = n.props || {};
    if (p.onClick && /Подробнее/.test(p["aria-label"] || "")) clicks.push(p.onClick);
    (n.children || []).forEach(find);
  })(el3);
  clicks[1]();                                   // вторая строка — «Back-check»
  hookIdx = 0;
  const out3 = [];
  walk(TabEditor({ store: storeStub, toast }), 0, out3);
  const t3 = out3.join("\n");
  check(t3.indexOf("проверял тот, кто переводил — это не проверка") !== -1,
        "группа self названа человеку по имени");
  const solo3 = /Запустить: (\d+) сегм\./.exec(t3);
  check(solo3 && Number(solo3[1]) === 5,
        "сегмент с self-проверкой входит в отдельный запуск по умолчанию (" +
        (solo3 ? solo3[1] : "?") + " против 5)");

  console.log("\n" + (fail.length ? "ПРОВАЛЕНО: " + fail.join("; ") : "ВСЁ ПРОШЛО"));
  process.exit(fail.length ? 1 : 0);
} catch (e) {
  console.log("РЕНДЕР УПАЛ:", e && e.message);
  console.log((e && e.stack || "").split("\n").slice(0, 8).join("\n"));
  process.exit(1);
}
})();
