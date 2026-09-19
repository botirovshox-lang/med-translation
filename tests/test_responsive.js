/* Резиновая вёрстка: сторож механических правил.
 *
 * Экран на 360 px ломается тихо: страница начинает ездить вбок, и увидеть
 * это можно только на телефоне — ни один рендер-тест горизонтальной
 * прокрутки не видит, потому что рендерит в пустоту без ширины. Поэтому
 * сторожатся не пиксели, а ПРИЧИНЫ, по которым они разъезжались у нас:
 *
 *   1. таблица лежит в прокручиваемом контейнере. Шесть колонок в 360 px
 *      не помещаются никогда, и без контейнера вбок едет ВСЯ страница,
 *      а не таблица;
 *   2. в .jsx нет жёсткой ширины от 300 px: это ширина больше телефонной
 *      колонки, и она выталкивает соседа за край (так было с выбором файла
 *      в панели редактора — minWidth: 280 плюс пара языков рядом);
 *   3. авто-сетка не требует колонки шире контейнера: `minmax(340px, 1fr)`
 *      на экране в 360 px даёт полосу прокрутки ровно на поля страницы.
 *      Лечится `min(340px, 100%)`;
 *   4. поле ввода на телефоне не мельче 16 px — иначе iOS Safari приближает
 *      страницу при входе в поле и сам обратно не отдаляет;
 *   5. у страницы есть viewport-meta: без неё телефон рисует экран
 *      шириной 980 px и уменьшает его — «резиновость» перестаёт работать
 *      вся разом.
 *
 * Запуск: node tests/test_responsive.js
 */
const fs = require("fs");
const path = require("path");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

const JS = "frontend/js";
const CSS = fs.readFileSync("frontend/css/styles.css", "utf8");
const HTML = fs.readFileSync("frontend/index.html", "utf8");
const files = fs.readdirSync(JS).filter(f => f.endsWith(".jsx"));

console.log("1. Таблица — в прокручиваемом контейнере");
{
  const bad = [];
  for (const f of files) {
    const src = fs.readFileSync(path.join(JS, f), "utf8");
    /* className бывает не первым свойством («{ key: i, className: "tbl" }»),
       поэтому смотрим весь объект свойств до закрывающей скобки. */
    const re = /React\.createElement\("table",\s*\{[^}]*className:\s*"tbl/g;
    for (const m of src.matchAll(re)) {
      /* Контейнер стоит НЕПОСРЕДСТВЕННО над таблицей: свой класс
         (.tbl-scroll) либо inline-overflow — оба приёма уже в ходу. */
      const before = src.slice(Math.max(0, m.index - 260), m.index);
      if (!/tbl-scroll|tbl-fit|overflowX?:/.test(before)) {
        bad.push(f + ":" + (src.slice(0, m.index).split("\n").length));
      }
    }
  }
  check(bad.length === 0, "каждая таблица прокручивается сама" + (bad.length ? ": " + bad.join(", ") : ""));
}

console.log("2. Жёстких ширин от 300 px в .jsx нет");
{
  const bad = [];
  for (const f of files) {
    const src = fs.readFileSync(path.join(JS, f), "utf8");
    src.split("\n").forEach((line, i) => {
      /* Ширина окна (`Modal, { width: 640 }`) — это ПОТОЛОК: само окно
         шире экрана не станет (max-width), и к жёстким ширинам не относится. */
      if (/\bModal\b/.test(line)) return;
      /* Эвристика, и она честно неполная: ловит числовую ширину в инлайновом
         стиле («width: 340», «minWidth: 300») и ту же строкой («width: "340px"»).
         Ширину внутри `flex` и ширину картинки она не видит — там глаз. */
      for (const m of line.matchAll(/(?<!max)(?:W|w)idth:\s*"?(\d+)(?:px")?/g)) {
        if (Number(m[1]) >= 300) bad.push(f + ":" + (i + 1) + " — " + m[0]);
      }
    });
  }
  check(bad.length === 0, "ширина шире телефонной колонки не зашита" + (bad.length ? ": " + bad.join("; ") : ""));
}

console.log("3. Авто-сетка не шире контейнера");
{
  const bad = [];
  for (const m of CSS.matchAll(/repeat\(\s*auto-(?:fit|fill)\s*,\s*minmax\(\s*([^,)]+)\s*,/g)) {
    const low = m[1].trim();
    if (/^\d+px$/.test(low)) bad.push(m[0].trim());
  }
  check(bad.length === 0, "нижняя граница колонки снята min()" + (bad.length ? ": " + bad.join("; ") : ""));
}

console.log("4. Поле ввода на телефоне не мельче 16 px");
{
  /* Блок вырезается ПО СКОБКАМ, а не «до первого 16px где-нибудь ниже»:
     ленивый поиск через весь файл нашёл бы правило, вынесенное из блока,
     и сторож молчал бы ровно тогда, когда правила уже нет. */
  let found = false;
  for (let at = CSS.indexOf("@media (max-width: 640px)"); at >= 0;
       at = CSS.indexOf("@media (max-width: 640px)", at + 1)) {
    const i = CSS.indexOf("{", at);
    let depth = 0;
    for (let j = i; j < CSS.length; j++) {
      if (CSS[j] === "{") depth++;
      else if (CSS[j] === "}" && --depth === 0) {
        if (/font-size:\s*16px/.test(CSS.slice(i, j))) found = true;
        break;
      }
    }
  }
  check(found, "кегль поля на телефоне задан внутри блока 640 px");
}

console.log("5. Страница объявляет себя резиновой");
{
  check(/<meta name="viewport" content="width=device-width/.test(HTML), "viewport-meta на месте");
  check(/user-scalable=no|maximum-scale=1/.test(HTML) === false, "зум пальцами не запрещён");
}

console.log("6. Колонка карточки сегмента — только пока карточка открыта");
{
  /* Прежде сетка редактора держала 300–352 px справа всегда, даже с пустой
     рамкой «Сегмент не выбран». Теперь колонка есть только у .has-side,
     а на узком экране (≤ 1100 px) карточка встаёт под таблицу и с ней. */
  const base = /\.editor-body\s*\{[^}]*grid-template-columns:\s*([^;]+);/.exec(CSS);
  check(!!base && base[1].trim() === "minmax(0, 1fr)", "без карточки таблица во всю ширину: " + (base ? base[1] : "?"));
  check(/\.editor-body\.has-side\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\) minmax\(300px, 352px\)/.test(CSS),
        "с открытой карточкой — колонка 300–352 px");
  check(/@media \(max-width: 1100px\) \{ \.editor-body, \.editor-body\.has-side \{ grid-template-columns: 1fr; \}/.test(CSS),
        "на узком экране карточка под таблицей и с открытой колонкой");
}

console.log(fail.length ? "\nПРОВАЛЕНО: " + fail.length : "\nВСЁ ПРОШЛО");
process.exit(fail.length ? 1 : 0);
