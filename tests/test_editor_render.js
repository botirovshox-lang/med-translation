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
/* Полка хуков на компонент: по 100 слотов, начиная с 1000. Сам TabEditor
   зовётся напрямую и живёт на полке 0 — его индексы не сдвинулись. */
const shelves = new Map();
function shelf(fn) {
  if (!shelves.has(fn)) shelves.set(fn, 1000 + shelves.size * 100);
  return shelves.get(fn);
}
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
      // У КАЖДОГО — своя полка хуков. У настоящего React список хуков свой
      // у каждого компонента; общий счётчик в заглушке перемешивал индексы,
      // и хук одного компонента получал слот другого (`useRef` — значение
      // `useState`). Полка, а не ослабленная проверка слота: иначе сдвиг
      // порядка хуков — ошибка, ради которой этот сторож и заведён, —
      // начал бы самозалечиваться.
      const save = hookIdx;
      hookIdx = shelf(type);
      try {
        return type(Object.assign({}, props, kids.length ? { children: kids } : {}));
      } finally {
        hookIdx = save;
      }
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
      planStep("backcheck", "back-check", "GPT-5.6 Luna", [1, 2, 3, 5, 6, 7], [{ reason: "ещё не проверялся", count: 5 }, { reason: "появится после перевода", count: 1 }], [{ reason: "уже проверен этим переводом", count: 1 }]),
      planStep("termcheck", "проверка терминов", "GPT-5.6 Terra", [1, 3, 4, 5, 6], [{ reason: "ещё не проверялся", count: 4 }, { reason: "прошлая проверка слабее нужной", count: 1 }], [{ reason: "уже проверен проверкой не слабее нужной", count: 2 }]),
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
  // Корзины «под ключ» для карточки «Анализ» в блоках запуска: та же форма,
  // что отдаёт /analysis. Считает их сервер — карточка только показывает.
  analysis: async () => ({ ok: true, total: 7,
    turnkey: { ready: [1, 2, 5], machine: [3, 6], human: [7], confirmed: [5], params: {} } }),
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

// i18n.js грузится первым и здесь: TR() зовут ВСЕ .jsx, и без него
// первый же рендер падает с ReferenceError. Словарь не подключаем —
// без него TR(s) === s, то есть тест видит ровно прежние надписи.
for (const f of ["i18n.js", "ui.jsx", "tab_editor_detail.jsx", "tab_editor.jsx"]) {
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
  /* Папки проектов: файл в настоящей папке — optgroup, файл без папки — хвост списка. */
  folders: [{ id: 900, title: "Договор", files: [project.id] }, { id: 901, title: "Пусто", files: [] }],
  /* Устройство прогона — шаги, модели, состав и цена — показывается только
     системному администратору. Разделы ниже проверяют именно ЭТОТ вид;
     простой вид (одна кнопка) проверяется разделом 18. Экспертный вид —
     суперпользователь С ВКЛЮЧЁННЫМ переключателем (`store.expert`, как
     в app.jsx), а не всякий суперпользователь. */
  can: { owner: true, super: true, role: "owner" }, expert: true,
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
  for (const m of ["Перевод", "Back-check", "Термины", "Ремонт", "Детерминированные проверки"])
    check(text.indexOf(m) !== -1, "строка шага: " + m);
  check(text.indexOf("Ориентировочно") !== -1, "общая смета под таблицей");
  check(text.indexOf("от back-check") !== -1,
        "у Medical QA вместо выбора модели написано, чью она берёт");

  console.log("\n=== 2. Настройки шагов переехали в таблицу ===");
  check(text.indexOf("Отдельные прогоны") === -1,
        "свёрнутого блока «Отдельные прогоны» больше нет — искать галочки негде");

  console.log("\n=== 2a. Колонка «Что тут»: одно слово по корзинам сервера ===");
  // Слово берётся из корзин /analysis (стаб выше: ready [1,2,5], machine [3,6],
  // human [7], seg 4 — ни в одной, seg 5 заверён, seg 6 не переведён).
  // Браузер ничего не выводит сам: чего нет в корзинах — без слова.
  const chips = {}, ths = [];
  (function findCells(n) {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(findCells);
    const p = n.props || {};
    if (n.type === "th") ths.push((n.children || []).filter(c => typeof c === "string").join(""));
    if (n.type === "tr" && p["data-seg"] != null) {
      const cell = (n.children || []).find(c => c && c.props && c.props.className === "chip-cell");
      const badge = cell && (cell.children || []).find(c => c && c.props);
      chips[p["data-seg"]] = badge ? (badge.children || []).join("") : "";
    }
    (n.children || []).forEach(findCells);
  })(el);
  const want = { 1: "хорошо", 2: "хорошо", 3: "доделаю", 4: "", 5: "ваше", 6: "ещё не перевела", 7: "спрошу" };
  for (const id of Object.keys(want))
    check(chips[id] === want[id], "строка " + id + ": «" + want[id] + "», а не «" + chips[id] + "»");
  check(ths.indexOf("Проверки") === -1 && ths.indexOf("Что тут") !== -1,
        "колонки «Проверки» нет, «Что тут» есть");
  check(text.indexOf("↩ ") === -1 && text.indexOf("ревизия:") === -1,
        "чипов проверок и процента back-check в таблице нет");

  // ── Раскрываем строку так, как это сделал бы человек: жмём шеврон ──
  const found = [];
  (function find(n) {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(find);
    const p = n.props || {};
    if (p.onClick && /Подробнее/.test(p["aria-label"] || "")) found.push(p.onClick);
    (n.children || []).forEach(find);
  })(el);
  // Шагов семь: перевод, РЕВИЗИЯ, back-check, термины, сверка терминов
  // моделью, ремонт, Medical QA. Ревизия стоит второй — всё, что переписывает
  // текст, обязано идти раньше того, что его описывает.
  check(found.length === 7, "у каждого шага есть раскрытие (" + found.length + " из 7)");

  console.log("\n=== 3. Раскрытая строка объясняет состав и даёт запуск ===");
  // Порядок строк повторяет FULL_RUN_STEPS: перевод, ревизия, back-check,
  // ТЕРМИНЫ. Индекс жёсткий, поэтому при вставке шага его правят здесь —
  // иначе тест молча проверял бы соседнюю строку.
  found[3]();                                    // четвёртая строка — «Термины»
  hookIdx = 0;
  const out2 = [];
  walk(TabEditor({ store: storeStub, toast }), 0, out2);
  const t2 = out2.join("\n");
  check(/в общий прогон:.*ещё не проверялся/.test(t2), "названо, кого шаг возьмёт");
  check(/пропустит:.*не слабее нужной/.test(t2), "и почему пропустит остальных");
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
  /* Группа на месте, а ИМЯ модели в её подписи больше не называется
     (modelsShown в ui.jsx): ключ группы ведёт отбор, подпись — только показ. */
  check(t2.indexOf("проверено, замечаний нет") !== -1,
        "группа с готовым вердиктом показана");
  check(t2.indexOf("проверено, замечаний нет: ") === -1
        && t2.indexOf("проверено: ") === -1,
        "…и имени модели в подписи группы нет");

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
  clicks[2]();                                   // третья строка — «Back-check»
  // Индексы строк жёсткие и повторяют FULL_RUN_STEPS: перевод, ревизия,
  // BACK-CHECK, термины, сверка терминов, ремонт, Medical QA. Вставили шаг —
  // правьте здесь, иначе тест молча проверит соседнюю строку. Что открылась
  // именно нужная, сторожит её собственный маркер ниже.
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
  // У раскрытой строки (после шага 5 это back-check) шеврон подписан
  // «Свернуть» и в этот список не попадает. Считаем от списка шагов:
  // перевод, ревизия, back-check(раскрыт), термины, сверка терминов, ремонт,
  // Medical QA — значит среди оставшихся ремонт пятый, индекс 4. Что открылась
  // именно нужная строка, проверяет её собственный маркер «Что чинить» ниже.
  clicks4[4]();
  hookIdx = 0;
  const out4 = [];
  const el4b = TabEditor({ store: storeStub, toast });
  walk(el4b, 0, out4);
  const t4 = out4.join("\n");
  check(t4.indexOf("Чинить написанное человеком") !== -1,
        "переключатель «чинить подтверждённые» на месте");
  check(t4.indexOf("в выборке нет ваших сегментов с находками") !== -1,
        "и рядом сказано, сколько вашей работы ждёт починки");
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
    if (p.onClick && p["aria-label"] === "Чинить мои строки") { armSwitch = p.onClick; return; }
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

  console.log("\n=== 10. «Термины глоссария»: команда, а не второй отчёт ===");
  // Разбор соответствия глоссарию (списки, «Пересчитать», «Перевести заново»)
  // живёт на «Проверке» — в редакторе он только повторял его. Кнопка
  // одобрения стоит, только когда есть что применять: заглушка отдаёт пустой
  // отчёт и пустой разбор автоодобрения — карточки нет вовсе.
  check(text.indexOf("Соответствие глоссарию") === -1,
        "секции соответствия в редакторе больше нет");
  check(text.indexOf("Пересчитать") === -1 && text.indexOf("Перевести заново") === -1,
        "и её «Пересчитать» / «Перевести заново» тоже");
  check(text.indexOf("Нечего применять") === -1 && text.indexOf("и применить") === -1,
        "применять нечего — ни кнопки, ни пустой рамки «Нечего применять»");
  {
    const saved = global.API;
    global.API = Object.assign({}, saved, {
      autoApprove: async () => ({ ok: true, counts: { auto: 2, verified: 1, skipped: 0 } }),
      glossaryImpact: async () => ({ ok: true, terms: [], segments: [3, 4], pending: [3, 4], confirmed: [], futile: [4] }),
    });
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    TabEditor({ store: storeStub, toast });
    effects.forEach(fn => { try { fn(); } catch (e) {} });
    for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
    hookIdx = 0; effects.length = 0;
    const o10 = []; walk(TabEditor({ store: storeStub, toast }), 0, o10);
    const t10 = o10.join("\n");
    check(t10.indexOf("Одобрить 3 и применить") !== -1,
          "есть что одобрить — кнопка «Одобрить N и применить» на месте");
    check(t10.indexOf("ремонт не возьмёт — их правит человек") !== -1,
          "застрявшие названы одной строкой, а не абзацем");
    check(t10.indexOf("Соответствие глоссарию") === -1, "и секция соответствия не вернулась");
    global.API = saved;
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    TabEditor({ store: storeStub, toast });
    effects.forEach(fn => { try { fn(); } catch (e) {} });
    for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
  }

  console.log("\n=== 10a. Корзины в редакторе — ОДИН набор ===");
  // Прежде корзины рисовались трижды: плитки, карточка «Анализ» в блоках
  // запуска и кнопки-фильтры над таблицей. Остались плитки (с кнопкой
  // «Показать N сегм. →») и фильтры над таблицей, которые они зажигают.
  for (const m of ["Готово к сдаче", "Возьмёт ближайший прогон", "Нужно ваше решение"])
    check(text.split(m).length - 1 === 1, "корзина «" + m + "» нарисована один раз");
  check(text.indexOf("Открыть «Анализ»") === -1 && text.indexOf("Анализ") === -1,
        "карточки «Анализ» больше нет, и слова «Анализ» в редакторе тоже");
  check(text.indexOf("Разобрать на «Проверке»") !== -1, "у «Нужно ваше решение» — переход на «Проверку»");
  const btnText = (n) => (n.children || []).map(c => typeof c === "object" ? "" : String(c)).join("");
  const findAll = (n, pred, out) => {
    out = out || [];
    if (!n || typeof n !== "object") return out;
    if (Array.isArray(n)) { n.forEach(c => findAll(c, pred, out)); return out; }
    if (pred(n)) out.push(n);
    (n.children || []).forEach(c => findAll(c, pred, out));
    return out;
  };
  {
    const calls = [];
    const st = Object.assign({}, storeStub, {
      setSegmentFilter(ids, meta) {
        calls.push([ids, meta]);
        st.segmentFilter = ids && ids.length ? new Set(ids) : null;
        st.segmentFilterMeta = st.segmentFilter ? (meta || null) : null;
      },
    });
    hookIdx = 0; effects.length = 0;
    const e1 = TabEditor({ store: st, toast });
    const show = findAll(e1, n => n.type === "button" && /^Показать \d+ сегм\. →$/.test(btnText(n)));
    check(show.length === 4, "у каждой плитки — кнопка «Показать N сегм. →» (" + show.length + ")");
    const readyBtn = show.find(n => btnText(n) === "Показать 3 сегм. →");
    check(!!readyBtn, "число на кнопке — размер корзины «Готово» (3)");
    if (readyBtn) readyBtn.props.onClick();
    check(calls.length === 1 && calls[0][0].join(",") === "1,2,5" && calls[0][1] && calls[0][1].bucket === "ready",
          "кнопка фильтрует таблицу выборкой корзины и называет корзину");
    hookIdx = 0; effects.length = 0;
    const e2 = TabEditor({ store: st, toast });
    const chip = findAll(e2, n => n.type === "button" && n.props["data-bucket"] === "ready")[0];
    check(!!chip && chip.props["aria-pressed"] === true, "над таблицей зажглась кнопка-фильтр «Готово»");
    const all = findAll(e2, n => n.type === "button" && n.props["data-bucket"] === "all")[0];
    check(!!all && all.props["aria-pressed"] === false, "а «Все» погасла");
    const tile = findAll(e2, n => n.props && n.props["data-bucket"] === "ready" && /st-card/.test(n.props.className || ""))[0];
    check(!!tile && / st-on/.test(tile.props.className), "и плитка «Готово» выделена");
    check(findAll(e2, n => n.type === "tr" && n.props["data-seg"] != null).map(n => n.props["data-seg"]).join(",") === "1,2,5",
          "в таблице ровно сегменты корзины");
    // Выборка с «Проверки» (BucketCard) несёт ту же корзину — горит та же кнопка.
    st.setSegmentFilter([7], { bucket: "human", label: "Нужно ваше решение" });
    hookIdx = 0; effects.length = 0;
    const e3 = TabEditor({ store: st, toast });
    const hum = findAll(e3, n => n.type === "button" && n.props["data-bucket"] === "human")[0];
    check(!!hum && hum.props["aria-pressed"] === true, "выборка с «Проверки» зажигает кнопку своей корзины");
  }
  hookIdx = 0; effects.length = 0;

  console.log("\n=== 10b. Карточка сегмента — только по нажатию ===");
  // Прежде справа всегда стояла колонка 300–352 px, даже с «Сегмент не
  // выбран». Теперь колонки нет, пока карточку не открыли.
  {
    let detail = null;
    const realDetail = global.SegDetail;
    global.SegDetail = (p) => { detail = p; return null; };
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    TabEditor({ store: storeStub, toast });
    effects.forEach(fn => { try { fn(); } catch (e) {} });
    for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
    hookIdx = 0; effects.length = 0;
    const b1 = TabEditor({ store: storeStub, toast });
    const body1 = findAll(b1, n => /^editor-body/.test((n.props || {}).className || ""))[0];
    check(!!body1 && body1.props.className === "editor-body", "сразу после открытия колонки карточки нет — таблица во всю ширину");
    check(!findCls(b1, "editor-side") && detail === null, "и пустой рамки «Сегмент не выбран» тоже");
    check(text.indexOf("Сегмент не выбран") === -1, "надпись «Сегмент не выбран» ушла");
    const row2 = findAll(b1, n => n.type === "tr" && n.props["data-seg"] === 2)[0];
    row2.props.onClick();
    hookIdx = 0; effects.length = 0;
    const b2 = TabEditor({ store: storeStub, toast });
    const body2 = findAll(b2, n => /^editor-body/.test((n.props || {}).className || ""))[0];
    check(!!body2 && body2.props.className === "editor-body has-side", "нажали строку — колонка карточки появилась");
    check(!!findCls(b2, "editor-side") && detail && detail.seg.id === 2, "и в ней карточка нажатого сегмента");
    check(detail && typeof detail.onClose === "function", "у карточки есть «×»");
    detail.onClose();
    detail = null;
    hookIdx = 0; effects.length = 0;
    const b3 = TabEditor({ store: storeStub, toast });
    check(!findCls(b3, "editor-side") && detail === null, "«×» закрывает карточку и отдаёт ширину таблице");

    console.log("\n=== 10c. Переход с «Проверки» приносит слова ===");
    // Выборка с «Проверки» несёт термин и варианты перевода: они горят
    // в строках таблицы (без учёта регистра, безопасно для скобок и точек),
    // а карточка первого сегмента выборки открывается сама — с теми же словами.
    const st = Object.assign({}, storeStub, {
      segmentFilter: new Set([3, 4]),
      segmentFilterMeta: { terms: ["КАШЕЛЬ", "cough 3", "(x+"], label: "Термин: кашель" },
    });
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    TabEditor({ store: st, toast });
    effects.forEach(fn => { try { fn(); } catch (e) {} });
    for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
    hookIdx = 0; effects.length = 0;
    const c1 = TabEditor({ store: st, toast });
    check(detail && detail.seg.id === 3, "карточка первого сегмента выборки открылась сама (" + (detail && detail.seg.id) + ")");
    check(detail && (detail.hlTerms || []).join("|") === "КАШЕЛЬ|cough 3|(x+", "и получила слова для подсветки");
    const tr3 = findAll(c1, n => n.type === "tr" && n.props["data-seg"] === 3)[0];
    const marks = (cls) => findAll(findAll(tr3, n => n.props && n.props.className === cls), n => n.type === "mark")
      .map(m => (m.children || []).join(""));
    check(marks("src-cell").join("|") === "кашель", "в оригинале горит термин, регистр не важен (" + marks("src-cell").join("|") + ")");
    check(marks("tgt-cell").join("|") === "cough 3", "в переводе горит вариант перевода (" + marks("tgt-cell").join("|") + ")");
    const o10c = []; walk(c1, 0, o10c);
    check(o10c.join("\n").indexOf("проверить:") !== -1, "полоса фильтра называет слова для проверки");
    global.SegDetail = realDetail;
  }
  hooks.length = 0; hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));

  console.log("\n=== 10d. markTerms: несколько слов, без регулярок ===");
  const mt = (s, t) => { const r = markTerms(s, t); return Array.isArray(r)
    ? r.map(x => typeof x === "string" ? x : "[" + x.children.join("") + "]").join("") : r; };
  check(mt("Кашель и кашель", ["кашель"]) === "[Кашель] и [кашель]", "все вхождения, регистр не важен");
  check(mt("артериальное давление", ["давление", "артериальное давление"]) === "[артериальное давление]",
        "пересечения сливаются в одну метку");
  check(mt("доза (мг) и а.b", ["(мг)", "а.b", "[", "*"]) === "доза [(мг)] и [а.b]", "скобки и точки ищутся буквально");
  check(mt("Ёлка", ["елка"]) === "[Ёлка]", "«ё» и «е» — одна буква");
  check(mt("текст", []) === "текст" && mt("", ["x"]) === "", "без слов — текст как есть");

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

  console.log("\n=== 14. До первого прогона сводки корзин нет ===");
  // Проект из одних «новых»: корзины тривиальны, и нагружать ими интерфейс
  // (и единственный воркер запросом /analysis) незачем. Карточка появляется
  // после первого прогона либо когда в проекте уже есть переведённое.
  let asked14 = 0;
  const freshProject = { id: 2, title: "Новый", src: "RU", tgt: "EN", domain: "medical",
    segments: [{ id: 1, source: "текст", target: "", status: "new", risk: "low" }] };
  const freshStore = Object.assign({}, storeStub, {
    activeProject: freshProject, projects: [freshProject],
    statusCounts: () => ({ all: 1, new: 1, translated: 0, qa: 0, confirmed: 0, failed: 0, review: 0 }),
  });
  global.API = Object.assign({}, baseAPI, {
    listJobs: async () => ({ active: [], jobs: [] }),
    analysis: async () => { asked14++; return { ok: true, total: 1,
      turnkey: { ready: [], machine: [1], human: [] } }; },
  });
  hooks.length = 0; hookIdx = 0; effects.length = 0;
  TabEditor({ store: freshStore, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
  hookIdx = 0;
  const out15 = [];
  walk(TabEditor({ store: freshStore, toast }), 0, out15);
  check(out15.join("\n").indexOf("Готово к сдаче") === -1, "корзин на экране нет");
  check(asked14 === 0, "и /analysis не запрашивался зря (" + asked14 + ")");
  global.API = baseAPI;

  console.log("\n=== 15в. Модель не уезжает на сервер мимо рубежа ===");
  /* Выбор модели спрятан (`modelsShown` → false), поэтому переменные
     `gptModel`/`bcModel`/… содержат ПСЕВДОНИМ каталога («m3»), а не рабочий
     id. Уехав на сервер, псевдоним проходит `_resolve_model` и молча
     превращается в модель ПЕРЕВОДА по умолчанию: разбор состава и смета
     считаются не той моделью, чем пойдёт прогон, и признаков у этого нет
     никаких — числа выглядят правдоподобно.
     Поэтому в тело запроса модель кладётся только под `modelPick`.
     Сверяем ИСХОДНИК: рендер такой отправки не видит. */
  {
    // Проверяем ВСЕ .jsx, а не один редактор: отправку заведут там, где
    // её удобнее написать, а рубеж обязан стоять в каждом файле.
    const bad = [];
    const re = /\b(?:model|bc_model|tc_model|rp_model|rv_model|tcx_model|judge_model)\s*:\s*([A-Za-z][\w]*)/g;
    for (const f of fs.readdirSync(root).filter(x => x.endsWith(".jsx"))) {
      const src = fs.readFileSync(path.join(root, f), "utf8");
      let m;
      re.lastIndex = 0;
      while ((m = re.exec(src))) {
        const val = m[1];
        // Голая переменная выбора — только через modelPick/pickModel.
        if (!/^(gptModel|bcModel|tcModel|rpModel|rvModel|tcxModel|judgeModel)$/.test(val)) continue;
        const line = src.slice(0, m.index).split("\n").length;
        const around = src.slice(Math.max(0, m.index - 220), m.index + 60);
        if (around.indexOf("modelPick") === -1 && around.indexOf("pickModel") === -1)
          bad.push(f + " (стр. " + line + "): " + m[0]);
      }
    }
    check(bad.length === 0,
          "все отправки модели идут через modelPick" + (bad.length ? ":\n       " + bad.join("\n       ") : ""));
  }

  console.log("\n=== 16. Смета главной кнопки — число, а не прочерк ===");
  /* Шаг с работой и без цены обнуляет ВСЮ смету намеренно: «$0.00» под
     кнопкой, которая сделает тысячи платных вызовов, — худший вид молчания.
     Но цены у шага может не быть по причине, к деньгам отношения не имеющей:
     выбор модели в браузере пуст. Так и вышло со сверкой терминов — её
     единственную каталог не заполнял, — и прочерк вставал под кнопкой при
     исправных ценах всех шести шагов, а список моделей у шага рисовался
     без выбранной строки.
     Два рубежа, и оба проверяются:
       1) КАЖДЫЙ выбор модели заполняется из каталога (проверка по исходнику:
          забытая строка — это ровно то, что случилось, и рендер её не видит,
          потому что дефолт каталога подставляется дальше по цепочке);
       2) модель, которой шаг ПОЙДЁТ, называет сервер в разборе (plan.model),
          и смета берёт её, когда выбора нет. */
  {
    const src16 = fs.readFileSync(path.join(root, "tab_editor.jsx"), "utf8");
    const eff = src16.slice(src16.indexOf("window.API.models()"));
    const body = eff.slice(0, eff.indexOf("}, []);"));
    /* Список выводим из window.MODEL_LS, а не пишем руками: захардкоженная
       карта пропустила новый шаг (ревизию) и проверка осталась зелёной при
       живом дефекте — выбор модели каталогом не заполнялся, а цены у шага
       не было, то есть смета ГЛАВНОЙ кнопки становилась прочерком.
       Имя сеттера выводится из имени параметра: rv_model -> setRvModel. */
    const setterOf = (k) => "set" + k.replace(/_model$/, "")
      .replace(/(^|_)([a-z])/g, (m, s, c) => c.toUpperCase()) + "Model";
    const keys = Object.keys(global.window.MODEL_LS || {});
    check(keys.length >= 7, "карта ключей моделей полна (" + keys.length + ")");
    const SETTER = {};
    keys.forEach(k => { SETTER[k] = k === "model" ? "setGptModel" : setterOf(k); });
    const lost = Object.keys(SETTER).filter(k => body.indexOf(SETTER[k] + "(") === -1);
    check(lost.length === 0,
          "каталог заполняет ВСЕ выборы моделей" + (lost.length ? ": забыт " + lost.join(", ") : ""));
  }
  global.API = Object.assign({}, baseAPI, {
    runPlan: async () => {
      const p = await baseAPI.runPlan();
      return Object.assign({}, p, { steps: p.steps.concat([
        planStep("termaudit", "сверка терминов", "gpt-5.6-terra", [1, 3, 5],
                 [{ reason: "ещё не сверялся", count: 3 }], []),
      ]) });
    },
  });
  hooks.length = 0; hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
  hookIdx = 0;
  const out16 = [];
  walk(TabEditor({ store: storeStub, toast }), 0, out16);
  const t16 = out16.join("\n");
  // Цена лежит в <b> следующей строкой обхода, поэтому тег пропускаем явно:
  // регулярка без него ловила сам тег и радовалась «не прочерк».
  const est16 = /Ориентировочно:\s*\n\s*<b>\s*\n\s*(\S+)/.exec(t16);
  check(!!est16, "смета под таблицей есть");
  check(est16 && /^\$[\d.]+$/.test(est16[1]),
        "и это цена, а не прочерк (" + (est16 ? est16[1] : "?") + ")");
  check(t16.indexOf("Сверка терминов") !== -1, "строка сверки терминов на месте");
  global.API = baseAPI;

  /* Сегмент, распознанный на КАРТИНКЕ, заводится последним и получает номер
     max+1, а встаёт на место своей картинки в документе. Номера в таблице
     из-за этого перестают идти подряд — и выглядит это как сломанный отбор,
     хотя ни поиск, ни фильтр строк не двигают. Проверяем ровно три вещи:
     порядок документа по умолчанию, разрыв назван вслух и чинится кнопкой,
     а сортировка по номеру честно говорит, что документом список больше
     не является. */
  console.log("");
  console.log("=== 17. Порядок строк: документ против номера ===");
  const text17 = (node) => {
    const out = [];
    (function go(n) {
      if (n === null || n === undefined) return;
      if (typeof n === "string" || typeof n === "number") { out.push(String(n)); return; }
      if (Array.isArray(n)) return n.forEach(go);
      if (typeof n !== "object") return;
      const p = n.props || {};
      if (p.title) out.push(p.title);
      (n.children || []).forEach(go);
    })(node);
    return out.join(" | ");
  };
  const click17 = (node, label) => {
    let hit = null;
    (function go(n) {
      if (hit || !n || typeof n !== "object") return;
      if (Array.isArray(n)) return n.forEach(go);
      const p = n.props || {};
      if (n.type === "button" && p.onClick
          && (n.children || []).filter(c => typeof c === "string").join(" ").indexOf(label) !== -1) {
        hit = p.onClick; return;
      }
      (n.children || []).forEach(go);
    })(node);
    return hit;
  };
  const render17 = () => { hookIdx = 0; effects.length = 0; return TabEditor({ store: storeStub, toast }); };
  // Картинка стоит между сегментами 4 и 5, поэтому её сегмент встаёт туда же,
  // а номер у него max+1 — ровно тот разрыв, из-за которого таблицу читают
  // как сломанную.
  project.segments.splice(4, 0, seg(2692, {
    origin: { kind: "image", part: "word/media/image7.png", block: 0 } }));
  store.removeItem("mcat_seg_order");
  hooks.length = 0; hookIdx = 0; effects.length = 0;
  TabEditor({ store: storeStub, toast });
  effects.forEach(fn => { try { fn(); } catch (e) {} });
  for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
  const el17 = render17();
  const rows17 = segRows(el17).join(",");
  check(rows17 === "1,2,3,4,2692,5,6,7,8,9",
        "по умолчанию строки идут порядком документа (" + rows17 + ")");
  const t17 = text17(el17);
  check(t17.indexOf("Номера идут не по возрастанию") !== -1,
        "разрыв в номерах назван вслух, а не оставлен догадкой");
  check(t17.indexOf("Распознано на картинке") !== -1,
        "строка, пришедшая с картинки, помечена в самой таблице");
  const toNum = click17(el17, "Сортировать по номеру");
  check(!!toNum, "рядом с объяснением стоит кнопка сортировки");
  if (toNum) toNum();
  const el17b = render17();
  const rows17b = segRows(el17b).join(",");
  check(rows17b === "1,2,3,4,5,6,7,8,9,10",
        "по номеру список монотонный (" + rows17b + ")");
  const t17b = text17(el17b);
  check(t17b.indexOf("соседями в тексте не являются") !== -1,
        "и сказано, что соседство в нём документу больше не соответствует");
  check(t17b.indexOf("Номера идут не по возрастанию") === -1,
        "прежняя полоса про разрыв ушла: в показанном порядке разрыва нет");
  const toDoc = click17(el17b, "Вернуть порядок документа");
  check(!!toDoc, "и есть чем вернуть порядок документа");
  if (toDoc) toDoc();
  check(segRows(render17()).join(",") === "1,2,3,4,2692,5,6,7,8,9",
        "возврат работает: снова порядок документа");
  project.segments = project.segments.filter(s => s.id !== 2692);
  store.removeItem("mcat_seg_order");

  console.log("\n=== 18. Два рубежа: устройство прогона и смета ===");
  /* Устройство (шаги, модели, состав) — системному администратору: выбирать
     модель тому, кто не знает целевого языка, нечем. А СМЕТА — тому, кто
     платит: у владельца это единственное число, по которому он решает,
     запускать ли книгу. Рубежи РАЗНЫЕ, и тест сторожит именно это. */
  /* Состояние хуков живёт между разделами (заглушка), и после раздела
     с идущим прогоном кнопка была бы «Остановить». Раздел 18 — про
     свежий экран: хуки сбрасываются, прогонов нет, а разбор состава
     и корзины собираются заново первым проходом эффектов. */
  global.API.listJobs = async () => ({ active: [], jobs: [] });
  const fresh = async (can) => {
    /* Деньги прячет СЕРВЕР (`_hide_cost` → `hideCost` → `window.HIDE_COST`),
       и экран читает именно этот признак, а не роль. Заглушка обязана вести
       себя так же, иначе тест сторожит роль там, где код смотрит на флаг. */
    global.window.HIDE_COST = !(can && can.super);
    const st = Object.assign({}, storeStub, { can, expert: false });
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    TabEditor({ store: st, toast });
    effects.forEach(fn => { try { fn(); } catch (e) {} });
    for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
    hookIdx = 0; effects.length = 0;
    const out = [];
    walk(TabEditor({ store: st, toast }), 0, out);
    return out.join("\n");
  };
  const t18 = await fresh({ owner: true, super: false, role: "owner" });
  check(t18.indexOf("Перевести и проверить") !== -1, "владелец: главная кнопка на месте");
  check(t18.indexOf("\u2248 цена") === -1, "владелец: колонки цены по шагам нет");
  check(t18.indexOf("Модель") === -1, "владелец: выбора моделей нет");
  // Прежде смета оставалась владельцу («он платит»). Теперь деньги видит
  // только администратор сервиса: за модели платит не агентство, а сервис.
  check(t18.indexOf("Ориентировочно") === -1, "владелец: сметы нет — деньги сервиса не его дело");
  check(t18.indexOf("Переведу, перечитаю") !== -1, "вместо устройства — обещание словами");
  check(t18.indexOf("в работу пойдут") !== -1, "сколько строк уйдёт в работу — сказано");

  check(t18.indexOf("Готово к сдаче") !== -1, "владелец: сводка с корзинами наверху");
  /* Суперпользователь БЕЗ «Вида эксперта» — тот же простой экран. Прежде
     редактор считал экспертом любого суперпользователя, и выбор модели,
     сохранённый в браузере когда-то раньше, уезжал в задачу молча: боевой
     прогон 18.09 переводил книгу не той моделью, что стоит в админке. */
  const t18s = await fresh({ owner: true, super: true, role: "owner" });
  check(t18s.indexOf("Модель") === -1 && t18s.indexOf("Переведу, перечитаю") !== -1,
        "суперпользователь без вида эксперта: простой экран, выбора моделей нет");
  const t18b = await fresh({ owner: false, super: false, role: "translator" });
  check(t18b.indexOf("Перевести и проверить") !== -1, "переводчик: кнопка на месте");
  check(t18b.indexOf("Ориентировочно") === -1, "переводчик: сметы нет — деньги не его дело");

  console.log("\n=== 19. Отказ сервера — словами сервера, экран не врёт ===");
  /* Подтверждение пустого (400) и перевод выше предела (409) шли через
     safeCall: первое ставило «подтверждено» и хвалило тостом, второе
     говорило «сервер недоступен». */
  {
    let detail = null;
    const realDetail = global.SegDetail;
    global.SegDetail = (p) => { detail = p; return null; };
    const upd = [], errs = [], oks = [];
    const st = Object.assign({}, storeStub, { updateSegment: (pid, sid, patch) => { upd.push(patch); } });
    const tst = { info() {}, warning() {}, error: (t, m) => errs.push(t + " | " + m), success: (t) => oks.push(t) };
    const rerender = async () => {
      hookIdx = 0; effects.length = 0;
      const el = TabEditor({ store: st, toast: tst });
      return el;
    };
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    TabEditor({ store: st, toast: tst });
    effects.forEach(fn => { try { fn(); } catch (e) {} });
    for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
    const pick = async (sid) => {
      const b = await rerender();
      findAll(b, n => n.type === "tr" && n.props["data-seg"] === sid)[0].props.onClick();
      await rerender();
      return detail;
    };
    let confirmCalls = 0;
    global.API.confirm = async () => { confirmCalls++; const e = new Error("Пустой перевод не подтверждается"); e.status = 400; throw e; };
    let d6 = await pick(6);                       // сегмент 6 — пустой перевод
    await d6.onConfirm("");
    check(confirmCalls === 0 && !upd.some(p => p.status === "confirmed") && errs.length === 1 && !oks.length,
          "пустое: сервер не спрошен, «подтверждено» не поставлено, ошибка названа: " + errs.join(" / "));
    errs.length = 0;
    const d2 = await pick(2);
    await d2.onConfirm(d2.seg.target);
    check(confirmCalls === 1 && !upd.some(p => p.status === "confirmed") && errs.length === 1
          && errs[0].indexOf("Пустой перевод не подтверждается") !== -1 && !oks.length,
          "отказ сервера: статус не тронут, тост словами сервера: " + errs.join(" / "));
    errs.length = 0;
    global.API.translate = async () => { const e = new Error("Строку уже переводили заново 3 раз — это предел организации."); e.status = 409; throw e; };
    await d2.onTranslate();
    check(errs.length === 1 && errs[0].indexOf("предел организации") !== -1 && errs[0].indexOf("Сервер недоступен") === -1,
          "409 предела перевода заново — словами сервера, а не «сервер недоступен»: " + errs.join(" / "));

    console.log("\n=== 20. Сохранённая модель без ключа не уезжает в работу ===");
    /* Выбор из localStorage, у поставщика которого ключа больше нет
       (`ready: false`): сбрасывается на умолчание шага, и эксперту это
       сказано тостом, а в вызов уходит умолчание. */
    store.setItem("mcat_gpt_model", "claude-x");
    const realModels = global.API.models;
    global.API.models = async () => {
      const d = await realModels();
      d.models = d.models.concat([{ id: "claude-x", label: "Claude X", in: 1, out: 5, api: "anthropic", ready: false }]);
      return d;
    };
    const warns = [];
    tst.warning = (t, m) => warns.push(t + " | " + m);
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    TabEditor({ store: st, toast: tst });
    effects.forEach(fn => { try { fn(); } catch (e) {} });
    for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r));
    let sentModel = null;
    global.API.translate = async (pid, sid, force, model) => { sentModel = model; return { segment: { target: "x", status: "translated" } }; };
    const d2b = await pick(2);
    await d2b.onTranslate();
    check(sentModel === "gpt-4o", "в перевод ушло умолчание, а не модель без ключа: " + sentModel);
    /* Тоста больше нет и быть не должно: выбор модели спрятан от всех
       (modelsShown), в задачу он не едет вовсе, а сам тост называл бы имя
       модели тому, от кого его прячут. Важно другое — что уехало в вызов. */
    check(!warns.some(w => w.indexOf("Claude X") !== -1),
          "имя сброшенной модели никому не называется: " + warns.join(" / "));
    global.API.models = realModels;
    store.removeItem("mcat_gpt_model");
    global.SegDetail = realDetail;
  }

  console.log("\n=== 21. Текст правится в самой строке ===");
  /* Оригинал и перевод правятся тут же, в таблице: карточка их больше
     не дублирует. Сюда же переехали два правила, которые раньше сторожила
     карточка: «стёртый перевод — Новый» и «заверить вправе любая роль». */
  {
    const seen = [];
    const st2 = Object.assign({}, storeStub, {
      updateSegment: (pid, sid, patch) => { seen.push([sid, patch]); return Promise.resolve({}); },
      mergeServerSegments() {},
    });
    const rowOf = (tree, id) => findAll(tree, n => n.type === "tr" && n.props["data-seg"] === id)[0];
    const cellOf = (row, field) => findAll(row, n => n.type === "td"
      && new RegExp(field === "src" ? "src-cell" : "tgt-cell").test((n.props || {}).className || ""))[0];
    const draw2 = () => { hookIdx = 0; effects.length = 0; return TabEditor({ store: st2, toast }); };
    const saveBtn = (row) => findAll(row, n => n.type === "button"
      && (n.children || []).some(c => typeof c === "string" && c.indexOf("Сохранить") !== -1))[0];
    const openCell = (id, field) => {
      // Первое нажатие выбирает строку, второе — открывает поле: случайно
      // набранный текст в чужой строке — это чужая работа.
      rowOf(draw2(), id).props.onClick();
      const cell = cellOf(rowOf(draw2(), id), field);
      check(!!cell && typeof cell.props.onClick === "function",
            "на выбранной строке ячейка «" + field + "» открывается нажатием");
      cell.props.onClick({ stopPropagation() {} });
      return rowOf(draw2(), id);
    };
    hooks.length = 0;
    let r = openCell(1, "tgt");
    let ta = findAll(r, n => n.type === "textarea")[0];
    check(!!ta && ta.props.defaultValue === "complaints of cough 1", "в поле — нынешний перевод строки");
    check(!!saveBtn(r), "рядом с полем — «Сохранить»");
    // Текст не менялся — на сервер ничего не уходит.
    saveBtn(r).props.onClick();
    await new Promise(res => setImmediate(res));
    check(seen.length === 0, "текст не менялся — на сервер ничего не ушло");
    // Стёртый перевод уходит со статусом «Новый», а не «Переведён»: тот же
    // предикат, что на сервере (`_needs_translation`).
    hooks.length = 0;
    r = openCell(1, "tgt");
    // Поле неуправляемое (ref + defaultValue): подменяем сам ref, как это
    // сделал бы браузер, положив туда узел с набранным текстом.
    findAll(r, n => n.type === "textarea")[0].props.ref.current = { value: "   " };
    saveBtn(r).props.onClick();
    await new Promise(res => setImmediate(res));
    check(seen.length === 1 && seen[0][1].status === "new" && seen[0][1].target === "   ",
          "пустой текст уходит со статусом «new» (" + JSON.stringify(seen[0] || null) + ")");

    // Правка ОРИГИНАЛА: сильная замена спрашивает человека ДО записи.
    const calls = [];
    global.API.editSource = async (pid, sid, source, dry) => {
      calls.push([sid, source, !!dry]);
      return { ok: true, mode: "new", ratio: 0.2, applied: !dry,
               segment: { id: sid, source, target: "", status: "new" } };
    };
    let asked = null;
    global.confirm = (t) => { asked = t; return false; };
    hooks.length = 0;
    r = openCell(2, "src");
    ta = findAll(r, n => n.type === "textarea")[0];
    check(!!ta && ta.props.defaultValue === "жалобы на кашель 2", "в поле — нынешний оригинал строки");
    ta.props.ref.current = { value: "совсем другой текст про мёд" };
    saveBtn(r).props.onClick();
    await new Promise(res => setImmediate(res));
    check(calls.length === 1 && calls[0][2] === true,
          "сперва сухой запрос: сервер называет, чем станет строка");
    check(asked && asked.indexOf("считается новой") !== -1,
          "«другая строка» — спрошено ДО записи: " + (asked || "—"));
    check(!calls.some(c => c[2] === false), "человек отказался — записи не было");
    delete global.confirm;
    delete global.API.editSource;
  }

  console.log("\n=== 21а. Заверяет любая роль; жалоба подсвечена ===");
  {
    /* «Подтвердить» стоит в строке, а не в карточке (её оттуда убрали).
       Право заверять есть у ЛЮБОЙ роли — это решение владельца сервиса,
       а не забывчивость (инвариант 12). */
    const stT = Object.assign({}, storeStub, { can: { owner: false, super: false, role: "translator" }, expert: false });
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    const tT = TabEditor({ store: stT, toast });
    const rowT = findAll(tT, n => n.type === "tr" && n.props["data-seg"] === 1)[0];
    check(!!findAll(rowT, n => n.type === "button" && n.props["aria-label"] === "Подтвердить")[0],
          "переводчик видит галочку заверения в строке");
    /* Слова, на которые жалуется проверка, приходят с сервера полем
       `attention` и горят СВОИМ классом: «нашлось то, что искал» и «здесь
       дефект» — разные сообщения, и одним цветом они сливаются. */
    const pj = Object.assign({}, project, { segments: project.segments.map(
      x => x.id === 1 ? Object.assign({}, x, { attention: { src: ["кашель"], tgt: ["cough"] } }) : x) });
    const stA = Object.assign({}, storeStub, { activeProject: pj, projects: [pj] });
    hooks.length = 0; hookIdx = 0; effects.length = 0;
    const tA = TabEditor({ store: stA, toast });
    const rowA = findAll(tA, n => n.type === "tr" && n.props["data-seg"] === 1)[0];
    const att = findAll(rowA, n => n.type === "mark")
      .map(m => (m.props.className || "") + ":" + (m.children || []).join(""));
    check(att.join("|") === "hl hl-att:кашель|hl hl-att:cough",
          "жалоба горит своим классом в обеих колонках (" + att.join("|") + ")");
  }

  console.log("\n" + (fail.length ? "ПРОВАЛЕНО: " + fail.join("; ") : "ВСЁ ПРОШЛО"));
  process.exit(fail.length ? 1 : 0);
} catch (e) {
  console.log("РЕНДЕР УПАЛ:", e && e.message);
  console.log((e && e.stack || "").split("\n").slice(0, 8).join("\n"));
  process.exit(1);
}
})();
