/* Словарь интерфейса: полнота и честность.
 *
 * Перевод, у которого нет теста на полноту, — это перевод наполовину:
 * дыра в словаре выглядит на экране как русская строка среди узбекских,
 * и заметит её не разработчик, а клиент.
 *
 * Что сторожится:
 *   1. КАЖДЫЙ аргумент TR(...) в коде есть в словаре. Не найден — назван
 *      поимённо, а не спрятан в счётчике;
 *   2. в словаре нет МУСОРА — ключей, которых в коде уже нет: такие
 *      накапливаются после каждой правки экрана и создают ложное
 *      ощущение, что переведено больше, чем на самом деле;
 *   3. пробелы по краям СОХРАНЕНЫ: строки склеиваются с числами
 *      («Повторов: » + n), и съеденный пробел слепляет слово с цифрой;
 *   4. перенос строки и неразрывный пробел сохранены — они держат
 *      вёрстку подсказок;
 *   5. перевод НЕ РАВЕН оригиналу без причины: скопированная русская
 *      строка в словаре выглядит переведённой, а на экране — нет.
 *      Исключения (латиница, числа, знаки) перечислены явно;
 *   6. русских букв в переводе не осталось.
 *
 * Запуск: node tests/test_i18n.js
 */
const fs = require("fs");
const path = require("path");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

const root = process.argv[2] || "frontend/js";
global.window = global;
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
(0, eval)(fs.readFileSync(path.join(root, "i18n.js"), "utf8"));
(0, eval)(fs.readFileSync(path.join(root, "i18n_uz.js"), "utf8"));

/* Ключи из кода — тем же чтением исходников, что и сборщик словаря.
   Спрашивать у работающего экрана нельзя: до непройденной ветки
   (окно ошибки, пустой список) рендер не доходит, и её строки
   «не переведены» никто бы не увидел. */
const KEY = /\bTR\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g;
const used = new Map();
for (const f of fs.readdirSync(root)) {
  if (!/\.(jsx|js)$/.test(f) || f.startsWith("i18n")) continue;
  const src = fs.readFileSync(path.join(root, f), "utf8");
  for (const m of src.matchAll(KEY)) {
    let lit = m[1];
    let val;
    try { val = lit[0] === '"' ? JSON.parse(lit) : JSON.parse('"' + lit.slice(1, -1).replace(/"/g, '\\"') + '"'); }
    catch (e) { val = lit.slice(1, -1); }
    if (!used.has(val)) used.set(val, f);
  }
}

const dict = {};
window.I18N.register("uz", {});           // словарь уже зарегистрирован файлом
window.I18N.setLang("uz", true);
for (const k of used.keys()) dict[k] = TR(k);

console.log("=== 1. Полнота ===");
console.log("  ключей в коде: " + used.size);
const missing = [...used.keys()].filter(k => TR(k) === k && /[А-Яа-яЁё]/.test(k));
check(missing.length === 0, "все строки из кода есть в словаре" +
      (missing.length ? " — НЕТ " + missing.length + ":" : ""));
missing.slice(0, 40).forEach(k => console.log("       ! " + JSON.stringify(k)));
if (missing.length > 40) console.log("       … и ещё " + (missing.length - 40));

console.log("=== 2. Мусор ===");
/* Словарь читается тем же способом, что и на экране: через TR. Пройтись по
   ключам напрямую нельзя — I18N их не отдаёт, и это правильно. Поэтому
   берём JSON-источники: они и есть то, что правит человек. */
const parts = fs.readdirSync("frontend/i18n")
  .filter(f => /^uz\..*\.json$/.test(f) && f !== "uz.server.json");
const catalog = {};
for (const p of parts) {
  const obj = JSON.parse(fs.readFileSync(path.join("frontend/i18n", p), "utf8"));
  for (const k of Object.keys(obj)) if (k !== "_") catalog[k] = obj[k];
}
check(parts.length > 0, "части словаря на месте (" + parts.length + ")");
const stale = Object.keys(catalog).filter(k => !used.has(k));
check(stale.length === 0, "в словаре нет ключей, которых больше нет в коде" +
      (stale.length ? " — лишних " + stale.length + ":" : ""));
stale.slice(0, 30).forEach(k => console.log("       ~ " + JSON.stringify(k)));

console.log("=== 2b. Сообщения сервера ===");
/* Сервер отвечает по-русски НАМЕРЕННО: его строки лежат в боевых данных и
   разбираются подстрокой (_repair_findings читает backcheck.reasons), а
   промпты версионированы — перевод внутри сломал бы логику и данные.
   Переводится ГРАНИЦА показа: api.js достаёт detail и прогоняет через TRS().

   Значит у этой части словаря другой источник правды — исходники бэкенда,
   и проверять её фронтендом нельзя. Ключ обязан быть КУСКОМ настоящей
   строки бэкенда: иначе он не совпадёт никогда, а выглядеть будет
   переведённым. Кусками, а не целиком, потому что до браузера доезжает
   уже подставленное число («…исчерпан: $1.00 из $2.00»), и целая строка
   с %s не совпадёт ни с чем. */
/* checks.py здесь ОБЯЗАН быть: причины балла back-check и вердикт
   судьи пишутся там, и без него проверка молчала бы ровно про те
   объяснения, которые человек читает чаще всего. */
const backend = ["backend/main.py", "backend/checks.py",
                 "backend/textcount.py", "backend/store.py"]
  .filter(f => fs.existsSync(f))
  .map(f => fs.readFileSync(f, "utf8")).join("\n")
  /* Питон склеивает соседние литералы сам, а длинное сообщение в исходнике
     разрезано переносом строки — до клиента оно доезжает целым. Сшиваем
     так же, иначе проверка ругалась бы на верные ключи. Двумя способами:
     соседние литералы («…» «…») и явная склейка плюсом («…» + «…»).
     `\r` в классе обязателен: файлы, которых не касалась эта правка,
     лежат с CRLF, и без него сшивка молча не срабатывала — проверка
     выглядела зелёной там, где не смотрела. */
  .replace(/"[ \t\r]*\n[ \t\r]*"/g, "")
  .replace(/'[ \t\r]*\n[ \t\r]*'/g, "")
  .replace(/"[ \t\r]*\n?[ \t\r]*\+[ \t\r]*\n?[ \t\r]*"/g, "")
  .replace(/'[ \t\r]*\n?[ \t\r]*\+[ \t\r]*\n?[ \t\r]*'/g, "");
const srvFile = "frontend/i18n/uz.server.json";
const server = fs.existsSync(srvFile) ? JSON.parse(fs.readFileSync(srvFile, "utf8")) : {};
const srvKeys = Object.keys(server).filter(k => k !== "_");
check(srvKeys.length > 0, "часть со строками сервера есть (" + srvKeys.length + ")");
const notInBackend = srvKeys.filter(k => !backend.includes(k));
check(notInBackend.length === 0, "каждая строка сервера найдена в исходниках бэкенда" +
      (notInBackend.length ? " — НЕТ " + notInBackend.length + ":" : ""));
notInBackend.slice(0, 20).forEach(k => console.log("       ? " + JSON.stringify(k)));
/* И обратно: то, что сервер отвечает ЧАСТО и без вставок, обязано быть
   переведено. Список — сообщения об отказе доступа и о лимите: их видит
   каждый, и увидеть их по-русски в узбекском интерфейсе значит показать,
   что перевод сделан наполовину. */
const MUST = [
  "Требуется вход в систему",
  "Это действие доступно только владельцу организации",
  "Неверный логин или пароль",
  "Команда не найдена",
  "Приглашение не найдено",
];
const notTranslated = MUST.filter(k => !server[k]);
check(notTranslated.length === 0, "самые частые отказы сервера переведены" +
      (notTranslated.length ? " — НЕТ: " + notTranslated.join(", ") : ""));

console.log("=== 2c. Собранное сервером сообщение переводится ЦЕЛИКОМ ===");
/* Тот самый дефект, ради которого этот раздел и заведён: у TRS() стоял
   порог длины куска, и « из $» (пять символов) молча оставалось русским
   посреди узбекской фразы. Полнота словаря такое не ловит — ключ-то есть.
   Проверяется то, что видит человек: в переведённом сообщении не должно
   остаться НИ ОДНОЙ русской буквы. */
const SRV_SAMPLES = [
  "Требуется вход в систему",
  "Месячный лимит расхода организации исчерпан: $1.00 из $2.00. Бесплатные команды "
  + "(правка начертания, откаты, пересчёт, экспорт) работают; лимит сбрасывается 1-го числа.",
  "В организации есть проекты: [1, 2] — удалите их сначала",
  "Файл больше 25 МБ — разберите его по частям",
  "Цена страницы: больше нуля и не выше 1000 (снять цену — пустым полем)",
];
const dirty = SRV_SAMPLES.filter(m => /[А-Яа-яЁё]/.test(TRS(m)));
check(dirty.length === 0, "в переводе сообщений сервера не осталось русских букв" +
      (dirty.length ? " — осталось в " + dirty.length + ":" : ""));
dirty.forEach(m => console.log("       я " + JSON.stringify(TRS(m))));
check(TRS(SRV_SAMPLES[1]).includes("$1.00") && TRS(SRV_SAMPLES[1]).includes("$2.00"),
      "а числа подстановка не трогает");

console.log("=== 2d. Коды причин НЕ обёрнуты в TR ===");
/* Обёртка сломала это один раз и сломает снова: шесть кодов причин лежат
   в браузере СПИСКОМ ДЛЯ СРАВНЕНИЯ с `backcheck.reasons` — русским текстом
   с сервера. Обёрнутые, в узбекском режиме они перестают совпадать, и кнопка
   «Починить» гаснет на сегментах, которые чинить МОЖНО. Видимого признака
   поломки у этого нет: экран выглядит исправным.

   Проверяется в лоб: такой литерал в .jsx обязан стоять голым. Строка
   вида TR("расхождение чисел") — ошибка, где бы она ни встретилась. */
const DATA_CODES = [
  "расхождение чисел", "расхождение единиц", "инверсия отрицания",
  "подмена на противоположное", "обратный перевод про другое", "потерян термин",
];
const wrappedCodes = [];
for (const f of fs.readdirSync(root)) {
  if (!/\.(jsx|js)$/.test(f) || f.startsWith("i18n")) continue;
  const src = fs.readFileSync(path.join(root, f), "utf8");
  for (const code of DATA_CODES) {
    if (src.includes('TR("' + code + '")')) wrappedCodes.push(f + ": " + code);
  }
}
check(wrappedCodes.length === 0,
      "коды причин сравниваются с данными сервера и переводом не обёрнуты" +
      (wrappedCodes.length ? " — обёрнуты " + wrappedCodes.length + ":" : ""));
wrappedCodes.forEach(x => console.log("       ! " + x));

console.log("=== 3. Края строки и невидимые символы ===");
const edge = [];
const nl = [];
const nbsp = [];
for (const [k, v] of Object.entries(catalog)) {
  const lead = (s) => (s.match(/^\s*/) || [""])[0];
  const tail = (s) => (s.match(/\s*$/) || [""])[0];
  if (lead(k) !== lead(v) || tail(k) !== tail(v)) edge.push(k);
  if ((k.match(/\n/g) || []).length !== (v.match(/\n/g) || []).length) nl.push(k);
  if ((k.match(/ /g) || []).length !== (v.match(/ /g) || []).length) nbsp.push(k);
}
check(edge.length === 0, "пробелы по краям сохранены" + (edge.length ? " — сбито " + edge.length + ":" : ""));
edge.slice(0, 20).forEach(k => console.log("       ± " + JSON.stringify(k) + " → " + JSON.stringify(catalog[k])));
check(nl.length === 0, "переносов строк столько же" + (nl.length ? " — сбито " + nl.length : ""));
nl.slice(0, 10).forEach(k => console.log("       ± " + JSON.stringify(k)));
check(nbsp.length === 0, "неразрывных пробелов столько же" + (nbsp.length ? " — сбито " + nbsp.length : ""));
nbsp.slice(0, 10).forEach(k => console.log("       ± " + JSON.stringify(k)));

console.log("=== 4. Перевод не равен оригиналу ===");
/* Строка без кириллицы законно совпадает с оригиналом: «$», «≤ 8», «GPT».
   А вот скопированная русская строка — это невыполненная работа, которую
   счётчик полноты не поймает: ключ-то в словаре есть. */
const copied = Object.entries(catalog).filter(([k, v]) => k === v && /[А-Яа-яЁё]/.test(k));
check(copied.length === 0, "русских строк, скопированных как «перевод», нет" +
      (copied.length ? " — их " + copied.length + ":" : ""));
copied.slice(0, 20).forEach(([k]) => console.log("       = " + JSON.stringify(k)));

console.log("=== 5. Кириллицы в переводе не осталось ===");
/* Исключения именуются ЯВНО и списком: молчаливое «ну тут можно» через
   месяц объясняет любую невыполненную работу. */
const CYR_OK = new Set([
  "Русский",                                  // название языка на нём самом
  // Примеры русских букв в правиле отсева шума: это ОБРАЗЦЫ символов
  // исходного документа, а не надпись интерфейса. Перевести их значило бы
  // соврать о том, что именно отсеивается.
  "Строки, в которых переводить нечего: одиночные буквы («а», «б», «L»), ",
]);
const cyr = Object.entries(catalog)
  .filter(([k, v]) => /[А-Яа-яЁё]/.test(v) && !CYR_OK.has(k));
check(cyr.length === 0, "в узбекских строках нет кириллицы" +
      (cyr.length ? " — осталась в " + cyr.length + ":" : ""));
cyr.slice(0, 20).forEach(([k, v]) => console.log("       я " + JSON.stringify(v)));

console.log();
if (fail.length) {
  console.log("ПРОВАЛЕНО: " + fail.length);
  fail.forEach(f => console.log("  - " + f));
  process.exit(1);
}
console.log("ВСЁ ПРОШЛО");
