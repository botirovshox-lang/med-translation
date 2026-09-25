/* Мини-редактор видео и диалог «субтитры в кадре»: рендер без браузера.
 *
 * Тот же приём, что у test_export_render.js: файлы написаны на
 * React.createElement, и их можно выполнить с заглушкой React. Отличие —
 * здесь ЭФФЕКТЫ выполняются (редактор живёт эффектами: загрузка стартует
 * сама, стиль приходит с сервера, «готово» уходит, когда файл догрузился),
 * а экран перерисовывается руками после каждого события.
 *
 * Числа стиля (умолчание, доли кегля, пределы) и каталог шрифтов берутся
 * у САМОГО media.py — ответ собирается тем же кодом, что у /api/media/fonts,
 * а не второй копией чисел в тесте: копия прятала бы расхождение.
 *
 * Сторожится:
 *   1. редактор сам начинает загрузку и НЕ зовёт «готово» раньше решения
 *      человека (noFinish);
 *   2. обрезка: «Начало здесь» по текущему кадру, итог словами;
 *   3. предпросмотр субтитра поверх видео — шрифт каталога, кегль как у
 *      libass (доля короткой стороны × emRatio), образец на буквах языка;
 *   4. «Подтвердить» до конца загрузки не теряется: «готово» уходит
 *      с обрезкой и стилем, как только файл догрузился;
 *   5. формат, который браузер не показал: кадр и длительность — у сервера;
 *   6. диалог сборки: качество с размером кадра и оценкой времени, кадр
 *      с сервера, сборка уходит с выбранным стилем;
 *   7. экран «Скачать»: две разные строки видео и вход в диалог.
 *
 * Запуск: node tests/test_video_render.js
 */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

/* ── заглушка React с эффектами ─────────────────────────────────── */
let hooks = [], hookIdx = 0, effDeps = [];
const FAKE_EL = { clientWidth: 640, clientHeight: 360 };
const React = {
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
  useEffect(fn, deps) {
    const i = hookIdx++;
    const prev = effDeps[i];
    const changed = !prev || !deps || deps.length !== prev.length || deps.some((d, k) => d !== prev[k]);
    if (changed) { effDeps[i] = deps || []; fn(); }
  },
  /* Элементы DOM у заглушки нет, а размер картинки нужен предпросмотру:
     ref, заведённый пустым, получает «элемент» 640×360. */
  useRef(v) {
    const i = hookIdx++;
    if (!(i in hooks)) hooks[i] = { current: v === null ? FAKE_EL : (v === undefined ? null : v) };
    return hooks[i];
  },
  useMemo(f) { hookIdx++; return f(); },
  useCallback(f) { return f; },
  Fragment: "Fragment",
  createContext(v) { return { _v: v, Provider: "Provider", Consumer: "Consumer" }; },
  useContext() { return { info() {}, warning() {}, error() {}, success() {} }; },
};
const store_ls = { memory: {}, getItem(k) { return this.memory[k] || null; }, setItem(k, v) { this.memory[k] = String(v); }, removeItem(k) { delete this.memory[k]; } };
global.React = React;
Object.assign(global, { useState: React.useState, useEffect: React.useEffect, useRef: React.useRef,
  useMemo: React.useMemo, useCallback: React.useCallback, createContext: React.createContext, useContext: React.useContext });
global.localStorage = store_ls; global.sessionStorage = store_ls;
global.window = global;
global.addEventListener = () => {}; global.removeEventListener = () => {};
global.document = { addEventListener() {}, removeEventListener() {}, querySelector() { return null; } };
global.URL.createObjectURL = () => "blob:local";
global.URL.revokeObjectURL = () => {};
global.BOOT = { v: "test" };

const root = "frontend/js";
for (const f of ["i18n.js", "ui.jsx", "video_edit.jsx", "tab_export_preflight.jsx"]) {
  (0, eval)(fs.readFileSync(path.join(root, f), "utf8") + "\n//# sourceURL=" + f);
}

/* Ответ /api/media/fonts — числа из media.py, покрытие — из каталога, как в main.media_fonts. */
function fontsPayload(lang, script) {
  const py = "import sys, json; sys.path.insert(0, 'backend'); import media; print(json.dumps({"
    + "'style': media.style_clean(None), 'metrics': media.SUB_METRICS, "
    + "'limits': {'size': [media.SIZE_MIN, media.SIZE_MAX], 'margin': [media.MARGIN_MIN, media.MARGIN_MAX]}, "
    + "'sample': media.sub_sample('" + lang + "'), 'fonts': media.fonts_catalog()['fonts']}, ensure_ascii=False))";
  const out = JSON.parse(execFileSync(process.env.PYTHON || "python", ["-c", py],
    { encoding: "utf8", env: Object.assign({}, process.env, { PYTHONIOENCODING: "utf-8" }) }));
  const fonts = out.fonts.map(f => ({ id: f.id, name: f.name, family: f.family, regular: f.regular, bold: f.bold,
    emRatio: f.emRatio, covers: f.scripts.indexOf(script) !== -1 }));
  return Object.assign(out, { fonts, covered: fonts.some(f => f.covers), speed: 1.6, maxBurnMinutes: 120,
    qualities: [{ id: "src", short: 1080 }, { id: "720", short: 720 }, { id: "480", short: 480 }] });
}
const FONTS_UZC = fontsPayload("UZ-CYRL", "CYRILLIC");

function texts(node) {
  const out = [];
  (function walk(n) {
    if (n === null || n === undefined) return;
    if (typeof n === "string" || typeof n === "number") { if (String(n).trim()) out.push(String(n).trim()); return; }
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (typeof n !== "object") return;
    (n.children || []).forEach(walk);
  })(node);
  return out.join(" | ");
}
function find(node, pred) {
  const res = [];
  (function walk(n) {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (pred(n)) res.push(n);
    (n.children || []).forEach(walk);
  })(node);
  return res;
}
const btn = (tree, label) => find(tree, n => n.type === "button" && texts(n).indexOf(label) !== -1)[0];
const tick = () => new Promise(r => setTimeout(r, 0));

(async () => {
  /* ── 1–4. Редактор при загрузке ─────────────────────────────── */
  console.log("=== 1. Загрузка стартует сама, «готово» ждёт человека ===");
  let upload = null, finishBody = null, resolveUpload;
  global.API = {
    safeCall: async (fn) => { try { return await fn(); } catch (e) { return null; } },
    mediaFonts: async (lang) => { check(lang === "UZ-CYRL", "шрифты спрошены под язык перевода"); return FONTS_UZC; },
    uploadMedia: (file, meta, onProg, ctl) => { upload = { file, meta, ctl }; return new Promise(r => { resolveUpload = r; }); },
    mediaFinish: async (token, body) => { finishBody = { token, body }; return { id: 77, media: {} }; },
    mediaUploadProbe: async () => ({ duration: 90, video: { width: 1920, height: 1080 } }),
    mediaUploadPreview: async (token, body) => { global.__prev = body; return "blob:frame"; },
    mediaUploadCancel: async () => ({}),
  };
  let done = null;
  const props = { file: { name: "lecture.mov", size: 5000 }, meta: { title: "lecture", src: "RU", tgt: "UZ-CYRL", domain: "general", folder: 3 },
    onCancel() {}, onDone(p) { done = p; } };
  hooks = []; effDeps = [];
  const draw = () => { hookIdx = 0; return React.createElement(VideoEditor, props); };
  let tree = draw();
  check(upload && upload.ctl.noFinish === true && upload.meta.tgt === "UZ-CYRL" && upload.meta.folder === 3,
        "загрузка началась сразу, без автоматического «готово»");
  await tick(); tree = draw(); tree = draw();
  const video = find(tree, n => n.type === "video")[0];
  check(!!video && video.props.src === "blob:local", "видео играет из памяти вкладки");
  console.log("=== 2. Обрезка ===");
  video.props.onLoadedMetadata({ target: { duration: 125 } });
  tree = draw();
  let t = texts(tree);
  check(t.indexOf("Обрезка") !== -1 && t.indexOf("Возьмём 2:05.0 из 2:05.0") !== -1, "длительность из видео, итог словами");
  find(tree, n => n.type === "video")[0].props.onTimeUpdate({ target: { currentTime: 10, paused: true } });
  tree = draw();
  btn(tree, "Начало здесь").props.onClick();
  tree = draw(); t = texts(tree);
  check(t.indexOf("Возьмём 1:55.0 из 2:05.0") !== -1 && t.indexOf("платите только за этот отрезок") !== -1,
        "«Начало здесь» по текущему кадру: " + (t.match(/Возьмём[^|]*/) || [""])[0]);
  console.log("=== 3. Субтитр поверх видео ===");
  const span = find(tree, n => n.type === "span" && n.props.style && String(n.props.style.fontFamily || "").indexOf("mct-sub-") !== -1)[0];
  const f0 = FONTS_UZC.fonts.find(f => f.id === FONTS_UZC.style.font);
  const want = FONTS_UZC.style.size / 100 * 360 * f0.emRatio;
  check(!!span && span.props.style.fontFamily.indexOf("mct-sub-" + f0.id) !== -1, "шрифт предпросмотра — файл каталога");
  check(!!span && Math.abs(parseFloat(span.props.style.fontSize) - want) < 0.01,
        "кегль как у libass: доля короткой стороны × emRatio (" + (span && span.props.style.fontSize) + ")");
  check(!!span && /[ўқғҳ]/.test(texts(span)), "образец на буквах языка перевода: " + (span && texts(span)));
  check(t.indexOf("Жирный") !== -1 && t.indexOf("Плашка") !== -1 && t.indexOf("Сверху") !== -1, "форма стиля на месте");
  console.log("=== 4. «Подтвердить» до конца загрузки ===");
  btn(tree, "Подтвердить и распознать речь").props.onClick();
  tree = draw();
  check(texts(tree).indexOf("Запустим, как только файл загрузится") !== -1 && !finishBody, "ждём файл, «готово» не ушло");
  resolveUpload({ token: "tok" });
  await tick(); tree = draw(); await tick(); tree = draw(); await tick();
  check(finishBody && finishBody.token === "tok" && finishBody.body.trim && finishBody.body.trim.start === 10
        && finishBody.body.trim.end === 125 && finishBody.body.style && finishBody.body.style.font === f0.id,
        "«готово» ушло с обрезкой и стилем: " + JSON.stringify(finishBody && finishBody.body.trim));
  check(done && done.id === 77, "проект отдан экрану загрузки");

  /* ── 5. Формат, который браузер не показывает ─────────────────── */
  console.log("=== 5. Браузер не показал видео ===");
  hooks = []; effDeps = []; upload = null;
  const props2 = Object.assign({}, props, { file: { name: "old.avi", size: 900 } });
  const draw2 = () => { hookIdx = 0; return React.createElement(VideoEditor, props2); };
  tree = draw2(); await tick(); tree = draw2();
  find(tree, n => n.type === "video")[0].props.onError();
  tree = draw2();
  check(texts(tree).indexOf("Браузер не показывает видео в этом формате") !== -1, "сказано, что кадр нарисует сервер");
  resolveUpload({ token: "tok2" });
  await tick(); tree = draw2(); await tick(); tree = draw2(); await tick(); tree = draw2(); await tick(); tree = draw2();
  t = texts(tree);
  check(t.indexOf("Возьмём 1:30.0 из 1:30.0") !== -1, "длительность — у сервера");
  check(global.__prev && global.__prev.t === 1 && global.__prev.style, "кадр с образцом спрошен у сервера");
  check(find(tree, n => n.type === "img" && n.props.src === "blob:frame").length === 1, "кадр сервера показан");

  /* ── 6. Диалог «субтитры в кадре» ─────────────────────────────── */
  console.log("=== 6. Диалог сборки ===");
  let renderCall = null, started = null, previewBody = null;
  global.API = Object.assign(global.API, {
    mediaFonts: async () => FONTS_UZC,
    mediaBurnInfo: async () => ({ cues: [{ start: 0.5, end: 3, tr: true }, { start: 3.4, end: 6, tr: false }],
      span: 60, trim: null, kept: true, display: [1080, 1920], hdr: true, style: FONTS_UZC.style, tooLong: false,
      maxBurnMinutes: 120, qualities: { src: { frame: [1080, 1920], etaSec: 900 }, "720": { frame: [720, 1280], etaSec: 480 } } }),
    mediaPreview: async (pid, body) => { previewBody = body; return "blob:burnframe"; },
    mediaRender: async (pid, what, voice, extra) => { renderCall = { pid, what, voice, extra }; return { job: { id: 5 }, etaSec: 900 }; },
  });
  hooks = []; effDeps = [];
  const project = { id: 9, tgt: "UZ-CYRL", media: { video: {} } };
  const toast = { info() {}, warning() {}, error() {}, success() {} };
  const draw3 = () => { hookIdx = 0; return React.createElement(VidBurnDialog, { project, toast, onClose() {}, onStarted(j, e) { started = { j, e }; } }); };
  tree = draw3(); await tick(); tree = draw3(); await tick(); tree = draw3();
  await new Promise(r => setTimeout(r, 650)); tree = draw3();
  t = texts(tree);
  check(t.indexOf("Как в оригинале · 1080×1920 · ≈ 15 мин") !== -1 && t.indexOf("720p · 720×1280 · ≈ 8 мин") !== -1,
        "качество с кадром и оценкой времени от сервера");
  check(t.indexOf("1 реплик ещё не переведены") !== -1 && t.indexOf("HDR") !== -1, "названы непереведённое и HDR");
  check(previewBody && Math.abs(previewBody.t - 1.75) < 1e-9 && previewBody.style, "кадр спрошен на первой переведённой реплике");
  check(find(tree, n => n.type === "img" && n.props.src === "blob:burnframe").length === 1, "кадр с сервера показан");
  btn(tree, "Подтвердить и собрать").props.onClick();
  await tick();
  check(renderCall && renderCall.what === "burn" && renderCall.extra.quality === "src" && renderCall.extra.style.font === FONTS_UZC.style.font,
        "сборка ушла с выбранным стилем и качеством");
  check(started && started.e === 900, "экран «Скачать» узнал задачу и оценку");

  /* ── 6б. Отмена и закрытие окна во время загрузки ─────────────── */
  console.log("=== 6б. Отмена и закрытие окна ===");
  let deleted = null, finished = null, gotProject = null;
  global.API = Object.assign(global.API, {
    mediaFonts: async () => FONTS_UZC,
    uploadMedia: (file, meta, onProg, ctl) => { ctl.token = "tokX"; upload = { ctl }; return new Promise(r => { resolveUpload = r; }); },
    mediaUploadCancel: async (tok) => { deleted = tok; return {}; },
    mediaFinish: async (tok, body) => { finished = tok; return { id: 88 }; },
  });
  let cancelled = false;
  const p5 = Object.assign({}, props, { onCancel() { cancelled = true; }, onDone(p) { gotProject = p; } });
  const draw5 = () => { hookIdx = 0; return React.createElement(VideoEditor, p5); };
  hooks = []; effDeps = [];
  tree = draw5(); await tick(); tree = draw5(); tree = draw5();
  btn(tree, "Отменить").props.onClick();
  check(deleted === "tokX" && upload.ctl.cancelled && cancelled, "«Отменить» посреди загрузки удаляет её на сервере");
  hooks = []; effDeps = []; finished = null;
  tree = draw5(); await tick(); tree = draw5(); tree = draw5();
  btn(tree, "Подтвердить и распознать речь").props.onClick();
  /* окно закрыли (Esc), экран размонтирован — подтверждённая загрузка
     обязана дойти до проекта */
  find(tree, n => n.type === "button" && n.props["aria-label"] === "Закрыть")[0].props.onClick();
  check(!upload.ctl.stopped, "подтверждённую загрузку закрытие окна не останавливает");
  resolveUpload({ token: "tokX" });
  await tick(); await tick();
  check(finished === "tokX" && gotProject && gotProject.id === 88, "«готово» ушло и после закрытия окна");

  /* ── 7. Экран «Скачать» ──────────────────────────────────────── */
  console.log("=== 7. Экран «Скачать» ===");
  hooks = []; effDeps = [];
  global.API = Object.assign(global.API, { mediaVoices: async () => ({ voices: [] }), listJobs: async () => ({ active: [] }) });
  const vp = { id: 9, tgt: "UZ-CYRL", title: "L", mediaStatus: "ready", media: { video: { width: 1920, height: 1080 }, kept: true },
    mediaRender: { burn: { at: "2026-09-25 12:00", size: 1048576 * 3, width: 1280, height: 720, untranslated: 2 } },
    segments: [{ id: 1, source: "а", target: "b" }] };
  const draw4 = () => { hookIdx = 0; return React.createElement(ExpMediaCard, { project: vp, store: { replaceProject() {} }, toast }); };
  tree = draw4(); t = texts(tree);
  check(t.indexOf("Видео с субтитрами в кадре") !== -1 && t.indexOf("Видео с субтитрами дорожкой") !== -1, "два вида видео названы по-разному");
  check(t.indexOf("1280×720") !== -1 && t.indexOf("2 реплик были без перевода") !== -1, "у собранного — кадр и непереведённое");
  btn(tree, "Настроить и собрать заново").props.onClick();
  tree = draw4();
  check(texts(tree).indexOf("Субтитры в кадре") !== -1, "кнопка открывает диалог сборки");

  const imp = fs.readFileSync(path.join(root, "tab_import.jsx"), "utf8");
  check(/React\.createElement\(VideoEditor,/.test(imp), "экран загрузки открывает мини-редактор");

  console.log(fail.length ? "\nПРОВАЛЕНО: " + fail.length : "\nВСЁ ПРОШЛО");
  process.exit(fail.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
