/* ============================================================
   i18n — язык интерфейса.

   Сборки у фронтенда нет: .jsx грузятся тегами и живут в одной глобальной
   области, поэтому словарь тоже приезжает файлом и кладётся на window.

   Имя `TR`, а не `T`: `T` в tab_preflight.jsx уже занят хелпером подсказок
   (`const T = (title, body) => InfoTip`), а файлы живут в ОДНОЙ глобальной
   области — совпадение имён здесь означает, что подсказка станет переводом
   или наоборот, и увидит это только глаз на экране.

   Три правила, без которых перевод хуже его отсутствия:

   1) НЕТ ПЕРЕВОДА — ПОКАЗЫВАЕМ РУССКИЙ ОРИГИНАЛ. Пустая надпись или
      служебный ключ на экране — это потерянная кнопка: человек не поймёт,
      что она делает, и не найдёт того, что искал. Русская строка хотя бы
      честна. Непереведённое при этом СЧИТАЕТСЯ (window.I18N.misses) —
      иначе про дыры в словаре никто не узнает.

   2) `TR()` — ЧИСТАЯ ФУНКЦИЯ ОТ СТРОКИ-КЛЮЧА, и ключ у нас — сам русский
      текст. Значит на русском языке `TR(s) === s` побитово: включённый
      русский НИЧЕГО не меняет в поведении экрана. Это и есть страховка
      от того, чтобы перевод сломал логику: сравнения, ключи объектов и
      фильтры продолжают работать ровно как раньше.

   3) СМЕНА ЯЗЫКА ПЕРЕЗАГРУЖАЕТ СТРАНИЦУ. Часть надписей вычисляется ОДИН
      раз при загрузке файла (TABS, AUDIT_LABELS, полосы шкалы — это
      константы верхнего уровня), и перерисовкой их не поменять: экран
      остался бы наполовину на прежнем языке, а починить это можно было бы
      только превращением всех таких констант в функции. Перезагрузка
      честнее и дешевле; язык меняют редко и намеренно.

   Язык хранится в ДВУХ местах и это не дублирование: на пользователе
   (`uiLang`, источник правды — он переезжает на другой компьютер) и в
   localStorage (кэш, чтобы экран ВХОДА не мигал чужим языком: до входа
   спросить сервер не у кого).
   ============================================================ */
(function () {
  var LS_KEY = "mct-lang";
  var LANGS = [
    { code: "uz", label: "O‘zbekcha", native: "O‘zbekcha (lotin)" },
    { code: "ru", label: "Русский", native: "Русский" },
  ];
  var DEFAULT_LANG = "uz";
  var catalogs = {};                 // код языка -> { "русская строка": "перевод" }
  var servers = {};                  // то же, но ТОЛЬКО куски сообщений сервера
  var misses = {};                   // непереведённое: строка -> сколько раз спросили
  var phraseRe = null;               // ленивая регулярка для TS(): собирается один раз
  var phraseFor = null;

  var lang = DEFAULT_LANG;
  try {
    var saved = window.localStorage.getItem(LS_KEY);
    if (saved && LANGS.some(function (l) { return l.code === saved; })) lang = saved;
  } catch (e) { /* приватное окно: остаёмся на языке по умолчанию */ }

  function dict() { return catalogs[lang] || null; }
  function srvDict() { return servers[lang] || null; }

  /* Перевод ОДНОЙ строки-ключа. На русском — тождество. */
  function T(s) {
    if (typeof s !== "string" || !s) return s;
    var d = dict();
    if (!d) return s;
    var hit = d[s];
    if (hit !== undefined) return hit;
    misses[s] = (misses[s] || 0) + 1;
    return s;
  }

  /* Сообщение СЕРВЕРА. Оно приходит собранным вместе с числами
     («Месячный лимит расхода организации исчерпан: $1.00 из $2.00»),
     поэтому точного ключа у него нет и быть не может. Здесь — и только
     здесь — идёт подстановка ФРАЗАМИ: самые длинные куски словаря
     заменяются первыми, числа и имена остаются на своих местах.

     Почему это не применяется ко всему подряд: текст ДОКУМЕНТА клиента
     тоже содержит русские слова, и фразовая подстановка изуродовала бы
     перевод, который человек только что оплатил. Поэтому у неё отдельное
     имя и ровно одна точка вызова — граница показа ответа сервера. */
  function TS(s) {
    if (typeof s !== "string" || !s) return s;
    var d = dict(), sd = srvDict();
    if (!d && !sd) return s;
    if (d && d[s] !== undefined) return d[s];
    if (sd && sd[s] !== undefined) return sd[s];
    if (!/[А-Яа-яЁё]/.test(s)) return s;
    if (!sd) { misses[s] = (misses[s] || 0) + 1; return s; }
    if (phraseRe === null || phraseFor !== lang) {
      /* Порога длины здесь НЕТ, и это важно: «Месячный лимит… исчерпан: $1.00
         из $2.00» собран из кусков, и « из $» — пять символов. Порог молча
         оставлял такие куски по-русски посреди узбекской фразы.
         Обойтись без порога можно ровно потому, что таблица здесь СЕРВЕРНАЯ:
         её куски — части конкретных сообщений сервера, а не обрывки надписей
         интерфейса («ин », « с»), которыми подстановка изуродовала бы текст. */
      var keys = Object.keys(sd).filter(function (k) {
        return /[А-Яа-яЁё]/.test(k);
      }).sort(function (a, b) { return b.length - a.length; });
      phraseRe = keys.length
        ? new RegExp(keys.map(function (k) {
            return k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          }).join("|"), "g")
        : /(?!)/g;
      phraseFor = lang;
    }
    var out = s.replace(phraseRe, function (m) { return sd[m] !== undefined ? sd[m] : m; });
    if (out === s) misses[s] = (misses[s] || 0) + 1;
    return out;
  }

  /* Атрибут lang у страницы — не косметика: по нему браузер выбирает
     переносы, а экранная читалка — произношение. Ставится из скрипта, а не
     в index.html, потому что язык у каждого свой. В тестах document —
     заглушка без documentElement, поэтому под try. */
  function markDocument() {
    try { document.documentElement.lang = lang; } catch (e) { /* нет DOM */ }
  }
  markDocument();

  window.I18N = {
    langs: LANGS,
    default: DEFAULT_LANG,
    get lang() { return lang; },
    /* Словарь регистрируется своим файлом (i18n_uz.js). Русского словаря
       нет намеренно: ключ и есть русская строка. */
    register: function (code, table) {
      catalogs[code] = Object.assign(catalogs[code] || {}, table || {});
    },
    /* Куски сообщений СЕРВЕРА — своей таблицей, а не вперемешку с надписями.
       Из неё и только из неё TRS() собирает фразовую подстановку: обрывки
       интерфейса («ин », « с») внутри серверного сообщения дали бы кашу. */
    registerServer: function (code, table) {
      servers[code] = Object.assign(servers[code] || {}, table || {});
      if (code === lang) { phraseRe = null; }
    },
    label: function (code) {
      var l = LANGS.find(function (x) { return x.code === code; });
      return l ? l.native : code;
    },
    /* Смена языка: запомнить и перезагрузить (см. правило 3 выше).
       `silent` — язык приехал с сервера при входе, страница ещё пустая:
       перезагружать нечего, достаточно запомнить. */
    setLang: function (code, silent) {
      if (!LANGS.some(function (l) { return l.code === code; })) return false;
      var same = code === lang;
      lang = code;
      try { window.localStorage.setItem(LS_KEY, code); } catch (e) { /* приватное окно */ }
      phraseRe = null;
      markDocument();
      if (!same && !silent) window.location.reload();
      return true;
    },
    /* Чего не хватает в словаре — списком, для отладки из консоли.
       Молчаливая дыра в переводе неотличима от «так и задумано». */
    misses: function () { return Object.assign({}, misses); },
    missCount: function () { return Object.keys(misses).length; },
  };
  window.TR = T;
  window.TRS = TS;
})();
