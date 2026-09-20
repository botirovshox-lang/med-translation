/* Чтение надписей с картинок У СЕБЯ В БРАУЗЕРЕ.
   ════════════════════════════════════════════════════════════════════

   Зачем. Сегодня надписи читает зрячая модель, и у этого две цены, обе
   неочевидные. Первая — ВОРКЕР: поиск строк идёт на сервере, движок держит
   сотни мегабайт, воркер один, и на время разбора проект заперт. Вторая —
   юридическая: на снимках боевого учебника лежат фамилии врачей, даты
   исследования и настройки томографа, и всё это уезжает за границу
   поставщику модели. Здесь картинка не покидает компьютер человека вовсе,
   а сервер не тратит ни секунды и ни цента.

   Что тут своё, а что чужое. Чужой ровно один кусок — onnxruntime-web,
   то есть исполнитель тензоров. Всё остальное — подготовка картинки,
   разбор карты вероятностей в рамки (связные области), нарезка строк
   и CTC-декод — написано здесь, и написано так, чтобы совпадать
   с серверным разбором по смыслу, а не по коду.

   Чего тут НЕТ намеренно. Склейка кусков в строки, сборка строк в блоки,
   плоскость фона, отсев шума и заведение сегментов остались НА СЕРВЕРЕ
   (`image_text.lines_from`). Это не лень: правила измерены на боевых
   картинках, а вторая их копия здесь разошлась бы с первой же правкой —
   и разойтись ей нельзя, по этим правилам решают, можно ли стирать
   надпись на снимке.

   Честная цена. Локальная распознавалка читает ХУЖЕ зрячей модели: замер
   авторов модели — 81.6% строк без единой ошибки, и путает она в том числе
   омоглифы (латинская «A» приходит кириллической «А»). Поэтому прочитанное
   здесь — предложение человеку, а не готовый текст: он читает ОРИГИНАЛ,
   то есть язык, который знает.

   Первый заход качает около 21 МБ (исполнитель + две модели). Всё, что
   спрашиваем МЫ, идёт с `?v=` и потому лежит в кэше вечно; два файла
   исполнителя (`.mjs` и `.wasm`) спрашивает сам onnxruntime, адрес их
   задан им, и они переспрашиваются по ETag — один ответ «не менялось»
   на заход, который бывает раз в жизни проекта.                        */
(function () {
  "use strict";

  var DIR = "vendor/ocr/";
  /* Какой распознавалкой читать язык ОРИГИНАЛА. Модель одна на группу
     языков; узбекской кириллицы в её словаре нет (нет ни «қ», ни «ғ»,
     ни «ҳ»), латиницы мы пока не возим — для таких проектов кнопки нет
     вовсе, и сказано почему. Молча прочитать не тем алфавитом было бы
     хуже: на экран приехал бы мусор с видом готового текста. */
  var REC = { RU: "eslav", UK: "eslav", BE: "eslav", BG: "eslav", EN: "eslav" };

  /* Детектор. Числа — те же, на которых стоит PaddleOCR и наш серверный
     разбор: сторона не больше 960 и кратна 32 (модель считает по своей
     сетке), карта вероятностей режется по 0.3. */
  var DET_MAX = 960, DET_THRESH = 0.3, DET_UNCLIP = 1.6, DET_MIN_SIDE = 3;
  /* Средняя вероятность по пятну, ниже которой это не строка. Порог по
     самому пятну нужен отдельно от порога бинаризации: 0.3 отделяет чернила
     от бумаги, а это — строку от кляксы. Без него в сегменты уезжают пятна
     0.3–0.5, и их же потом рисуют поверх картинки при выгрузке. */
  var DET_BOX_MIN = 0.5;
  /* Распознавалка: высота строки 48 пикселей — это вход модели, а не вкус. */
  var REC_H = 48, REC_W_MAX = 640;
  /* Ниже этой уверенности строку не отдаём. Здесь это СРЕДНЯЯ вероятность
     выбранных символов, и на мусоре она проваливается. */
  var REC_MIN_CONF = 0.5;

  var ortP = null, sess = {}, dict = {};

  function ver() {
    return (window.BOOT && window.BOOT.v) || "0";
  }

  function url(name) { return DIR + name + "?v=" + ver(); }

  /* ── Исполнитель тензоров ──────────────────────────────────────── */

  /* Неудачу НЕ запоминаем: оборвалась загрузка (а качать тут 21 МБ) —
     запомненный отказ убил бы чтение до перезагрузки страницы, и человек
     видел бы «картинок не разобрано: 150» на каждое нажатие. Забыли —
     значит следующее нажатие попробует заново. */
  function forget(box, key) {
    return function (e) { if (box[key]) delete box[key]; throw e; };
  }

  function loadOrt() {
    if (ortP) return ortP;
    ortP = new Promise(function (done, fail) {
      if (window.ort) return done(window.ort);
      var s = document.createElement("script");
      s.src = url("ort.wasm.min.js");
      s.async = true;
      s.onload = function () {
        if (!window.ort) return fail(new Error("ort не поднялся"));
        /* Один поток и без прокси: потоки просят SharedArrayBuffer, а он
           требует заголовков COOP/COEP на ВСЁМ сайте — чинить ради этого
           весь сервис нельзя. Путь к wasm — свой: чужих хостов на наших
           страницах нет ни одного, и заводить первый ради OCR незачем. */
        window.ort.env.wasm.numThreads = 1;
        window.ort.env.wasm.proxy = false;
        window.ort.env.wasm.wasmPaths = DIR;
        done(window.ort);
      };
      s.onerror = function () { fail(new Error("не скачался исполнитель")); };
      document.head.appendChild(s);
    }).catch(function (e) { ortP = null; throw e; });
    return ortP;
  }

  function session(name, file) {
    if (sess[name]) return sess[name];
    sess[name] = loadOrt().then(function (ort) {
      return ort.InferenceSession.create(url(file), {
        executionProviders: ["wasm"], graphOptimizationLevel: "all"
      });
    }).catch(forget(sess, name));
    return sess[name];
  }

  function chars(group) {
    if (dict[group]) return dict[group];
    dict[group] = fetch(url("rec-" + group + ".txt")).then(function (r) {
      if (!r.ok) throw new Error("нет словаря " + group);
      return r.text();
    }).then(function (t) {
      /* Режем и по CRLF: словарь — по символу на строку, и «\r»,
         прилипший к каждому, стал бы ЧАСТЬЮ символа — алфавит съехал
         бы целиком, а на экране не было бы ни одной ошибки, только
         другие буквы. Файлу это запрещает и `.gitattributes`; здесь —
         второй рубеж: цена ошибки несоразмерна цене проверки. */
      var list = t.split(/\r?\n/);
      while (list.length && list[list.length - 1] === "") list.pop();
      /* Раскладка классов у PaddleOCR: нулевой — пустой символ CTC,
         дальше словарь, последним пробел. Сдвинься она на единицу —
         текст поедет по всему алфавиту, и заметить это будет нечем. */
      return ["\u0000"].concat(list).concat([" "]);
    }).catch(forget(dict, group));
    return dict[group];
  }

  /* ── Картинка ──────────────────────────────────────────────────── */

  function canvas(w, h) {
    var c = document.createElement("canvas");
    c.width = w; c.height = h;
    return c;
  }

  /* Пиксели куска картинки, СРАЗУ нужного размера: масштабирование делает
     сам браузер — это его работа, и делает он её быстрее любого нашего
     цикла по пикселям. */
  function pixels(bitmap, sx, sy, sw, sh, dw, dh) {
    var c = canvas(dw, dh);
    var g = c.getContext("2d", { willReadFrequently: true });
    /* Белая подложка: у PNG прозрачное обычно хранит чёрный, и без неё
       прозрачный фон приехал бы чёрным полем. */
    g.fillStyle = "#fff";
    g.fillRect(0, 0, dw, dh);
    g.drawImage(bitmap, sx, sy, sw, sh, 0, 0, dw, dh);
    return g.getImageData(0, 0, dw, dh).data;
  }

  /* ── Детектор: картинка → карта вероятностей → рамки ───────────── */

  var DET_MEAN = [0.485, 0.456, 0.406], DET_STD = [0.229, 0.224, 0.225];

  function detTensor(bitmap) {
    var w = bitmap.width, h = bitmap.height;
    var k = Math.min(1, DET_MAX / Math.max(w, h));
    var nw = Math.max(32, Math.round(w * k / 32) * 32);
    var nh = Math.max(32, Math.round(h * k / 32) * 32);
    var px = pixels(bitmap, 0, 0, w, h, nw, nh);
    var n = nw * nh, f = new Float32Array(3 * n);
    for (var i = 0; i < n; i++) {
      for (var c = 0; c < 3; c++) {
        f[c * n + i] = (px[i * 4 + c] / 255 - DET_MEAN[c]) / DET_STD[c];
      }
    }
    return { data: f, nw: nw, nh: nh, kx: w / nw, ky: h / nh };
  }

  /* Связные области (4-связность) стеком, без рекурсии: рекурсия на карте
     960×960 упирается в стек браузера, а падение здесь означало бы
     «надписей нет» — то самое враньё, которого модуль не допускает. */
  function areas(prob, w, h) {
    var seen = new Uint8Array(w * h), stack = new Int32Array(w * h), out = [];
    for (var p0 = 0; p0 < w * h; p0++) {
      if (seen[p0] || prob[p0] <= DET_THRESH) continue;
      var top = 0;
      stack[top++] = p0; seen[p0] = 1;
      var x0 = p0 % w, x1 = x0, y0 = (p0 / w) | 0, y1 = y0, sum = 0, cnt = 0;
      while (top > 0) {
        var p = stack[--top], x = p % w, y = (p / w) | 0;
        sum += prob[p]; cnt++;
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (y < y0) y0 = y; if (y > y1) y1 = y;
        if (x > 0 && !seen[p - 1] && prob[p - 1] > DET_THRESH) { seen[p - 1] = 1; stack[top++] = p - 1; }
        if (x < w - 1 && !seen[p + 1] && prob[p + 1] > DET_THRESH) { seen[p + 1] = 1; stack[top++] = p + 1; }
        if (y > 0 && !seen[p - w] && prob[p - w] > DET_THRESH) { seen[p - w] = 1; stack[top++] = p - w; }
        if (y < h - 1 && !seen[p + w] && prob[p + w] > DET_THRESH) { seen[p + w] = 1; stack[top++] = p + w; }
      }
      out.push({ x0: x0, y0: y0, x1: x1 + 1, y1: y1 + 1, conf: sum / cnt });
    }
    return out;
  }

  function detect(sessionDet, bitmap, ort) {
    var t = detTensor(bitmap);
    var input = new ort.Tensor("float32", t.data, [1, 3, t.nh, t.nw]);
    var feeds = {};
    feeds[sessionDet.inputNames[0]] = input;
    return sessionDet.run(feeds).then(function (res) {
      var prob = res[sessionDet.outputNames[0]].data;
      var boxes = [];
      areas(prob, t.nw, t.nh).forEach(function (a) {
        var bw = a.x1 - a.x0, bh = a.y1 - a.y0;
        if (bw < DET_MIN_SIDE || bh < DET_MIN_SIDE || a.conf < DET_BOX_MIN) return;
        /* Рамку детектор ставит по чернилам, впритык; настоящая строка
           шире. Расширяем так же, как это делает PaddleOCR своим
           многоугольником: смещение = площадь × коэффициент / периметр. */
        var d = (bw * bh) * DET_UNCLIP / (2 * (bw + bh));
        boxes.push({
          box: [Math.round((a.x0 - d) * t.kx), Math.round((a.y0 - d) * t.ky),
                Math.round((a.x1 + d) * t.kx), Math.round((a.y1 + d) * t.ky)],
          conf: Math.round(a.conf * 1000) / 1000
        });
      });
      boxes.sort(function (p, q) { return p.box[1] - q.box[1] || p.box[0] - q.box[0]; });
      return boxes;
    });
  }

  /* ── Распознавалка: кусок → строка текста ──────────────────────── */

  /* Полосы, на которые режется слишком длинная рамка. Подпись 900×20 —
     это 45 высот строки, а вход у распознавалки не резиновый: втиснутая
     в REC_W_MAX она превращается в кашу, кашу отсеет порог уверенности,
     а картинка останется «прочитанной» — то есть кусок книги пропадёт
     молча. Режем по ИСХОДНОЙ рамке и склеиваем тексты; шов может съесть
     букву, но это видно, в отличие от сжатия. */
  function slices(sx, sw, sh) {
    var need = REC_H * sw / sh;
    var n = Math.max(1, Math.ceil(need / REC_W_MAX));
    var out = [];
    for (var i = 0; i < n; i++) {
      var a = Math.round(sx + sw * i / n), b = Math.round(sx + sw * (i + 1) / n);
      out.push([a, Math.max(1, b - a)]);
    }
    return out;
  }

  function recTensor(bitmap, box, sx, sw) {
    var y0 = Math.max(0, box[1]);
    var y1 = Math.min(bitmap.height, box[3]);
    var x0 = sx, sh = Math.max(1, y1 - y0);
    var w = Math.max(8, Math.min(REC_W_MAX, Math.round(REC_H * sw / sh)));
    var px = pixels(bitmap, x0, y0, sw, sh, w, REC_H);
    var n = w * REC_H, f = new Float32Array(3 * n);
    for (var i = 0; i < n; i++) {
      for (var c = 0; c < 3; c++) f[c * n + i] = px[i * 4 + c] / 255 * 2 - 1;
    }
    return { data: f, w: w };
  }

  /* CTC: берём самый вероятный класс на каждом шаге, схлопываем повторы
     подряд и выбрасываем пустой символ. Уверенность строки — средняя
     по тем шагам, что дали буквы. */
  function ctc(logits, dims, list) {
    var steps = dims[1], klass = dims[2], text = "", sum = 0, cnt = 0, prev = -1;
    for (var t = 0; t < steps; t++) {
      var best = 0, bestV = -Infinity, off = t * klass;
      for (var c = 0; c < klass; c++) {
        if (logits[off + c] > bestV) { bestV = logits[off + c]; best = c; }
      }
      if (best !== prev && best !== 0) {
        text += list[best] || "";
        sum += bestV; cnt++;
      }
      prev = best;
    }
    return { text: text, conf: cnt ? Math.round(sum / cnt * 1000) / 1000 : 0 };
  }

  function recognise(sessionRec, bitmap, box, list, ort) {
    var x0 = Math.max(0, box[0]);
    var sw = Math.max(1, Math.min(bitmap.width, box[2]) - x0);
    var sh = Math.max(1, Math.min(bitmap.height, box[3]) - Math.max(0, box[1]));
    var text = "", sum = 0, cnt = 0;
    return slices(x0, sw, sh).reduce(function (chain, s) {
      return chain.then(function () {
        var t = recTensor(bitmap, box, s[0], s[1]);
        var feeds = {};
        feeds[sessionRec.inputNames[0]] =
          new ort.Tensor("float32", t.data, [1, 3, REC_H, t.w]);
        return sessionRec.run(feeds).then(function (res) {
          var out = res[sessionRec.outputNames[0]];
          var r = ctc(out.data, out.dims, list);
          text += r.text;
          if (r.conf) { sum += r.conf; cnt++; }
        });
      });
    }, Promise.resolve()).then(function () {
      return { text: text, conf: cnt ? Math.round(sum / cnt * 1000) / 1000 : 0 };
    });
  }

  /* ── Наружу ────────────────────────────────────────────────────── */

  function group(src) {
    return REC[String(src || "").toUpperCase()] || "";
  }

  var api = {
    /* Можно ли вообще предложить это человеку: браузер умеет WebAssembly
       и для языка оригинала у нас есть распознавалка. */
    can: function (src) {
      return typeof WebAssembly === "object"
        && typeof createImageBitmap === "function" && !!group(src);
    },
    group: group,
    /* Прочитать одну картинку. [{box, conf, text}] — строки, как их отдаёт
       серверный детектор, плюс текст. Ошибку не глотаем: «не смогли» и
       «надписей нет» — разные ответы, и путать их нельзя. */
    read: function (bytes, src) {
      var g = group(src);
      if (!g) return Promise.reject(new Error("нет распознавалки для " + src));
      var bitmap = null;
      return Promise.all([
        loadOrt(), session("det", "det.onnx"),
        session("rec-" + g, "rec-" + g + ".onnx"), chars(g),
        createImageBitmap(new Blob([bytes]))
      ]).then(function (all) {
        var ort = all[0], det = all[1], rec = all[2], list = all[3];
        bitmap = all[4];
        return detect(det, bitmap, ort).then(function (boxes) {
          var out = [];
          return boxes.reduce(function (chain, b) {
            return chain.then(function () {
              return recognise(rec, bitmap, b.box, list, ort).then(function (r) {
                if (r.text.trim() && r.conf >= REC_MIN_CONF) {
                  out.push({ box: b.box, conf: r.conf, text: r.text });
                }
              });
            });
          }, Promise.resolve()).then(function () { return out; });
        });
      }).then(function (out) {
        if (bitmap && bitmap.close) bitmap.close();
        return out;
      }, function (e) {
        if (bitmap && bitmap.close) bitmap.close();
        throw e;
      });
    },
    /* Наружу ради теста, и только: связные области и CTC — единственные
       два куска, которые мы написали САМИ, а ошибка в них выглядит как
       рамка не на том месте и текст, поехавший по алфавиту. Проверить их
       через `read` нельзя — там чужой исполнитель и сеть. */
    _areas: areas,
    _ctc: ctc,
    _slices: slices
  };

  window.LocalOCR = api;
})();
