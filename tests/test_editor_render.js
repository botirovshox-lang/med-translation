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
/* Сторож хуков. Сборки у фронтенда нет: .jsx грузятся как есть, а хуки
   раздаёт одна строка деструктуризации в ui.jsx. Забытый там хук — это
   ReferenceError при первом рендере, то есть БЕЛЫЙ ЭКРАН, и ни один тест
   этого не видит: каждый объявляет свои заглушки хуков сам (ниже — тоже).
   Так и уехал useMemo. Поэтому сверяем ИСХОДНИКИ: всякий хук, которым
   пользуются .jsx, обязан стоять в той строке. */
function checkHookExports(fs, path, root, report) {
  const ui = fs.readFileSync(path.join(root, "ui.jsx"), "utf8");
  const m = ui.match(/const\s*\{([^}]*)\}\s*=\s*React;/);
  const declared = new Set((m ? m[1] : "").split(",").map(s => s.trim()).filter(Boolean));
  const used = new Set();
  for (const f of fs.readdirSync(root)) {
    if (!f.endsWith(".jsx")) continue;
    const code = fs.readFileSync(path.join(root, f), "utf8");
    // Голый вызов хука: «useMemo(» без «React.» перед ним.
    for (const hit of code.matchAll(/(^|[^.\w])(use[A-Z]\w*)\s*\(/g)) {
      const name = hit[2];
      // Свои хуки компонентов (useStore, useTheme, useToast) объявлены
      // в самих файлах — сторожим только реактовские.
      if (["useState", "useEffect", "useRef", "useMemo", "useCallback",
           "useContext", "useReducer", "useLayoutEffect"].includes(name)) used.add(name);
    }
  }
  const missing = [...used].filter(h => !declared.has(h));
  report(missing.length === 0,
         "все реактовские хуки объявлены в ui.jsx" +
         (missing.length ? " — НЕ объявлены: " + missing.join(", ") : ""));
}

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
  useRef(v) {
    // Ref обязан пережить рендер: на нём держится флажок перехода к сегменту —
    // ровно то место, где ошибка не видна ни глазами, ни node --check.
    const i = hookIdx++;
    if (!(i in hooks)) hooks[i] = { current: v === undefined ? null : v };
    return hooks[i];
  },
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
    languages: [{ code: "RU", ru: "Русский", native: "Русский" }, { code: "EN", ru: "Английский", native: "English" }],
    backcheckBands: [], available: true,
  }),
  glossaryImpact: async () => ({ ok: true, terms: [], segments: [], pending: [], confirmed: [] }),
  autoApprovePreview: async () => null,
  listJobs: async () => ({ jobs: [] }),
};

const root = process.argv[2] || "frontend/js";
console.log("=== 0. Хуки, которыми пользуются .jsx, объявлены в ui.jsx ===");
checkHookExports(fs, path, root, check);

/* Сторож коллизий имён. Все .jsx грузятся тегами <script> в ОДНУ глобальную
   область, и функция верхнего уровня из позднего файла молча перезаписывает
   одноимённую из раннего. Так SegRow из tab_preflight.jsx затёр SegRow
   редактора — и таблица сегментов рисовала строки «0» без текста, при
   исправных данных и фильтре. Ни один рендер-тест этого не видел: каждый
   грузит только свои файлы, вместе их не грузит никто. */
console.log("=== 0a. Флагов стран в исходниках нет ===");
/* Флаг — это страна, а не язык: английский не 🇬🇧, у арабского двадцать
   стран. Пара проекта теперь любая, и языки приходят с сервера кодами;
   эмодзи-флаг в .jsx — это возврат к пяти зашитым языкам. */
{
  const flagRe = /[\u{1F1E6}-\u{1F1FF}]{2}/u;
  const withFlags = fs.readdirSync(root).filter(f => f.endsWith(".jsx")
    && flagRe.test(fs.readFileSync(path.join(root, f), "utf8")));
  check(withFlags.length === 0, "эмодзи-флагов нет" + (withFlags.length ? ": " + withFlags.join(", ") : ""));
}

console.log("=== 0b. Имена верхнего уровня не совпадают между .jsx ===");
{
  const decl = {};
  for (const f of fs.readdirSync(root)) {
    if (!f.endsWith(".jsx")) continue;
    const code = fs.readFileSync(path.join(root, f), "utf8");
    for (const m of code.matchAll(/^(?:function\s+([A-Za-z_]\w*)|const\s+([A-Za-z_]\w*)\s*=)/gm)) {
      const name = m[1] || m[2];
      (decl[name] = decl[name] || new Set()).add(f);
    }
  }
  const dupes = Object.entries(decl).filter(([, files]) => files.size > 1);
  check(dupes.length === 0,
        "коллизий нет" + (dupes.length
          ? " — ЕСТЬ: " + dupes.map(([n, fl]) => n + " (" + [...fl].join(", ") + ")").join("; ")
          : ""));
}

for (const f of ["ui.jsx", "tab_editor_detail.jsx", "tab_editor.jsx"]) {
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

// Прогон, запущенный из этой же вкладки, оставляет в localStorage состав шагов:
// сколько сегментов разбор отвёл каждому. Во время прогона разбор больше не
// считается, и без этого снимка «осталось» взять неоткуда.
// Опознаётся снимок по тройке «номер + проект + время создания»: номера задач
// живут в памяти сервера и после его рестарта начинаются с единицы заново.
store.setItem("mcat_run_snapshot", JSON.stringify({
  jobId: 77, project: 1, created: "2026-08-23 10:00:00",
  steps: { translate: 6, backcheck: 20, termcheck: 15 } }));

// Идущий прогон подсовываем опросу задач: полоса собирается из его счётчиков.
function activeFullJob(id, counters, extra) {
  return { active: [Object.assign(
    { id: id, kind: "full", project: 1, created: "2026-08-23 10:00:00",
      status: "running", done: 25, total: 100,
      counters: counters, recent: [],
      params: { steps: ["translate", "backcheck", "termcheck"] } }, extra || {})], jobs: [] };
}

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
  // Шагов шесть: перевод, back-check, термины, СВЕРКА терминов моделью,
  // ремонт, Medical QA. Сверка добавлена как языконезависимая проверка —
  // морфология знает один язык и знает его грубо.
  check(found.length === 6, "у каждого шага есть раскрытие (" + found.length + " из 6)");

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

  console.log("\n=== 6. Ремонт: разрешение трогать заверенное человеком ===");
  // Галочка живёт в раскрытой строке ремонта. Проверяем, что строка вообще
  // собирается: сломанный компонент виден только белым экраном в браузере.
  hookIdx = 0;
  const el4 = TabEditor({ store: storeStub, toast });
  const clicks4 = [];
  (function find(n) {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(find);
    const p = n.props || {};
    if (p.onClick && /Подробнее/.test(p["aria-label"] || "")) clicks4.push(p.onClick);
    (n.children || []).forEach(find);
  })(el4);
  // Индекс 3, а не 4: у раскрытой строки (после шага 5 это back-check) шеврон
  // подписан «Свернуть» и в этот список не попадает. Считать надо от списка
  // шагов: перевод, back-check(раскрыт), термины, СВЕРКА терминов, ремонт,
  // Medical QA — значит ремонт третий среди оставшихся. Что открылась именно
  // нужная строка, проверяет её собственный маркер «Что чинить» ниже.
  clicks4[3]();
  hookIdx = 0;
  const out4 = [];
  const el4b = TabEditor({ store: storeStub, toast });
  walk(el4b, 0, out4);
  const t4 = out4.join("\n");
  check(t4.indexOf("Чинить подтверждённые человеком") !== -1,
        "переключатель «чинить подтверждённые» на месте");
  check(t4.indexOf("в выборке нет заверенных сегментов с находками") !== -1,
        "и рядом сказано, сколько заверенного ждёт починки");
  check(t4.indexOf("Что чинить — отметьте") !== -1,
        "прежние группы ремонта никуда не делись");

  // Взведённое разрешение обязано быть видно У ГЛАВНОЙ КНОПКИ. Переключатель
  // живёт в раскрытой строке ремонта — строку сворачивают, а кнопка остаётся
  // и всё так же снимает отметки «подтвердил человек».
  let armSwitch = null;
  (function findSw(n) {
    if (!n || typeof n !== "object" || armSwitch) return;
    if (Array.isArray(n)) return n.forEach(findSw);
    const p = n.props || {};
    if (p.onClick && p["aria-label"] === "Чинить подтверждённые") { armSwitch = p.onClick; return; }
    (n.children || []).forEach(findSw);
  })(el4b);
  check(!!armSwitch, "переключатель кликабелен");
  if (armSwitch) armSwitch();
  hookIdx = 0;
  const out6 = [];
  walk(TabEditor({ store: storeStub, toast }), 0, out6);
  const t6 = out6.join("\n");
  check(t6.indexOf("Ремонт возьмёт и подтверждённые") !== -1,
        "взведённое разрешение названо у кнопки «Перевести и проверить»");
  check(t6.indexOf("снимется отметка «подтвердил человек»") !== -1,
        "и сказано, что именно произойдёт");
  if (armSwitch) armSwitch();          // возвращаем как было: дальше идут другие проверки
  hookIdx = 0;
  const out6b = [];
  walk(TabEditor({ store: storeStub, toast }), 0, out6b);
  check(out6b.join("\n").indexOf("Ремонт возьмёт и подтверждённые") === -1,
        "выключили — предупреждение ушло");

  console.log("\n=== 7. Полоса прогона: залипает наверху и говорит, где мы ===");
  // Счётчики задачи приходят порциями и говорят, сколько шаг УЖЕ прошёл.
  // Перевод свои 6 добрал — ему галочка; back-check сделал 12 из 20; термины
  // не начинались. Всё это должно читаться, не листая страницу.
  global.API.listJobs = async () => activeFullJob(77, { translate: 6, backcheck: 12 });
  hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
  hookIdx = 0;
  const el7 = TabEditor({ store: storeStub, toast });
  const out7 = [];
  walk(el7, 0, out7);
  const t7 = out7.join("\n");
  check(t7.indexOf("<div.run-strip>") !== -1, "полоса прогона отрисовалась");
  check(/Перевод и проверка — идёт на сервере/.test(t7), "названо, что именно идёт");
  check(t7.indexOf("25 из 100") !== -1, "общий счёт на месте");
  check(t7.indexOf("<span.run-step ok>") !== -1, "закрытый шаг отмечен галочкой");
  check(t7.indexOf("осталось 8") !== -1, "у незакрытого шага показан остаток");
  check(t7.indexOf("осталось 15") !== -1, "и у того, который ещё не начинался");
  check(t7.indexOf("Остановить") !== -1, "остановка — там же, на полосе");

  // Полоса обязана жить ВНУТРИ залипающей панели: таблица длинная, и уехавшая
  // за верхний край полоса — это прогон, который не видно и нечем остановить.
  const findCls = (n, cls) => {
    if (!n || typeof n !== "object") return null;
    if (Array.isArray(n)) { for (const c of n) { const r = findCls(c, cls); if (r) return r; } return null; }
    if ((n.props || {}).className === cls) return n;
    for (const c of (n.children || [])) { const r = findCls(c, cls); if (r) return r; }
    return null;
  };
  const sticky = findCls(el7, "editor-toolbar");
  const inSticky = [];
  if (sticky) walk(sticky, 0, inSticky);
  check(inSticky.join("\n").indexOf("<div.run-strip>") !== -1,
        "полоса стоит внутри залипающей панели, а не в потоке страницы");

  console.log("\n=== 8. Чужой прогон: остаток не выдумываем ===");
  // Прогон запущен из другого браузера — состава шагов у нас нет. Показываем
  // только сделанное: придуманное «осталось» и есть то враньё, ради которого
  // состав вообще считает сервер.
  global.API.listJobs = async () => activeFullJob(88, { translate: 4 });
  hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
  hookIdx = 0;
  const out8 = [];
  walk(TabEditor({ store: storeStub, toast }), 0, out8);
  const t8 = out8.join("\n");
  check(t8.indexOf("<div.run-strip>") !== -1, "полоса всё равно на месте");
  check(t8.indexOf("осталось") === -1, "остаток по шагам не придуман");
  check(t8.indexOf("прогон запущен не из этой вкладки") !== -1, "и сказано, почему его нет");
  check(t8.indexOf("<span.run-step ok>") === -1, "галочку без состава тоже не ставим");

  console.log("\n=== 9. Тот же номер после рестарта сервера — не тот же прогон ===");
  // Номера задач живут в памяти процесса и после рестарта начинаются с единицы
  // заново, поэтому снимок опознаётся ещё и по проекту со временем создания.
  // Совпал номер, но не время — состав чужой, и остаток показывать нельзя.
  global.API.listJobs = async () => activeFullJob(77, { translate: 4 },
    { created: "2026-08-23 18:30:00" });
  hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
  hookIdx = 0;
  const out9 = [];
  walk(TabEditor({ store: storeStub, toast }), 0, out9);
  const t9 = out9.join("\n");
  check(t9.indexOf("<div.run-strip>") !== -1, "полоса на месте");
  check(t9.indexOf("осталось") === -1, "чужой снимок к прогону не прилип");
  check(t9.indexOf("прогон запущен не из этой вкладки") !== -1, "и об этом сказано прямо");

  console.log("\n=== 10. Ноль расхождений с глоссарием не уносит карточку ===");
  // Заглушка отдаёт ПУСТОЙ отчёт — ровно то состояние, в котором карточка
  // раньше не отрисовывалась вовсе. Вместе с ней пропадала «Пересчитать»,
  // то есть единственный способ убедиться, что ноль настоящий, а не остался
  // с прошлого расчёта.
  check(text.indexOf("Соответствие глоссарию") !== -1,
        "карточка на месте и при нуле");
  check(text.indexOf("Пересчитать") !== -1,
        "и «Пересчитать» вместе с ней");
  check(/Все переводы соответствуют утверждённым терминам/.test(text),
        "ноль назван словами, а не пустотой");
  check(text.indexOf("Перевести заново (0)") !== -1,
        "кнопка честно показывает ноль, а не исчезает");

  console.log("\n=== 11. Поиск над таблицей и переход к сегменту по номеру ===");
  // Зона — окно в ZONE_HALF (10) строк в каждую сторону. На семи сегментах она
  // совпала бы со всем файлом и не доказала бы ничего, поэтому добираем.
  for (let i = 8; i <= 40; i++) project.segments.push(seg(i));
  const rec = { list: [], info(t, m) { this.list.push(t + " " + m); },
                warning(t, m) { this.list.push(t + " " + m); }, error() {}, success() {} };
  const byProp = (n, key, val) => {
    if (!n || typeof n !== "object") return null;
    if (Array.isArray(n)) { for (const c of n) { const r = byProp(c, key, val); if (r) return r; } return null; }
    if ((n.props || {})[key] === val) return n;
    for (const c of (n.children || [])) { const r = byProp(c, key, val); if (r) return r; }
    return null;
  };
  const byLabel = (n, label) => {
    if (!n || typeof n !== "object") return null;
    if (Array.isArray(n)) { for (const c of n) { const r = byLabel(c, label); if (r) return r; } return null; }
    if (n.type === "button" && (n.children || []).indexOf(label) !== -1) return n;
    for (const c of (n.children || [])) { const r = byLabel(c, label); if (r) return r; }
    return null;
  };
  const segRows = (n, out) => {
    out = out || [];
    if (!n || typeof n !== "object") return out;
    if (Array.isArray(n)) { n.forEach(c => segRows(c, out)); return out; }
    const d = (n.props || {})["data-seg"];
    if (d !== undefined) out.push(d);
    (n.children || []).forEach(c => segRows(c, out));
    return out;
  };
  const draw = () => { hookIdx = 0; return TabEditor({ store: storeStub, toast: rec }); };
  const jumpTo = (num, el) => {
    byProp(el, "aria-label", "Перейти к сегменту по номеру").props.onChange({ target: { value: String(num) } });
    byProp(draw(), "aria-label", "Перейти к сегменту").props.onClick();
    return draw();
  };

  const el11 = draw();
  const head = findCls(el11, "table-head");
  check(!!head, "строка над таблицей отрисована");
  check(!!head && !!byProp(head, "placeholder", "Поиск по оригиналу и переводу…"),
        "поиск стоит НАД таблицей");
  // Поле поиска одно. Два поля на одно состояние — два места, где его ищут,
  // и лишняя высота у залипающей панели, из-за которой таблицу видно хуже.
  const sticky11 = findCls(el11, "editor-toolbar");
  check(!!sticky11 && !byProp(sticky11, "placeholder", "Поиск по оригиналу и переводу…"),
        "и в залипающей панели его больше нет — не дублируем");
  check(!!head && !!byProp(head, "aria-label", "Перейти к сегменту по номеру"),
        "и рядом слева — маленькая строка для номера сегмента");

  const el11c = jumpTo(20, el11);
  const rows11 = segRows(el11c);
  check(rows11.length === 21, "в зоне 21 строка: десять до, сам сегмент и десять после (" + rows11.length + ")");
  check(rows11[0] === 10 && rows11[rows11.length - 1] === 30, "окно построено вокруг введённого номера");
  check(rows11.indexOf(20) === 10, "сам сегмент — посередине, а не первой строкой страницы");
  const out11 = []; walk(el11c, 0, out11);
  const t11 = out11.join("\n");
  check(t11.indexOf("Зона сегмента #20") !== -1, "сказано, что в таблице не весь файл");
  check(t11.indexOf("10 до и 10 после") !== -1, "и сколько соседей видно");

  // Сбросы страницы и выбранного сегмента висят на фильтрах, а переход их
  // снимает: без флажка они в том же коммите утащили бы нас с зоны обратно
  // на первую страницу. Прогоняем эффекты сразу после перехода.
  effects.length = 0;
  const el11cc = draw();
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  check(segRows(draw()).length === 21, "сбросы после перехода зону не рушат");

  rec.list.length = 0;
  const el11e = jumpTo(999, el11cc);
  check(/Сегмента #999 в проекте нет/.test(rec.list.join(" ")),
        "несуществующий номер назван словами, а не молчанием");
  check(segRows(el11e).length === 21, "и зона от промаха не рассыпалась");

  const back = byLabel(el11e, "Весь файл");
  check(!!back, "из зоны есть выход");
  if (back) back.props.onClick();
  check(segRows(draw()).length === 10, "«Весь файл» возвращает обычную страницу");

  // Фильтр статуса зону не режет: просили показать СОСЕДЕЙ, а не тех из них,
  // кто уцелел после отбора. Снятое при этом называется вслух.
  byLabel(draw(), "Новые").props.onClick();
  rec.list.length = 0;
  const el11h = jumpTo(20, draw());
  check(segRows(el11h).length === 21, "зона показывает соседей поверх фильтра статуса");
  check(/Снял фильтр статуса/.test(rec.list.join(" ")), "и сказано, какой фильтр для этого снят");
  // ── 12. Сверка статусов: чем ловится устаревшая копия проекта ──
  console.log("");
  console.log("=== 12. Сверка статусов проекта с сервером ===");
  check(statusSig(statusCountsOf([{ id: 1 }, { id: 2, status: "qa" }])) === "new:1,qa:1",
        "сегмент без статуса считается «new» — ровно как на сервере");
  check(statusSig({ qa: 2, new: 1 }) === statusSig({ new: 1, qa: 2 }),
        "отпечаток не зависит от порядка ключей — иначе сверка врала бы на ровном месте");

  /* Число сегментов сходится, а статусы — нет: ровно тот случай, ради которого
     сверка и заведена. Прогон отработал на сервере, вкладка результат не
     забрала, и в одном окне стоят два ответа на один вопрос. */
  const pulls = [];
  const baseAPI = global.API;
  const driftAPI = Object.assign({}, baseAPI, {
    // Прогонов нет: сверка статусов — про простой. Пока результат прогона
    // не забран, ею занимается опрос задач, и лезть туда второй раз незачем.
    listJobs: async () => ({ active: [], jobs: [] }),
    segEdits: () => ({ busy: false, failed: false, ticket: "0:0" }),
    runPlan: async () => Object.assign(await baseAPI.runPlan(), {
      projectSegments: project.segments.length,
      projectStatus: { translated: 4, confirmed: 1, new: 1, qa: 1 },
    }),
    getProject: async () => { pulls.push(1); return { id: 1, segments: project.segments }; },
  });
  storeStub.replaceProjectSegments = () => {};
  const rerun = async () => {
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    TabEditor({ store: storeStub, toast });
    effects.forEach(fn => { try { fn(); } catch (e) {} });
    for (let i = 0; i < 30; i++) await new Promise(r => setImmediate(r));
  };
  global.API = driftAPI;
  await rerun();
  check(pulls.length === 1,
        "статусы разошлись при том же числе сегментов — проект подтянут (" + pulls.length + ")");

  /* А своя правка, ещё не доехавшая до сервера, поводом быть не должна:
     она применяется в браузере сразу, и разбор честно вернёт статусы ДО неё.
     Иначе каждое «Подтвердить» тянуло бы весь проект заново. */
  pulls.length = 0;
  global.API = Object.assign({}, driftAPI,
    { segEdits: () => ({ busy: true, failed: false, ticket: "1:0" }) });
  await rerun();
  check(pulls.length === 0,
        "наша правка в пути расхождением не считается (" + pulls.length + ")");

  /* Сервер молчит о статусах (старая версия бэкенда) — сверка молчит тоже,
     а не считает молчание расхождением. */
  pulls.length = 0;
  global.API = Object.assign({}, driftAPI, {
    runPlan: async () => Object.assign(await baseAPI.runPlan(),
      { projectSegments: project.segments.length }),
  });
  await rerun();
  check(pulls.length === 0, "без разбивки по статусам сверка не срабатывает (" + pulls.length + ")");
  global.API = baseAPI;


  /* Правка, успевшая и начаться, и закончиться за время разбора, флагом
     «занято» не ловится — только отпечатком. Ради этого он и заведён. */
  pulls.length = 0;
  let tk = 0;
  global.API = Object.assign({}, driftAPI,
    { segEdits: () => ({ busy: false, failed: false, ticket: (tk++) + ":" + tk }) });
  await rerun();
  check(pulls.length === 0,
        "правка, прошедшая целиком за время разбора, расхождением не считается (" + pulls.length + ")");

  /* Правка НЕ доехала до сервера: в браузере лежит текст, которого сервер
     не знает. Подстановка выбросила бы его молча — вместе с набранным
     человеком переводом. */
  pulls.length = 0;
  global.API = Object.assign({}, driftAPI,
    { segEdits: () => ({ busy: false, failed: true, ticket: "1:1" }) });
  await rerun();
  check(pulls.length === 0,
        "несохранённая правка выключает сверку: её текст дороже синхронизации (" + pulls.length + ")");

  // ── 13. Результат прогона забирается, несмотря на cleanup эффекта ──
  console.log("");
  console.log("=== 13. Конец прогона: подстановка переживает пересоздание эффекта ===");
  /* Тот самый баг: tick зовёт setJob(null), от этого меняется зависимость
     !!job, React делает cleanup — и dead взводится ЗАДОЛГО до того, как
     пятимегабайтный проект доедет. Проверка dead отменяла подстановку
     не иногда, а всегда. Здесь cleanup вызывается руками ровно в тот момент,
     когда его делает React: ответ getProject ещё в пути. */
  const laid = [];
  storeStub.replaceProjectSegments = (pid, segs) => laid.push(segs.length);
  const JOB = { id: 9, kind: "full", project: 1, created: "2026-08-26 00:00:00",
                status: "running", done: 3, total: 7, counters: {}, recent: [],
                params: { steps: ["translate"] } };
  let polls = 0, asked = 0;
  global.API = Object.assign({}, driftAPI, {
    listJobs: async () => (polls++ === 0
      ? { active: [JOB], jobs: [] }
      : { active: [], jobs: [Object.assign({}, JOB, { status: "done", done: 7 })] }),
    /* Разбор состава расхождение НАХОДИТ — и всё равно тянуть не должен:
       результат прогона ещё не забран, этим занят опрос задач. Иначе те же
       пять мегабайт уходят второй раз, да ещё с тостом про аварию после
       каждого штатного прогона. */
    runPlan: async () => Object.assign(await baseAPI.runPlan(), {
      projectSegments: project.segments.length,
      projectStatus: { translated: 4, confirmed: 1, new: 1, qa: 1 },
    }),
    getProject: async () => { asked++; await new Promise(r => setTimeout(r, 5));
                              return { id: 1, segments: project.segments }; },
  });
  hooks.length = 0; hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });        // опрос 1: прогон идёт
  for (let i = 0; i < 10; i++) await new Promise(r => setImmediate(r));
  hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  const cleanups = [];
  effects.forEach(fn => {
    try { const c = fn(); if (typeof c === "function") cleanups.push(c); } catch (e) {}
  });
  for (let i = 0; i < 5; i++) await new Promise(r => setImmediate(r));  // запрос ушёл
  cleanups.forEach(c => { try { c(); } catch (e) {} });                 // ← React гасит эффект
  /* И пересоздаёт его: !!job изменилось. Новый экземпляр немедленно делает
     свой tick и находит тот же завершённый прогон — второй ответ по пять
     мегабайт подряд на единственном воркере. */
  hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  await new Promise(r => setTimeout(r, 60));
  check(laid.length === 1,
        "проект подставлен, хотя эффект погашен во время запроса (" + laid.length + ")");
  check(asked === 1,
        "и запрошен ОДИН раз, а не каждым пересозданным эффектом (" + asked + ")");
  /* Забрали — отметку снимаем. Иначе КАЖДЫЙ следующий опрос находит тот же
     завершённый прогон и тянет пять мегабайт заново, вечно. Разбор состава
     на этом круге расхождения не находит: проверяется путь прогона, а свой
     повод тянуть проект только запутал бы счёт. */
  global.API = Object.assign({}, global.API, {
    runPlan: async () => Object.assign(await baseAPI.runPlan(),
      { projectSegments: project.segments.length }),
  });
  hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  await new Promise(r => setTimeout(r, 40));
  check(asked === 1,
        "забранный результат второй раз не запрашивается (" + asked + ")");

  /* Сервер стабильно не отдаёт проект. Отметку «результат не забран» держим —
     иначе одна моргнувшая сеть оставляет таблицу устаревшей навсегда, — но
     не бесконечно: воркер uvicorn ОДИН, и вечный запрос самого тяжёлого
     эндпоинта раз в 15 с это самообстрел. Кончились попытки — говорим вслух.
     Пока отметка держится, сверка статусов молчит: тянет опрос задач. */
  const say = { list: [], info(t, m) { this.list.push(t + " " + m); },
                warning(t, m) { this.list.push(t + " " + m); }, error() {}, success() {} };
  laid.length = 0; asked = 0; polls = 0;
  global.API = Object.assign({}, global.API, {
    getProject: async () => { asked++; return null; },
    // Без разбивки по статусам: здесь проверяется путь прогона, и лишний
    // повод тянуть проект только запутал бы счёт попыток.
    runPlan: async () => Object.assign(await baseAPI.runPlan(),
      { projectSegments: project.segments.length }),
  });
  hooks.length = 0; hookIdx = 0; effects.length = 0;
  // Круг 1 — прогон ещё идёт (отметка ставится), круги 2-4 — три неудачи,
  // круг 5 — отметка снята, больше не ходим.
  for (let round = 0; round < 5; round++) {
    hookIdx = 0; effects.length = 0;
    TabEditor({ store: storeStub, toast: say });
    effects.forEach(fn => { try { fn(); } catch (e) {} });
    for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
  }
  check(asked === 3,
        "неудачных попыток ровно три, а не бесконечно (" + asked + ")");
  check(laid.length === 0, "и ничего не подставлено (" + laid.length + ")");
  check(say.list.some(t => /Результат прогона не забран/.test(t)),
        "исчерпав попытки, вкладка говорит человеку обновить страницу");

  /* Номера задач живут в памяти процесса и после рестарта сервиса начинаются
     с единицы заново — поэтому прогон опознаётся ТРОЙКОЙ «номер + проект +
     время создания», как и снимок состава. По голому номеру отчёт о новом
     прогоне №9 считался бы уже сделанным и пропал бы молча: ни цены,
     ни числа ошибок, ни обновления карточек. */
  const said = { list: [], info(t) { this.list.push(t); }, warning(t) { this.list.push(t); },
                 error(t) { this.list.push(t); }, success(t) { this.list.push(t); } };
  const cycle = async (created) => {
    let step = 0;
    global.API = Object.assign({}, global.API, {
      getProject: async () => ({ id: 1, segments: project.segments }),
      listJobs: async () => (step++ === 0
        ? { active: [{ id: 9, kind: "full", project: 1, created, status: "running",
                       done: 1, total: 7, counters: {}, recent: [],
                       params: { steps: ["translate"] } }], jobs: [] }
        : { active: [], jobs: [{ id: 9, kind: "full", project: 1, created,
                                 status: "done", done: 7, total: 7, counters: {} }] }),
    });
    for (let r = 0; r < 2; r++) {
      hookIdx = 0; effects.length = 0;
      TabEditor({ store: storeStub, toast: said });
      effects.forEach(fn => { try { fn(); } catch (e) {} });
      for (let i = 0; i < 20; i++) await new Promise(z => setImmediate(z));
    }
  };
  hooks.length = 0;                       // свежая вкладка; дальше рефы живут
  await cycle("2026-08-26 01:00:00");
  const afterFirst = said.list.length;
  await cycle("2026-08-26 02:00:00");     // тот же номер, другой прогон
  check(afterFirst > 0, "о первом прогоне отчитались (" + afterFirst + ")");
  check(said.list.length > afterFirst,
        "и о втором с тем же номером — тоже (" + afterFirst + " → " + said.list.length + ")");
  global.API = baseAPI;


  console.log("\n" + (fail.length ? "ПРОВАЛЕНО: " + fail.join("; ") : "ВСЁ ПРОШЛО"));
  process.exit(fail.length ? 1 : 0);
} catch (e) {
  console.log("РЕНДЕР УПАЛ:", e && e.message);
  console.log((e && e.stack || "").split("\n").slice(0, 8).join("\n"));
  process.exit(1);
}
})();
