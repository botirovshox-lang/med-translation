/* Учёт поведения на лендинге → НАШ сервер (инвариант 34, п. 19).
 *
 * Считает то, что отвечает на вопрос «где человек бросает лендинг»:
 *   * просмотр страницы и скорость её загрузки;
 *   * глубину прокрутки 25/50/75/100 — каждую отметку один раз;
 *   * нажатия на кнопки (`data-cta`, ссылки в приложение, якоря, языки,
 *     вкладки примеров, вопросы FAQ);
 *   * воронку формы: выбрал файл → нажал «Перевести» → какая ошибка →
 *     доехал ли файл в приложение;
 *   * уход: до какой глубины дочитал и успел ли отправить форму.
 *
 * Коды — из закрытого списка сервера (`LAND_EVENTS`): чужое там выбросят,
 * поэтому никакой текст страницы и ничего из полей формы сюда не попадает.
 * Те же события уходят целями в Яндекс.Метрику — ради Вебвизора и сегментов;
 * ЧИСЛА берём со своего сервера (у двух счётчиков числа всегда расходятся).
 *
 * Отправка — на тот же адрес (`/api/client/beacon` проксирует nginx лендинга),
 * `text/plain`, чтобы не было предварительного запроса, пачкой и при уходе. */
(function () {
  var URL = "/api/client/beacon";
  var path = location.pathname || "/";
  var PAGE = /^\/start\//.test(path) ? "start" : /^\/uz\//.test(path) ? "uz"
           : /^\/en\//.test(path) ? "en" : (path === "/" || path === "/index.html") ? "index" : "other";
  var q = [], timer = null, sent = {}, maxScroll = 0, submitted = false, left = false;

  function ym(goal) {
    try { if (window.ym && window.METRIKA_ID) window.ym(window.METRIKA_ID, "reachGoal", goal); } catch (e) { /* нет счётчика */ }
  }
  function flush() {
    timer = null;
    if (!q.length) return;
    var body = JSON.stringify({ land: q.splice(0, 30) });
    try {
      fetch(URL, { method: "POST", headers: { "Content-Type": "text/plain" }, body: body,
                   keepalive: true, credentials: "omit" }).catch(function () {});
    } catch (e) { /* старый браузер */ }
    if (q.length) schedule();
  }
  function schedule() { if (!timer) timer = setTimeout(flush, 3000); }
  /* once — событие, которое на странице бывает ОДИН раз (отметка прокрутки,
     уход): повтор не шлётся, и счёт выходит «людьми», а не нажатиями. */
  function ev(code, once) {
    if (once) { if (sent[code]) return; sent[code] = 1; }
    if (q.length < 120) q.push(code);
    schedule();
  }

  ev("view:" + PAGE, true);
  ym("land_view");

  window.addEventListener("load", function () {
    try {
      var nav = performance.getEntriesByType("navigation")[0];
      var ms = nav ? (nav.loadEventStart || nav.duration) : 0;
      if (ms > 0) ev("perf:" + (ms < 1000 ? "lt1" : ms < 3000 ? "1to3" : ms < 7000 ? "3to7" : "gt7"), true);
    } catch (e) { /* нет Performance API */ }
  });

  function onScroll() {
    var h = document.documentElement.scrollHeight - window.innerHeight;
    var p = h > 0 ? (window.scrollY || window.pageYOffset || 0) / h : 1;
    [25, 50, 75, 100].forEach(function (m) {
      if (p * 100 >= m - 2 && maxScroll < m) {
        maxScroll = m;
        ev("scroll:" + m, true);
        ym("land_scroll_" + m);
      }
    });
  }
  window.addEventListener("scroll", onScroll, { passive: true });

  /* Что нажали. Порядок проверок — от точного к общему. */
  var APP = /^https:\/\/(www\.)?simpletranslate\.(me|uz)(\/|$)/;
  document.addEventListener("click", function (e) {
    var el = e.target && e.target.closest && e.target.closest("a, button, summary, [role=tab]");
    if (!el) return;
    var cta = el.getAttribute("data-cta");
    if (cta) { ev("cta:" + cta); ym("land_cta_" + cta); return; }
    if (el.tagName === "SUMMARY") {
      var all = Array.prototype.slice.call(document.querySelectorAll("#faq summary, .faq summary"));
      var i = all.indexOf(el);
      if (i >= 0 && !(el.parentNode && el.parentNode.open)) ev("faq:" + Math.min(i + 1, 20));
      return;
    }
    var k = el.getAttribute("data-k");
    if (el.getAttribute("role") === "tab" && k) { ev("tab:" + k); return; }
    if (el.closest("#lens-pick")) {
      var btns = Array.prototype.slice.call(document.querySelectorAll("#lens-pick button"));
      ev("lens:" + Math.max(0, Math.min(btns.indexOf(el), 9)));
      return;
    }
    var href = el.getAttribute("href") || "";
    var hl = el.getAttribute("hreflang");
    if (hl) { ev("lang:" + hl.slice(0, 2)); return; }
    if (el.id === "login") { ev("cta:login"); return; }
    if (APP.test(href)) { ev("cta:app"); ym("land_cta_app"); return; }
    if (href.charAt(0) === "#") { ev("cta:anchor"); return; }
  }, true);

  /* Форма: файл, отправка, ошибка, передача файла. Ошибку узнаём по тому,
     какой из data-* текстов встал в #tr-err: ключи закрыты списком. */
  var fileIn = document.getElementById("tr-file");
  if (fileIn) fileIn.addEventListener("change", function () { ev("form.file", true); });
  var form = document.getElementById("tr");
  if (form) form.addEventListener("submit", function () { submitted = true; ev("form.submit", true); }, true);
  var errEl = document.getElementById("tr-err");
  if (errEl && window.MutationObserver) {
    new MutationObserver(function () {
      if (errEl.hidden || !errEl.textContent) return;
      var key = "other", t = errEl.textContent;
      ["big", "tgt", "same", "busy"].forEach(function (n) { if (errEl.getAttribute("data-" + n) === t) key = n; });
      if (key !== "busy") ev("form.err:" + key, true);
    }).observe(errEl, { childList: true, characterData: true, subtree: true, attributes: true });
  }

  /* Уход: до какой глубины дочитал и отправил ли форму. Один раз за
     страницу; `visibilitychange` надёжнее `pagehide` на телефоне. */
  function leave() {
    if (left) return;
    left = true;
    ev("leave:" + maxScroll + ":" + (submitted ? "sub" : "nosub"));
    flush();
  }
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "hidden") leave(); });
  window.addEventListener("pagehide", leave);

  window.LANDTRACK = {
    page: PAGE,
    /* Цели скрипта формы (`tr_handoff_ok` и пр.) — и в Метрику, и сюда. */
    goal: function (name) {
      if (name === "tr_handoff_ok") ev("form.handoff_ok", true);
      else if (name === "tr_handoff_fail") ev("form.handoff_fail", true);
    },
    /* Ошибка формы по ключу её текста (страница /start/ пишет текст сама,
       а не из data-атрибута). «Занято» — не ошибка, а ожидание. */
    err: function (key) {
      var m = { eBig: "big", eTgt: "tgt", eSame: "same" }[key];
      if (m) ev("form.err:" + m, true);
    },
  };
})();
