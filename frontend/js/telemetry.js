/* Ошибки JS и открытые экраны → сервер (`POST /api/client/beacon`).
 *
 * Грузится ПЕРВЫМ, раньше React: самая дорогая ошибка — та, после которой
 * не нарисовался экран входа, и ловить её надо до того, как она случится.
 * Зависимостей нет ни от одного файла приложения.
 *
 * Что уходит: вид ошибки, имя файла, строка и столбец, обрезанное сообщение
 * и стек, открытая вкладка, версия статики. Текста документов клиента тут
 * нет и быть не должно: перехватываются только ошибки КОДА, а экраны
 * называются ключом вкладки (инвариант 34, п. 7).
 *
 * Отправка — пачкой раз в несколько секунд и при уходе со страницы
 * (`keepalive`), не больше MAX_PAGE ошибок за жизнь страницы и без повторов
 * одной и той же: ошибка в цикле отрисовки иначе засыпала бы сервер. */
(function () {
  var URL = "/api/client/beacon";
  var MAX_PAGE = 30, DELAY = 4000;
  var q = { errors: [], ui: [] }, sent = 0, seen = {}, timer = null, lastUi = "";

  function token() {
    try { return window.sessionStorage.getItem("mct-token") || ""; } catch (e) { return ""; }
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
  function flush() {
    timer = null;
    if (!q.errors.length && !q.ui.length) return;
    var body = JSON.stringify({ errors: q.errors.splice(0, 10), ui: q.ui.splice(0, 40) });
    var h = { "Content-Type": "application/json" };
    var t = token();
    if (t) h["Authorization"] = "Bearer " + t;
    try {
      window.fetch(URL, { method: "POST", headers: h, body: body, keepalive: true, credentials: "same-origin" })
        .catch(function () { /* сервер недоступен — наблюдение не вправе мешать */ });
    } catch (e) { /* старый браузер без fetch: молчим */ }
    if (q.errors.length || q.ui.length) schedule();
  }
  function schedule() { if (!timer) timer = setTimeout(flush, DELAY); }

  function report(kind, file, line, col, msg, stack) {
    var key = kind + "|" + file + "|" + line + "|" + String(msg).slice(0, 80);
    if (seen[key] || sent >= MAX_PAGE) return;
    seen[key] = 1; sent++;
    q.errors.push({
      kind: kind, file: file, line: line || 0, col: col || 0,
      msg: String(msg || "").slice(0, 300), stack: String(stack || "").slice(0, 1200),
      screen: window._mcat_tab || "", ver: (window.BOOT && window.BOOT.v) || "",
    });
    schedule();
  }

  /* Фаза ПЕРЕХВАТА: ошибка загрузки <script> не всплывает, и без неё
     не поймать самый частый белый экран — «файл не доехал». */
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

  window.addEventListener("pagehide", flush);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") flush();
  });

  window.TELEMETRY = {
    /* Экран или шаг знакомства. Код — из закрытого списка сервера
       (`UI_EVENTS`); чужой там молча выбросят. Повтор подряд не шлём. */
    ui: function (code) {
      if (!code || code === lastUi) return;
      lastUi = code;
      if (q.ui.length < 200) q.ui.push(String(code));
      schedule();
    },
    /* Ошибка, пойманная кодом (рамка падения экрана). */
    error: function (kind, err) {
      var stack = err && err.stack;
      report(kind || "error", fileOfStack(stack) || "other", 0, 0,
             (err && err.message) || String(err), stack);
    },
    flush: flush,
  };
})();
