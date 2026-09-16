/*
 * Сторож загрузки фронтенда: Babel больше нет.
 *
 * Файлы .jsx подключаются обычными <script> и выполняются браузером как
 * есть — самого JSX в них никогда и не было (везде React.createElement).
 * Отсюда три вещи, которые ломаются молча и потому проверяются здесь:
 *
 *   1. настоящий JSX в любом из файлов — это SyntaxError в браузере, то
 *      есть БЕЛЫЙ ЭКРАН. Node — тот же разбор, что у браузера, поэтому
 *      «файл разбирается как обычный JS» и есть нужная проверка;
 *   2. новый файл, забытый в загрузчике index.html, не подключится ничем:
 *      сборки нет, автоматического обхода каталога нет;
 *   3. порядок файлов НЕСУЩИЙ: они живут в одной глобальной области, и
 *      совпавшее имя верхнего уровня из позднего файла затирает раннее
 *      (так SegRow из tab_preflight.jsx однажды затёр SegRow редактора).
 *
 * Запуск: node tests/test_no_babel.js
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

const root = process.argv[2] || "frontend/js";
const html = fs.readFileSync("frontend/index.html", "utf8");

console.log("=== 1. Файлы — обычный JavaScript, а не JSX ===");
const files = fs.readdirSync(root).filter(f => f.endsWith(".jsx")).sort();
check(files.length > 0, "файлы экранов найдены: " + files.length);
for (const f of files) {
  const src = fs.readFileSync(path.join(root, f), "utf8");
  let ok = true, why = "";
  try { new vm.Script(src, { filename: f }); } catch (e) { ok = false; why = " — " + e.message.slice(0, 70); }
  check(ok, f + ": разбирается браузером без сборки" + why);
}

console.log("=== 2. Babel не подключается и не нужен ===");
/* Смотрим на РАЗМЕТКУ, а не на текст: почему Babel убран, сказано там же
   комментарием, и тест, ищущий слово, запретил бы само объяснение. */
const markup = html.replace(/<!--[\s\S]*?-->/g, "");
check(!/text\/babel/.test(markup), "в index.html нет type=\"text/babel\"");
check(!/src\s*=\s*"[^"]*babel/i.test(markup), "babel.min.js не грузится");

console.log("=== 3. Загрузчик знает все файлы, и порядок сохранён ===");
/* Список адресов из загрузчика — в порядке появления. */
const listed = [...html.matchAll(/"(js\/[A-Za-z0-9_.]+\.jsx)"/g)].map(m => m[1].slice(3));
check(new Set(listed).size === listed.length, "ни один файл не подключён дважды");
const missing = files.filter(f => !listed.includes(f));
check(missing.length === 0, "все файлы экранов подключены" + (missing.length ? ": забыты " + missing.join(", ") : ""));
const extra = listed.filter(f => !files.includes(f));
check(extra.length === 0, "лишних адресов нет" + (extra.length ? ": " + extra.join(", ") : ""));
/* Правило из CLAUDE.md: SegRow редактора должен пережить tab_preflight.jsx. */
check(listed.indexOf("tab_export_preflight.jsx") < listed.indexOf("tab_preflight.jsx"),
      "tab_preflight.jsx идёт ПОСЛЕ tab_export_preflight.jsx");
check(listed.indexOf("tab_editor_detail.jsx") < listed.indexOf("tab_editor.jsx"),
      "tab_editor_detail.jsx идёт ПЕРЕД tab_editor.jsx");
check(listed.indexOf("ui.jsx") === -1 || listed.indexOf("ui.jsx") < listed.indexOf("app.jsx"),
      "ui.jsx идёт ПЕРЕД app.jsx");

console.log("=== 4. React — свой, а не с чужого хоста ===");
for (const f of ["react.production.min.js", "react-dom.production.min.js"]) {
  check(fs.existsSync(path.join("frontend/vendor", f)), "frontend/vendor/" + f + " на месте");
  check(html.includes("vendor/" + f), "index.html грузит свой " + f);
}

console.log("\n" + (fail.length ? "ПРОВАЛЕНО: " + fail.join("; ") : "ВСЁ ПРОШЛО"));
process.exit(fail.length ? 1 : 0);
