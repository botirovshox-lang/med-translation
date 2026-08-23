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
  // Индекс 2, а не 3: у раскрытой строки (после шага 5 это back-check) шеврон
  // подписан «Свернуть» и в этот список не попадает. Что открылась именно нужная
  // строка, проверяет её собственный маркер «Что чинить» ниже.
  clicks4[2]();
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

  console.log("\n" + (fail.length ? "ПРОВАЛЕНО: " + fail.join("; ") : "ВСЁ ПРОШЛО"));
  process.exit(fail.length ? 1 : 0);
} catch (e) {
  console.log("РЕНДЕР УПАЛ:", e && e.message);
  console.log((e && e.stack || "").split("\n").slice(0, 8).join("\n"));
  process.exit(1);
}
})();
