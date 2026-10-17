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
    exitSettle();
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
  /* Сигнал по кнопке — ОДИН раз за сессию страницы на (экран, надпись, вид):
     счёт «сессиями», а не кликами одного раздражённого человека
     (рейтинг затруднений на сервере делит именно сессии). */
  var once = {};
  function push1(kind, tab, c, extra) {
    var key = kind + (extra && extra.rage ? "!" : "") + "|" + tab + "|" + (c[0] || "") + "|" + ((extra && extra.s) || "");
    if (once[key] || clicksSeen >= MAX_CLICKS_PAGE) return;
    once[key] = 1; clicksSeen++;
    var rec = { t: tab, c: c };
    if (kind !== "click") rec.kind = kind;
    if (extra) for (var k in extra) rec[k] = extra[k];
    q.clicks.push(rec);
    schedule();
  }

  /* «Нервный» клик — как у PostHog: 3 нажатия за 1 с в пределах 30 px.
     Кнопки листания и счётчики «+/−» жмут подряд законно — не считаем. */
  var RAGE_IGNORE = /^(Далее|Назад|Вперёд|Ещё|Следующая|Предыдущая|[+−\-‹›«»<>]|\d+)$/;
  var burst = [];

  /* Клик без отклика: за 1 с после нажатия на экране ничего не изменилось
     (ни DOM, ни прокрутки, ни фокуса) и запроса к серверу не было.
     Наблюдатель включается ТОЛЬКО на эту секунду: на таблице в 2700 строк
     постоянный наблюдатель стоил бы тысяч вызовов. Не считаем то, что
     законно не меняет экран: выбор файла, скачивание, новая вкладка,
     переход по ссылке, раскрывашки, погашенные кнопки, поля. */
  var lastClick = null;          // для привязки отказа сервера к нажатию
  function quiet(el) {
    if (!el || !el.matches) return true;
    if (el.disabled || el.getAttribute("aria-disabled") === "true") return true;
    if (el.matches("input, select, textarea, label, a[target], a[download], [aria-haspopup], summary")) return true;
    if (el.closest && el.closest("label")) return true;
    var href = el.getAttribute && el.getAttribute("href");
    if (href && href.charAt(0) !== "#") return true;
    return false;
  }
  function watchDead(el, tab, c) {
    if (!window.MutationObserver || quiet(el) || !c.length) return;
    var alive = false, mo = null;
    var sy = window.scrollY, act = document.activeElement;
    var mark = function () { alive = true; if (mo) { mo.disconnect(); mo = null; } };
    try {
      mo = new window.MutationObserver(mark);
      mo.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
    } catch (e) { return; }
    lastClick.mark = mark;
    setTimeout(function () {
      if (mo) { mo.disconnect(); mo = null; }
      if (!alive && window.scrollY === sy && document.activeElement === act) push1("dead", tab, c);
    }, 1000);
  }

  document.addEventListener("click", function (ev) {
    try {
      var el = ev.target && ev.target.closest &&
        ev.target.closest("button, a, [role=button], [role=tab], summary, .navi");
      if (!el) return;
      var tab = screen();
      if (!tab) return;
      var c = cands(el);
      var t = now(), x = ev.clientX || 0, y = ev.clientY || 0;
      /* Серия — по одному и тому же элементу: соседняя кнопка в 30 px
         серию не продолжает, иначе быстрые нажатия по разным кнопкам
         пропадали бы как «повторы». */
      burst = burst.filter(function (b) {
        return b.el === el && t - b.at < 1000 && Math.abs(b.x - x) <= 30 && Math.abs(b.y - y) <= 30;
      });
      burst.push({ at: t, x: x, y: y, el: el });
      lastClick = { at: t, tab: tab, c: c };
      if (burst.length >= 3 && c.length && !RAGE_IGNORE.test(c[0])) {
        push1("click", tab, c, { rage: true });
        burst = [];
        return;
      }
      if (burst.length > 1) return;   // повторы серии — не новые нажатия
      push1("click", tab, c);
      watchDead(el, tab, c);
    } catch (e) { /* учёт не вправе ломать нажатие */ }
  }, true);

  /* Отказ сервера, привязанный к нажатию. api.js спрашивает `claim()` в
     момент СТАРТА запроса: привязываем только запросы, начатые в первые
     300 мс после клика, — фоновые опросы (задачи, разбор) стартуют по
     таймеру и к нажатию не прилипают. Запрос сам по себе — уже отклик:
     клик с запросом «без отклика» не бывает. */
  function claim() {
    var lc = lastClick;
    if (!lc || now() - lc.at > 300) return null;
    if (lc.mark) lc.mark();
    return lc;
  }
  function failed(ctx, status) {
    if (!ctx || status === 401 || status === 429) return;
    push1("fail", ctx.tab, ctx.c, { s: status });
  }

  /* Уход со страницы — с какой вкладки и успел ли человек получить перевод
     (`exit.<вкладка>.ok|none`). На телефоне `pagehide` ненадёжен, а
     «скрыта» бывает и на минуту (переключился в другое приложение), поэтому
     уход откладывается в localStorage и считается, только если человек
     не вернулся за 30 минут (сессия Mixpanel/Amplitude): при следующем
     заходе или возврате отложенный уход либо уходит, либо снимается. */
  var EXIT_KEY = "mct-exit", SESSION_MS = 30 * 60 * 1000, gotValue = false;
  try { gotValue = sessionStorage.getItem("mct-got") === "1"; } catch (e) { /* приватное окно */ }
  function exitCode() {
    var tb = window._mcat_tab;
    return tb && token() ? "exit." + tb + "." + (gotValue ? "ok" : "none") : "";
  }
  function exitPark() {
    var c = exitCode();
    if (!c) return;
    /* Номер пользователя — чтобы уход засчитался ТОМУ ЖЕ человеку: на общем
       компьютере следующий вошедший — другой. Токен не годится: он живёт
       в sessionStorage и после закрытия вкладки новый. */
    var u = window._mcat_uid;
    if (!u) return;
    try { localStorage.setItem(EXIT_KEY, JSON.stringify({ c: c, at: now(), u: String(u) })); } catch (e) { /* приватное окно */ }
  }
  /* Разбирается, когда известно, кто сейчас вошёл (`_mcat_uid` ставит
     приложение после /auth/me), — до этого отложенный уход ждёт. */
  function exitSettle() {
    try {
      var p = JSON.parse(localStorage.getItem(EXIT_KEY) || "null");
      if (!p) return;
      var me = window._mcat_uid;
      if (now() - p.at < SESSION_MS) {
        if (visible()) localStorage.removeItem(EXIT_KEY);   // вернулся — не уход
        return;
      }
      if (!me || !token()) return;                           // ещё не знаем, кто вошёл
      localStorage.removeItem(EXIT_KEY);
      if (p.c && p.u === String(me)) { lastUi = ""; ui(p.c); }
    } catch (e) { /* приватное окно */ }
  }

  /* Откуда пришли: страница лендинга из `?from=` или переход с лендинга. */
  /* Метка живёт в sessionStorage: между приходом и регистрацией человек
     переключает экраны входа, а регистрация уносит её на сервер
     (`srcPage`). Событие прихода — только в момент самого прихода. */
  var entry = "", arrived = false;
  try {
    var fq = new URLSearchParams(location.search || "").get("from");
    if (fq) { entry = /^(index|uz|en|start)$/.test(fq) ? fq : "other"; arrived = true; }
    else if (/^https:\/\/click\.simpletranslate\.me/.test(document.referrer || "")) { entry = "landing"; arrived = true; }
    /* Перезагрузка (смена языка, F5) с тем же `?from=` — не новый приход. */
    if (arrived && sessionStorage.getItem("mct-entry-sent")) arrived = false;
    if (entry) sessionStorage.setItem("mct-entry", entry);
    else entry = sessionStorage.getItem("mct-entry") || "";
    if (arrived) sessionStorage.setItem("mct-entry-sent", "1");
  } catch (e) { /* приватное окно */ }
  if (arrived) setTimeout(function () { lastUi = ""; ui("entry." + entry); }, 0);

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

  window.addEventListener("pagehide", function () { exitPark(); flush(); });
  document.addEventListener("visibilitychange", function () {
    if (!visible()) { stopDwell(); exitPark(); flush(); } else { startDwell(); exitSettle(); }
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
    /* api.js: привязка отказа к нажатию (см. claim/failed выше). */
    claim: claim,
    failed: failed,
    /* Человек получил ценность (скачал перевод): уход после этого — успех. */
    success: function () {
      gotValue = true;
      try { sessionStorage.setItem("mct-got", "1"); } catch (e) { /* приватное окно */ }
    },
    /* Откуда пришёл — регистрация уносит это на сервер. */
    entry: function () { return entry; },
  };
})();
