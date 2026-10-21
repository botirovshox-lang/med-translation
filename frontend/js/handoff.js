/* Файл, выбранный на ЛЕНДИНГЕ, ждёт человека здесь, пока он регистрируется.

   Зачем. Форма перевода стоит на лендинге (корень simpletranslate.me), а
   перевести файл можно только в приложении, за входом. Без этой передачи
   человек выбирает файл, нажимает «Перевести», проходит регистрацию —
   и на экране «Проекты» выбирает тот же файл ВТОРОЙ раз. Это ровно то
   трение, ради которого форма и поставлена на первый экран.

   Как. Лендинг держит невидимый фрейм `/handoff` (страница ПРИЛОЖЕНИЯ,
   `frontend/handoff.html`) и передаёт ему файл postMessage'ем. Фрейм кладёт
   его в IndexedDB — хранилище ДОМЕНА ПРИЛОЖЕНИЯ, — и после входа приложение
   забирает файл отсюда же. Сервер в передаче не участвует: до регистрации
   файл никуда не уходит, и анонимной двери на запись у сервиса не появляется
   (закон инварианта 35 — единственная неаутентифицированная запись в STATE
   остаётся анкетой).

   Почему IndexedDB, а не localStorage: там только строки, и документ
   на мегабайты туда не лезет. File в IndexedDB кладётся как есть
   (structured clone) во всех живых браузерах.

   Почему это работает во фрейме: лендинг и приложение — ОДИН сайт
   (simpletranslate.me), а браузеры делят хранилище фреймов по сайту
   верхнего окна, не по поддомену. Не сработало (старый Safari, запрет
   хранилища, приватное окно) — ничего не ломается: после входа человек
   выберет файл сам, пара языков всё равно приедет адресом.

   Один файл на два места — страницу `/handoff` и приложение: имена базы
   и срок жизни, записанные дважды, однажды разошлись бы, и файл клали бы
   в одно хранилище, а искали в другом. */
(function () {
  var DB = "mct-handoff", STORE = "pending", KEY = "file";
  // Сутки: человек мог уйти за письмом с кодом и вернуться завтра. Дольше
  // чужой документ лежать в браузере не должен — компьютер бывает общим.
  var TTL_MS = 24 * 3600 * 1000;
  // Тот же потолок, что у сервера (textcount.MAX_BYTES): больший файл сервер
  // всё равно не примет, а класть его в браузер незачем.
  var MAX_BYTES = 32 * 1024 * 1024;
  var CODE_RE = /^[A-Z]{2}(-[A-Z]{4})?$/;

  function open() {
    return new Promise(function (ok, bad) {
      if (!window.indexedDB) return bad(new Error("no indexedDB"));
      var rq;
      try { rq = window.indexedDB.open(DB, 1); } catch (e) { return bad(e); }
      rq.onupgradeneeded = function () { rq.result.createObjectStore(STORE); };
      rq.onsuccess = function () { ok(rq.result); };
      rq.onerror = function () { bad(rq.error || new Error("indexedDB")); };
    });
  }
  function tx(mode, fn) {
    return open().then(function (db) {
      return new Promise(function (ok, bad) {
        var t = db.transaction(STORE, mode), st = t.objectStore(STORE), out;
        var rq = fn(st);
        if (rq) rq.onsuccess = function () { out = rq.result; };
        t.oncomplete = function () { db.close(); ok(out); };
        t.onerror = t.onabort = function () { db.close(); bad(t.error || new Error("tx")); };
      });
    });
  }
  function code(v) {
    var c = String(v || "").toUpperCase();
    return CODE_RE.test(c) ? c : "";
  }

  /* Проверка того, что пришло СНАРУЖИ: сообщение шлёт чужая страница,
     и в хранилище ложится только файл разумного размера и коды языков. */
  function clean(rec) {
    if (!rec || typeof rec !== "object") return null;
    var f = rec.file;
    if (!f || typeof f.size !== "number" || typeof f.name !== "string") return null;
    if (f.size <= 0 || f.size > MAX_BYTES) return null;
    return { file: f, name: f.name.slice(0, 200), src: code(rec.src), tgt: code(rec.tgt), at: Date.now() };
  }

  /* Вернулись с кассы платёжной системы (`/?pay=N`)? Читаем ПРИ ЗАГРУЗКЕ:
     полоса оплаты (PayNeedBar) сразу убирает номер из адреса, а приложение
     спрашивает об этом позже, когда пришли данные. */
  var PAY_BACK = false;
  try { PAY_BACK = /^\d+$/.test(new URLSearchParams(window.location.search).get("pay") || ""); } catch (e) { PAY_BACK = false; }
  var PAID_SS = "mct-paid-at";

  window.MCT_HANDOFF = {
    MAX_BYTES: MAX_BYTES,
    payBack: PAY_BACK,
    /* Оплата прошла (заказ по возврату с кассы стал paid) — время в
       sessionStorage: экран, ждавший оплаты, мог быть не открыт в момент
       события и узнает об этом, когда откроется. */
    markPaid: function () { try { sessionStorage.setItem(PAID_SS, String(Date.now())); } catch (e) {} },
    paidAt: function () { try { return Number(sessionStorage.getItem(PAID_SS) || 0) || 0; } catch (e) { return 0; } },
    clean: clean,
    put: function (rec) {
      var r = clean(rec);
      if (!r) return Promise.reject(new Error("bad"));
      return tx("readwrite", function (st) { return st.put(r, KEY); });
    },
    /* Прочитать, НЕ снимая: файл снимается, только когда проект заведён
       (`drop`). Иначе сбой создания проекта (сеть, 402) терял бы файл. */
    peek: function () {
      return tx("readonly", function (st) { return st.get(KEY); }).then(function (r) {
        if (!r || !r.file) return null;
        if (Date.now() - (r.at || 0) > TTL_MS) { window.MCT_HANDOFF.drop(); return null; }
        return r;
      }, function () { return null; });
    },
    /* Дописать в запись то, что узналось по дороге: номер заведённой папки
       (возврат с кассы не плодит вторую) и отметку «ждём оплату». Файл
       и срок жизни прежние. */
    update: function (patch) {
      return window.MCT_HANDOFF.peek().then(function (r) {
        if (!r) return null;
        var n = {};
        Object.keys(r).forEach(function (k) { n[k] = r[k]; });
        if (patch && patch.folder != null && /^\d+$/.test(String(patch.folder))) n.folder = Number(patch.folder);
        if (patch && "payWait" in patch) { n.payWait = !!patch.payWait; n.waitAt = Date.now(); }
        return tx("readwrite", function (st) { return st.put(n, KEY); });
      }).catch(function () { /* хранилище закрыто — продолжим без памяти */ });
    },
    drop: function () {
      return tx("readwrite", function (st) { return st.delete(KEY); }).catch(function () { /* нечего снимать */ });
    },
    code: code,
  };
})();
