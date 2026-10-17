/* Поведение в приложении → сервер (`POST /api/client/beacon`, инвариант 34, п. 17).
 *
 * Грузится ПЕРВЫМ, раньше React: самая дорогая ошибка — та, после которой
 * не нарисовался экран входа, и ловить её надо до того, как она случится.
 * Зависимостей нет ни от одного файла приложения (I18N спрашивается, когда
 * он уже есть).
 *
 * Что уходит:
 *   * ошибки кода: вид, файл, строка, обрезанные сообщение и стек;
 *   * экраны (`ui`): вкладки, шаги знакомства, экраны входа, устройство, язык;
 *   * клики — НАДПИСЬЮ кнопки, переведённой обратно в русский ключ словаря.
 *     Сервер принимает только надписи из словаря интерфейса, поэтому текст
 *     документа клиента в учёт не попадает, даже если он стоит на кнопке;
 *   * «нервные» клики: три нажатия по одному элементу за 1,2 с;
 *   * время на каждой вкладке (только пока вкладка браузера видна);
 *   * скорость: загрузка страницы и появление первого экрана.
 *
 * Отправка — пачкой раз в несколько секунд и при уходе со страницы
 * (`keepalive`). Потолки на страницу и на пачку: тело обязано влезть
 * в потолок сервера (BEACON_MAX_BYTES), иначе пачка пропала бы целиком. */
(function () {
  var URL = "/api/client/beacon";
  var MAX_PAGE = 30, MAX_CLICKS_PAGE = 600, DELAY = 4000;
  var q = { errors: [], ui: [], clicks: [] }, sent = 0, clicksSeen = 0, seen = {}, timer = null, lastUi = "";
  var perf = {}, perfReady = false;
  var curTab = null, since = 0, dwell = {};
  var t0 = Date.now();

  function now() { return Date.now(); }
  function token() {
    try { return window.sessionStorage.getItem("mct-token") || ""; } catch (e) { return ""; }
  }
  function visible() {
    try { return document.visibilityState !== "hidden"; } catch (e) { return true; }
  }
  function fileOf(u) {
    var s = String(u || "").split("?")[0].split("#")[0];
    return s.slice(s.lastIndexOf("/") + 1) || "inline";
  }
  /* Файл ошибки, у которой нет `filename` (отклонённый промис), — первая
     строка стека, указывающая на наш каталог js/. */
  function fileOfStack(stack) {
    var m = /\/js\/([A-Za-z0-9_.]+)/.exec(String(stack || ""));
    return m ? m[1] : "";
  }
  /* Экран для клика: до входа — «auth», после — открытая вкладка. */
  function screen() { return token() ? (window._mcat_tab || "") : "auth"; }

  function stopDwell() {
    if (curTab && since) dwell[curTab] = (dwell[curTab] || 0) + (now() - since);
    since = 0;
  }
  function startDwell() { if (curTab && visible()) since = now(); }

  function flush() {
    timer = null;
    stopDwell(); startDwell();
    var dw = null;
    for (var k in dwell) { if (dwell[k] > 500) { dw = dw || {}; dw[k] = Math.round(dwell[k]); } }
    var hasPerf = perf.load || perf.ready;
    if (!q.errors.length && !q.ui.length && !q.clicks.length && !dw && !hasPerf) return;
    var payload = { errors: q.errors.splice(0, 5), ui: q.ui.splice(0, 40), clicks: q.clicks.splice(0, 25) };
    /* Время на экранах — только с токеном: сервер без сессии его не берёт,
       а сброшенное здесь пропало бы. */
    if (dw && token()) { payload.dwell = dw; dwell = {}; }
    if (hasPerf) { payload.perf = perf; perf = {}; }
    var h = { "Content-Type": "application/json" };
    var t = token();
    if (t) h["Authorization"] = "Bearer " + t;
    try {
      window.fetch(URL, { method: "POST", headers: h, body: JSON.stringify(payload),
                          keepalive: true, credentials: "same-origin" })
        .catch(function () { /* сервер недоступен — наблюдение не вправе мешать */ });
    } catch (e) { /* старый браузер без fetch: молчим */ }
    if (q.errors.length || q.ui.length || q.clicks.length) schedule();
  }
  function schedule() { if (!timer) timer = setTimeout(flush, DELAY); }

  function report(kind, file, line, col, msg, stack) {
    var key = kind + "|" + file + "|" + line + "|" + String(msg).slice(0, 80);
    if (seen[key] || sent >= MAX_PAGE) return;
    seen[key] = 1; sent++;
    q.errors.push({
      kind: kind, file: file, line: line || 0, col: col || 0,
      msg: String(msg || "").slice(0, 300), stack: String(stack || "").slice(0, 800),
      screen: window._mcat_tab || "", ver: (window.BOOT && window.BOOT.v) || "",
    });
    schedule();
  }

  function ui(code) {
    if (!code || code === lastUi) return;
    lastUi = code;
    code = String(code);
    if (code.indexOf("tab.") === 0) {
      stopDwell(); curTab = code.slice(4); startDwell();
    }
    /* Первый экран (вход или вкладка) — мера «сколько ждал человек». */
    if (!perfReady && (code.indexOf("tab.") === 0 || code.indexOf("auth.") === 0)) {
      perfReady = true;
      perf.ready = now() - t0;
    }
    if (q.ui.length < 200) q.ui.push(code);
    schedule();
  }

  /* Ошибки. Фаза ПЕРЕХВАТА: ошибка загрузки <script> не всплывает, и без
     неё не поймать самый частый белый экран — «файл не доехал». */
  window.addEventListener("error", function (ev) {
    var t = ev && ev.target;
    if (t && t !== window && (t.src || t.href)) {
      report("load", fileOf(t.src || t.href), 0, 0, "не загрузился", "");
      return;
    }
    var err = ev && ev.error;
    report("error", fileOf(ev && ev.filename), ev && ev.lineno, ev && ev.colno,
           (ev && ev.message) || (err && err.message) || "error", err && err.stack);
  }, true);

  window.addEventListener("unhandledrejection", function (ev) {
    var r = ev && ev.reason;
    /* Отказ сервера (у ошибки api.js есть `status`) — не ошибка кода:
       его уже посчитал сервер, а повтор здесь удвоил бы счёт. */
    if (r && typeof r === "object" && "status" in r) return;
    var stack = r && r.stack;
    report("rejection", fileOfStack(stack) || "other", 0, 0,
           (r && r.message) || String(r), stack);
  });

  /* Клики. Надпись — aria-label, title или текст элемента; кандидатов
     несколько, потому что в надписи бывает число («Применить к 12 сегм.»):
     сервер возьмёт первый, что есть в словаре. */
  function norm(s) { return String(s || "").replace(/\s+/g, " ").trim(); }
  function strip(s) { return norm(s).replace(/^[^0-9A-Za-zА-Яа-яЁёЀ-ӿʻʼ‘’«(]+|[^0-9A-Za-zА-Яа-яЁёЀ-ӿʻʼ‘’»).…?!]+$/g, ""); }
  function cands(el) {
    var raw = el.getAttribute && (el.getAttribute("aria-label") || el.getAttribute("title"));
    var text = norm(raw || el.textContent || "");
    if (!text || text.length > 200) return [];
    var out = [], push = function (s) {
      s = strip(s);
      if (!s) return;
      var k = (window.I18N && window.I18N.toKey) ? window.I18N.toKey(s) : s;
      k = String(k).slice(0, 80);
      if (out.indexOf(k) < 0) out.push(k);
    };
    push(text);
    push(text.split(" · ")[0]);
    push(text.replace(/\s*[\d$№#].*$/, ""));
    /* Номер шага в меню стоит ПЕРЕД названием («1Проекты»). */
    push(text.replace(/\d+/g, " "));
    return out.slice(0, 4);
  }
  var last = { el: null, n: 0, at: 0, raged: false };
  document.addEventListener("click", function (ev) {
    try {
      var el = ev.target && ev.target.closest &&
        ev.target.closest("button, a, [role=button], [role=tab], summary, .navi");
      if (!el || clicksSeen >= MAX_CLICKS_PAGE) return;
      var t = now();
      if (last.el === el && t - last.at < 1200) { last.n++; } else { last = { el: el, n: 1, at: t, raged: false }; }
      last.at = t;
      var tab = screen();
      if (!tab) return;
      var c = cands(el);
      var rage = last.n >= 3 && !last.raged;
      if (rage) last.raged = true;
      /* Повторные клики пачки рисуем одним «нервным», а не тремя обычными. */
      if (last.n > 1 && !rage) return;
      clicksSeen++;
      q.clicks.push({ t: tab, c: c, rage: rage });
      schedule();
    } catch (e) { /* учёт не вправе ломать нажатие */ }
  }, true);

  /* Скорость загрузки, устройство и язык — один раз на страницу. */
  window.addEventListener("load", function () {
    try {
      var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
      var ms = nav ? (nav.loadEventStart || nav.duration) : (Date.now() - t0);
      if (ms > 0) { perf.load = Math.round(ms); schedule(); }
    } catch (e) { /* нет Performance API */ }
    var w = window.innerWidth || 1024;
    ui(w <= 640 ? "env.phone" : w <= 1100 ? "env.tablet" : "env.desktop");
    lastUi = "";
    try { if (window.I18N) ui("lang." + window.I18N.lang); } catch (e) { /* нет словаря */ }
    lastUi = "";
  });

  window.addEventListener("pagehide", flush);
  document.addEventListener("visibilitychange", function () {
    if (!visible()) { stopDwell(); flush(); } else { startDwell(); }
  });

  window.TELEMETRY = {
    /* Экран, шаг знакомства, экран входа… Код — из закрытого списка сервера
       (`UI_EVENTS`); чужой там молча выбросят. Повтор подряд не шлём. */
    ui: ui,
    /* Ошибка, пойманная кодом (рамка падения экрана). */
    error: function (kind, err) {
      var stack = err && err.stack;
      report(kind || "error", fileOfStack(stack) || "other", 0, 0,
             (err && err.message) || String(err), stack);
    },
    flush: flush,
  };
})();
