/* Чтение надписей у себя в браузере: математика, написанная НАМИ.

   Чужой кусок (onnxruntime) тут не проверяется — он не наш и не ломается
   от наших правок. Проверяется ровно то, что мы написали сами и что не
   видно ни в одном другом тесте:

     1. связные области — разбор карты вероятностей в рамки. Ошибка здесь
        означает рамку не на том месте, то есть заливку поверх рисунка
        при выгрузке и чужой текст в сегменте;
     2. CTC-декод — повторы схлопываются, пустой символ выбрасывается,
        а раскладка классов начинается с пустого: сдвинься она на единицу,
        текст поедет по всему алфавиту, и заметить это будет нечем;
     3. языка нет — предложения нет: прочитать узбекскую кириллицу
        русской распознавалкой значит показать мусор с видом готового
        текста.

   Ни одного вызова модели, ни браузера, ни npm.                        */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const fail = [];
function check(cond, label) {
  console.log((cond ? "  OK   " : "  FAIL ") + label);
  if (!cond) fail.push(label);
}

const file = path.join(__dirname, "..", "frontend", "js", "ocr_local.js");
const sandbox = {
  window: {},
  document: { createElement: () => ({ getContext: () => ({}) }), head: { appendChild() {} } },
  fetch: () => Promise.reject(new Error("сеть в тесте не нужна")),
  Promise, Float32Array, Uint8Array, Int32Array, Math, Blob: function () {},
  console,
};
sandbox.WebAssembly = {};
sandbox.createImageBitmap = function () {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(file, "utf8"), sandbox, { filename: "ocr_local.js" });

const L = sandbox.window.LocalOCR;
check(!!L, "модуль отдаёт window.LocalOCR");

console.log("\n── связные области ──");
/* Карта 6x3: две кляксы, между ними пустой столбец. Слить их в одну рамку
   значит накрыть заодно и то, что между ними, — а по рамке потом стирают. */
const W = 6, H = 3;
const prob = new Float32Array(W * H);
const put = (x, y, v) => { prob[y * W + x] = v; };
put(0, 0, 0.9); put(1, 0, 0.9); put(0, 1, 0.9);
put(4, 1, 0.8); put(5, 1, 0.8); put(5, 2, 0.8);
const got = L._areas(prob, W, H).sort((a, b) => a.x0 - b.x0);
check(got.length === 2, "две кляксы — две области, а не одна: " + got.length);
check(got[0] && got[0].x0 === 0 && got[0].x1 === 2 && got[0].y0 === 0 && got[0].y1 === 2,
  "первая область обмерена по своим пикселям: " + JSON.stringify(got[0]));
check(got[1] && got[1].x0 === 4 && got[1].x1 === 6 && got[1].y1 === 3,
  "вторая область обмерена по своим пикселям: " + JSON.stringify(got[1]));
check(got[0] && Math.abs(got[0].conf - 0.9) < 1e-6,
  "уверенность области — средняя по её пикселям: " + (got[0] || {}).conf);
check(L._areas(new Float32Array(W * H), W, H).length === 0,
  "пустая карта — ноль областей, без срыва");

console.log("\n── CTC ──");
/* Классы: 0 — пустой, дальше словарь, последним пробел (раскладка PaddleOCR). */
const list = ["\u0000", "а", "б", " "];
function logits(seq) {
  const out = new Float32Array(seq.length * list.length);
  seq.forEach((k, t) => { out[t * list.length + k] = 5; });
  return out;
}
const r1 = L._ctc(logits([1, 1, 0, 1, 2]), [1, 5, list.length], list);
check(r1.text === "аа" + "б" || r1.text === "ааб",
  "повтор подряд схлопнут, после пустого буква считается заново: " + JSON.stringify(r1.text));
const r2 = L._ctc(logits([0, 0, 0]), [1, 3, list.length], list);
check(r2.text === "" && r2.conf === 0,
  "одни пустые — пустая строка и нулевая уверенность, а не выдуманный текст");
const r3 = L._ctc(logits([1, 3, 2]), [1, 3, list.length], list);
check(r3.text === "а б", "пробел — обычный класс словаря: " + JSON.stringify(r3.text));

console.log("\n── длинная строка ──");
/* Подпись 900×20 — это 45 высот строки. Сжать её во вход распознавалки
   значит получить кашу, отсеять её по уверенности и оставить картинку
   «прочитанной»: кусок книги пропадёт молча. Режем — и ни пикселя
   не теряем на стыках. */
const one = L._slices(10, 200, 20);
check(one.length === 1 && one[0][0] === 10 && one[0][1] === 200,
  "короткая строка не режется вовсе: " + JSON.stringify(one));
/* Боевая подпись «Диссеминированный туберкулёз лёгких» — 467x23, то есть
   975 пикселей после подгонки по высоте. Браузер показал: сжатие до 66%
   она переживает без единой ошибки, а шов съедает пробел. Значит резать
   её НЕЛЬЗЯ — и это ровно тот случай, на котором правило сломалось. */
const real = L._slices(29, 467, 23);
check(real.length === 1,
  "подпись в 467x23 идёт одним куском — шов дороже сжатия: " + real.length);
const many = L._slices(0, 3000, 20);
check(many.length >= 2, "совсем длинная строка разрезана: " + many.length);
check(many[0][0] === 0, "первая полоса начинается с начала рамки");
const last = many[many.length - 1];
check(last[0] + last[1] === 3000,
  "последняя полоса кончается концом рамки: " + JSON.stringify(last));
let seam = true;
for (let i = 1; i < many.length; i++) {
  if (many[i][0] !== many[i - 1][0] + many[i - 1][1]) seam = false;
}
check(seam, "полосы идут встык: ни дыр, ни нахлёста — " + JSON.stringify(many));
check(many.every(s => s[1] > 0), "пустых полос нет");

console.log("\n── язык ──");
check(L.can("RU") === true, "для русского чтение у себя предлагается");
check(L.can("EN") === true, "для английского тоже — он в том же словаре");
check(L.can("UZ") === false, "узбекской латиницы не возим — кнопки нет");
check(L.can("UZ-CYRL") === false,
  "узбекской кириллицы в словаре нет (ни «қ», ни «ғ», ни «ҳ») — кнопки нет");
check(L.can("") === false, "языка не знаем — кнопки нет");

console.log("\n" + (fail.length ? "ПРОВАЛЕНО: " + fail.join("; ") : "ВСЁ ПРОШЛО"));
process.exit(fail.length ? 1 : 0);
