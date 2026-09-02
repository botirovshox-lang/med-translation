/* ============================================================
   Tab: Segment Editor — the core translation workspace
   ============================================================ */

// Размер порции пакетного перевода на сервере (JOB_CHUNKS в main.py) — нужен только
// для сметы и подписей: сами порции крутит фоновый прогон, а не браузер.
const BATCH_CHUNK = 10;
const EST_SEC_PER_SEG = 5;          // замер на проде: 5-6 с на сегмент через GPT

const GPT_MODEL_LS_KEY = "mcat_gpt_model";
const BC_MODEL_LS_KEY = "mcat_backcheck_model";
const JUDGE_MODEL_LS_KEY = "mcat_judge_model";
const BC_SKIP_CONFIRMED_LS_KEY = "mcat_bc_skip_confirmed";
const SEARCH_SCOPE_LS_KEY = "mcat_search_scope";
const TC_MODEL_LS_KEY = "mcat_termcheck_model";
const TCX_MODEL_LS_KEY = "mcat_termaudit_model";
const RP_MODEL_LS_KEY = "mcat_repair_model";
const RV_MODEL_LS_KEY = "mcat_review_model";
/* Один источник ключей для панели «Анализа»: она читает и пишет ТЕ ЖЕ выборы
   моделей, что и карточки редактора. Свои литералы там завели бы второе
   хранилище того же выбора — модель, сменённая на одном экране, молча
   не доехала бы до другого. Имена параметров = имена полей run-plan. */
window.MODEL_LS = { model: GPT_MODEL_LS_KEY, bc_model: BC_MODEL_LS_KEY,
                    tc_model: TC_MODEL_LS_KEY, tcx_model: TCX_MODEL_LS_KEY,
                    rp_model: RP_MODEL_LS_KEY, judge_model: JUDGE_MODEL_LS_KEY,
                    rv_model: RV_MODEL_LS_KEY };
const JOB_LABELS = { translate: TR("Перевод"), backcheck: "Back-check", termcheck: TR("Проверка терминологии"),
                     termaudit: TR("Сверка терминов моделью"), review: TR("Ревизия перевода"),
                     repair: TR("Автоматический ремонт"), medical_qa: TR("Детерминированные проверки"),
                     full: TR("Перевод и проверка"), apply_terms: TR("Одобрение и применение") };

// Короткие имена шагов составного прогона. Одни и те же в таблице состава и
// в полосе прогресса: разойдись они — человек не свяжет галочку на полосе
// со строкой, галочками в которой он этот шаг и набирал.
const FULL_STEP_LABELS = { translate: TR("Перевод"), backcheck: "Back-check", termcheck: TR("Термины"),
                           termaudit: TR("Сверка терминов"), review: TR("Ревизия"),
                           repair: TR("Ремонт"), medical_qa: TR("Детерминированные проверки") };

/* Сколько раз пробуем забрать результат прогона, прежде чем сдаться вслух.
   Ноль попыток — оборванная сеть оставляет таблицу устаревшей навсегда;
   без потолка — вкладка раз в 15 секунд бесконечно долбит самый тяжёлый
   эндпоинт, а воркер uvicorn на сервере ОДИН: это самообстрел. */
const PULL_TRIES = 3;
/* Пауза между сверками статусов. Пока прогон идёт в СОСЕДНЕЙ вкладке, эта
   узнаёт о нём не сразу (опрос в простое — раз в 15 с), а статусы на сервере
   меняются каждые несколько секунд: без паузы сверка гоняла бы «разбор →
   пять мегабайт → разбор» по кругу все эти пятнадцать секунд. */
const DRIFT_PAUSE_MS = 30000;

/* Отпечаток статусов проекта — строкой, чтобы сравнивать с ответом сервера
   одним равенством. Нормализация («нет статуса» = «new») обязана совпадать
   с серверной (_status_counts в main.py) буква в букву: разойдись они —
   сверка находила бы расхождение там, где его нет, и тянула бы проект
   целиком на каждый разбор состава. */
function statusCountsOf(segments) {
  const out = {};
  segments.forEach(s => { const k = s.status || "new"; out[k] = (out[k] || 0) + 1; });
  return out;
}
function statusSig(counts) {
  return Object.keys(counts).sort().map(k => k + ":" + counts[k]).join(",");
}

/* ── Снимок состава прогона ───────────────────────────────────────────
   Счётчики задачи (job.counters) говорят, сколько сегментов шаг УЖЕ прошёл.
   Сколько ему всего — знает только разбор, а во время прогона он не
   пересчитывается: воркер на сервере ОДИН, и разбор дрался бы за него с самой
   работой. Поэтому состав, посчитанный сервером в момент запуска, сохраняем
   здесь — из него и вычитается сделанное.

   Лежит в localStorage, а не в состоянии компонента: прогон идёт на сервере и
   переживает и вкладку, и перезагрузку страницы — цифра «осталось» тоже должна.
   Снимка нет (прогон запущен из другого браузера) — показываем только сделанное
   и про остаток МОЛЧИМ: выдуманное число хуже отсутствующего. */
const RUN_SNAP_LS_KEY = "mcat_run_snapshot";
function readRunSnap() {
  try { return JSON.parse(localStorage.getItem(RUN_SNAP_LS_KEY) || "null"); }
  catch (e) { return null; }
}
function writeRunSnap(snap) {
  try { localStorage.setItem(RUN_SNAP_LS_KEY, JSON.stringify(snap)); }
  catch (e) { /* приватный режим */ }
}

/* Состояние шагов идущего составного прогона.

   Галочка означает ровно одно: шаг взял всё, что ему отвёл разбор. «Текущего»
   шага одного на весь прогон не существует и подсвечивать его нельзя: порция
   (5 сегментов) проходит ВСЕ выбранные шаги по очереди, поэтому пока перевод
   добирает своё в двадцатой порции, back-check уже отработал по девятнадцати.
   Точка у шага — «ещё берёт», и это правда для всех незакрытых шагов сразу.

   У ремонта остаток может кончиться раньше плана и наоборот: находки рождают
   проверки этого же прогона, разбор считал по прежним. Поэтому остаток
   обрезается нулём, а сделанное показывается как есть. */
function runStepRows(job, snap) {
  if (!job || job.kind !== "full") return [];
  const want = (job.params && job.params.steps) || FULL_STEP_KEYS;
  // Снимок опознаём по ТРОЙКЕ: номер + проект + время создания. Номера задач
  // живут в памяти процесса и после рестарта сервиса начинаются с единицы
  // заново, так что одного номера мало: чужой снимок сел бы на неродной прогон,
  // и полоса показала бы выдуманное «осталось» — ровно то враньё, которого мы
  // избегаем, когда снимка нет вовсе.
  const mine = snap && snap.jobId === job.id
    && snap.project === job.project && snap.created === job.created;
  const planned = (mine && snap.steps) || null;
  const counters = job.counters || {};
  return FULL_STEP_KEYS.filter(k => want.indexOf(k) !== -1).map(k => {
    const done = counters[k] || 0;
    const total = planned && planned[k] != null ? planned[k] : null;
    return { key: k, label: FULL_STEP_LABELS[k] || k, done: done, total: total,
             left: total == null ? null : Math.max(0, total - done),
             complete: total != null && done >= total };
  });
}

// ── Смета прогонов ───────────────────────────────────────────────────
// Кириллица ≈ 2.2 симв./токен, латиница ≈ 3.5. У моделей GPT-5.x в оплачиваемый
// вывод входят ещё и reasoning-токены — отсюда надбавка ×1.8.
// Считается по объёму текста: точную цену знает только ответ модели, поэтому
// везде подписано «ориентировочно». Лучше показать порядок суммы, чем ничего:
// прогон на 2600 сегментов и прогон на 30 отличаются в сто раз.
const REASONING_MULT = 1.8;
// Доля сегментов, попадающих в зону судьи. Только для ЕЩЁ НЕ ПРОВЕРЕННЫХ:
// у проверенных сервер отвечает точно (backcheck.needs_judge), и гадать про них
// значит занизить смету на короткие сегменты — их зона открыта до нуля.
const JUDGE_SHARE = 0.3;
/* Доля сегментов, на которых ревизия возвращает исправленный текст (с разбором
   для человека). Замер на боевом учебнике: 30 правок и 6 «оригинал повреждён»
   на 150 сегментов. Число нужно ровно для сметы — сколько выходных токенов
   купит шаг; работу оно не выбирает. */
const REVIEW_FIX_SHARE = 0.25;

/* Цена эмбеддингов приходит с сервера (/api/models → aux, embedModel). Числом
   в браузере она была вторым прайс-листом рядом с настоящим — ровно тем, от
   чего защищает правило «модели и цены живут в одном месте». Каталог ещё не
   пришёл — считаем эту строку нулём и молчим: выдуманная цена хуже пропущенной,
   а весит она сотые доли цента на весь проект. */
let AUX_PRICES = {}, EMBED_MODEL_ID = "";
function embedPrice() { return ((AUX_PRICES[EMBED_MODEL_ID] || {}).in) || 0; }

function reasoning(model) { return model && model.api === "modern" ? REASONING_MULT : 1; }

function priceOf(model, tokIn, tokOut) {
  /* Ждём ОБЪЕКТ модели, а не её id: передашь строку — `model.in` окажется
     undefined, цена станет NaN и на экране встанет «$NaN». Так и случилось,
     когда в смету ремонта добавили судью. Неизвестная цена — это null
     («не знаю»), а не NaN: null экран покажет прочерком. */
  if (!model || typeof model.in !== "number" || typeof model.out !== "number") return null;
  return (tokIn / 1e6) * model.in + (tokOut / 1e6) * model.out;
}

// kind: translate | backcheck | termcheck | termaudit | repair | medical_qa
// opts: { judge, judgeModel, secPerSeg }
function estimateRun(kind, targets, model, opts) {
  const o = opts || {};
  const n = targets.length;
  const srcChars = targets.reduce((a, s) => a + (s.source || "").length, 0);
  const tgtChars = targets.reduce((a, s) => a + (s.target || "").length, 0);
  const mult = reasoning(model);
  let tokIn = 0, tokOut = 0, cost = null, sec = n * EST_SEC_PER_SEG;

  if (kind === "translate") {
    tokIn = n * 500 + srcChars / 2.2;          // 500 ≈ системный промпт с глоссарием
    tokOut = (srcChars / 3.5) * mult;
    cost = priceOf(model, tokIn, tokOut);
  } else if (kind === "backcheck") {
    // Сегменты, которым нужен ТОЛЬКО судья, обратный перевод не покупают:
    // он у них уже есть, и сервер берёт его готовым (reuse в
    // _run_segment_backcheck — то же условие: проверка свежая, текст обратного
    // перевода на месте, делал его не тот, кто переводил). Считать им полный
    // back-check значило бы завысить смету вдвое на прогоне с разрешением
    // judge_all: там таких большинство, и кнопка обещала «≈ $5.81» за
    // работу, которой сервер не делает.
    const judgeOnly = o.judge
      ? targets.filter(s => s.backcheck && !s.backcheck.stale && s.backcheck.back
          && s.backcheck.score != null && s.backcheck.model !== s.provider)
      : [];
    const buying = judgeOnly.length ? targets.filter(s => judgeOnly.indexOf(s) === -1) : targets;
    const bChars = buying.reduce((a, s) => a + (s.target || "").length, 0);
    tokIn = buying.length * 200 + bChars / 3.5; // короткий промпт буквального перевода
    tokOut = (bChars / 2.2) * mult;             // обратный перевод на язык оригинала
    cost = priceOf(model, tokIn, tokOut);
    // Судья вызывается только в своей зоне и не вызывается при жёсткой находке.
    // У сегментов, которые уже проверялись, гадать не нужно: сервер посчитал
    // needs_judge своей зоной (у короткого оригинала она открыта до нуля) и
    // прислал ответ. Доля JUDGE_SHARE остаётся только для непроверенных —
    // про них не знает никто. Без этого смета занижена ровно на короткие
    // сегменты, то есть на заголовки, которых в учебнике сотни.
    if (o.judge && o.judgeModel) {
      const known = targets.filter(s => s.backcheck && s.backcheck.score != null);
      // judgeAll — прогон с разрешением судить и выше зоны: needs_judge
      // сервер считает по ОБЫЧНОЙ зоне, и по нему смета не увидела бы ровно
      // те бесспорные сегменты, ради которых разрешение дано. Несудимые
      // с баллом — верхняя оценка (жёсткие отметки в ней тоже): завышенная
      // смета честнее заниженной.
      const jn = known.filter(s => o.judgeAll
          ? !s.backcheck.judged : s.backcheck.needs_judge).length
        + (n - known.length) * JUDGE_SHARE;
      const jshare = n ? jn / n : 0;
      cost += priceOf(o.judgeModel, jn * 400 + (srcChars * jshare) / 1.1,
                      jn * 250 * reasoning(o.judgeModel));
    }
    cost += ((srcChars + tgtChars) / 3 / 1e6) * embedPrice();  // эмбеддинги
    sec = n * EST_SEC_PER_SEG;
  } else if (kind === "termcheck") {
    tokIn = n * 450 + (srcChars + tgtChars) / 3;
    tokOut = n * 250 * mult;                   // короткий JSON с находками
    cost = priceOf(model, tokIn, tokOut);
  } else if (kind === "repair") {
    // Ремонт = вызов правки + перепроверка теми проверками, что ругались.
    tokIn = n * 600 + (srcChars + tgtChars * 2) / 3;
    tokOut = (tgtChars / 3.5) * mult;
    cost = priceOf(model, tokIn, tokOut);
    if (o.recheckModel) {
      cost += priceOf(o.recheckModel, n * 300 + tgtChars / 3.5,
                      (tgtChars / 2.2) * reasoning(o.recheckModel));
    }
    // Судья. Ремонт зовёт его СИММЕТРИЧНО: там, где он участвовал в прежней
    // оценке, перепроверка зовёт его тоже (judge_after на сервере) — иначе
    // вердикт сравнивался бы с сырым измерением. Значит вызовы покупаются
    // и при ВЫКЛЮЧЕННОМ тумблере, и без этой строки смета их не считает,
    // а её число уходит в est_cost и калибрует поправку estRatio по всей
    // системе. Считается по сохранённому признаку `backcheck.judged`,
    // а не по правилу зоны: правило зоны живёт на сервере.
    if (o.judgeModel) {
      const jdone = targets.filter(s => s.backcheck && s.backcheck.judged).length;
      const jn = jdone + (o.judge ? (n - jdone) * JUDGE_SHARE : 0);
      if (jn > 0) {
        const jshare = n ? jn / n : 0;
        const jc = priceOf(o.judgeModel, jn * 400 + (srcChars * jshare) / 1.1,
                           jn * 250 * reasoning(o.judgeModel));
        /* Цена судьи неизвестна — вся смета шага становится «не знаю».
           Прибавить ноль значило бы показать сумму меньше настоящей. */
        cost = (jc == null || cost == null) ? null : cost + jc;
      }
    }
    sec = n * EST_SEC_PER_SEG * 2;             // правка + перепроверка
  } else if (kind === "review") {
    // Вход тот же, что у сверки терминов: соседи + оригинал + перевод.
    // Выход СЧИТАЕТСЯ ДВУМЯ ЧАСТЯМИ и это не педантизм: ревизор отвечает
    // либо «годится» (несколько токенов), либо готовым текстом с разбором.
    // Считать разбор на каждом сегменте — завысить смету втрое: на боевом
    // замере 150 сегментов правки потребовали 20%, а стоил прогон $0.33,
    // то есть $0.0022 на сегмент против $0.009 по «разбору всегда».
    tokIn = n * 450 + (srcChars * 3 + tgtChars) / 2.6;
    /* Множитель рассуждения — ТОЛЬКО на части с правкой. Ответ «годится» —
       это несколько токенов, думать там не над чем, и умножать их на 1.8
       значит завышать смету на ровном месте. Сверка с боевым замером
       (150 сегментов, Terra, $0.3259): со множителем на всём выходе формула
       давала $0.49 (+51%), так — $0.41 (+26%). Завышение осталось намеренно:
       заниженная смета хуже завышенной, а замер пока ОДИН и на одной модели. */
    tokOut = n * 10 + REVIEW_FIX_SHARE * (n * 200 + tgtChars / 3.5) * mult;
    cost = priceOf(model, tokIn, tokOut);
  } else if (kind === "termaudit") {
    // Один вызов на сегмент: соседи + список приказных терминов -> вердикт
    // по каждому. Соседи и есть основной вход, поэтому исходника втрое.
    tokIn = n * 350 + (srcChars * 3 + tgtChars) / 2.6;
    tokOut = n * 200 * mult;                   // короткий JSON по терминам
    cost = priceOf(model, tokIn, tokOut);
  } else if (kind === "medical_qa") {
    tokIn = n * 200 + tgtChars / 3.5;
    tokOut = (tgtChars / 2.2) * mult;
    cost = priceOf(model, tokIn, tokOut);
  }
  return { cost, seconds: sec, tokIn: Math.round(tokIn), tokOut: Math.round(tokOut), count: n };
}

// Смета пакетного перевода — та же функция, отдельное имя ради модалки сметы
function estimateBatch(targets, model) {
  const e = estimateRun("translate", targets, model);
  return { chars: targets.reduce((a, s) => a + (s.source || "").length, 0),
           cost: e.cost, seconds: e.seconds };
}

// Строка сметы под кнопкой запуска: одинаковая во всех карточках
function EstLine({ est }) {
  if (!est || !est.count) return null;
  return React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
    TR("Ориентировочно: "),
    React.createElement("b", { style: { color: "var(--text-2)" } },
      est.cost != null ? fmtCost(est.cost) : "—"),
    " · " + fmtDuration(est.seconds) + TR(" на ") + est.count + TR(" сегм."));
}

// Чем сегмент переведён. seg.provider проставляется бэкендом в момент перевода.
// У сегментов, переведённых до появления поля, его нет — тогда показываем
// приблизительное значение по маршруту и помечаем его как неточное.
function providerOf(seg) {
  if (seg.provider) return { id: seg.provider, exact: true };
  if (!seg.target || !seg.target.trim()) return null;
  if (seg.route === "EXACT_TM") return { id: "tm", exact: false };
  // Исторический маршрут: так помечены сегменты, переведённые до того, как
  // Google убрали из системы. Новые так не появляются.
  if (seg.route === "GOOGLE_SAFE") return { id: "google", exact: false };
  if (seg.route === "GPT_REQUIRED") return { id: "gpt", exact: false };
  return null;
}

function providerLabel(p, models) {
  if (!p) return null;
  if (p.id === "google") return "Google";
  if (p.id === "tm") return "TM";
  if (p.id === "gpt") return "GPT";
  const m = (models || []).find(x => x.id === p.id);
  return m ? m.label : p.id;
}

// Поиск по сегментам. Регистр не важен, «ё» и «е» считаются одной буквой:
// в русских текстах они пишутся вперемешку, и точный поиск иначе врёт.
const SEARCH_SCOPES = ["all", "src", "tgt"];
function normText(t) { return (t || "").toLowerCase().replace(/ё/g, TR("е")); }

function segMatches(seg, q, scope) {
  const needle = normText(q);
  if (!needle) return true;
  const inSrc = scope !== "tgt" && normText(seg.source).includes(needle);
  const inTgt = scope !== "src" && normText(seg.target).includes(needle);
  return inSrc || inTgt;
}

// Подсветка совпадений. normText сохраняет длину строки (ё→е и lowercase —
// один символ в один), поэтому индексы из нормализованной строки годятся для
// исходной. Если длина всё же разъехалась — отдаём текст без подсветки.
function markHits(text, q) {
  const src = text || "";
  const needle = normText(q);
  if (!needle) return src;
  const hay = normText(src);
  if (hay.length !== src.length || !hay.includes(needle)) return src;
  const out = [];
  let i = 0, key = 0;
  for (let idx = hay.indexOf(needle); idx !== -1; idx = hay.indexOf(needle, i)) {
    if (idx > i) out.push(src.slice(i, idx));
    out.push(React.createElement("mark", { key: key++, className: "hl" }, src.slice(idx, idx + needle.length)));
    i = idx + needle.length;
  }
  if (i < src.length) out.push(src.slice(i));
  return out;
}

// ── Группировка «что уже прогонялось» ────────────────────────────────
// Чистые функции: по ним карточка считает, что предложить, а прогон — что брать.
// Ключ проверки терминологии различает «с замечаниями» и «без»: после правок
// перепрогоняют обычно именно первые.
function tcGroupKey(s) {
  const tc = s.termcheck;
  if (!tc) return "none";
  if (tc.stale) return "stale";
  if (tc.model === "skip") return "skip";
  return ((tc.findings || []).length ? "hit:" : "ok:") + (tc.model || "unknown");
}

// Ранг модели из каталога /api/models. null — «сила неизвестна».
function rankOf(models, id) {
  const m = (models || []).find(x => x.id === id);
  return m && m.rank != null ? m.rank : null;
}

// Отмечено по умолчанию: непроверенное, устаревшее и проверенное более СЛАБОЙ
// моделью. Тот же закон, что у _rank_not_weaker на сервере, и это обязательно:
// иначе таблица предлагала бы отдельным прогоном перепроверить ровно то, что
// общий прогон только что законно пропустил, — и числа под соседними кнопками
// противоречили бы друг другу. Усилить проверку можно всегда, ослабить — нет.
function tcGroupDefault(key, model, models) {
  if (key === "none" || key === "stale") return true;
  if (key === "skip") return false;
  const i = key.indexOf(":");
  if (i === -1) return false;
  const had = key.slice(i + 1);
  if (had === model) return false;
  const rh = rankOf(models, had), rw = rankOf(models, model);
  if (rh == null || rw == null) return true;   // не знаем — проверяем заново
  return rh < rw;
}

// tried приходит с бэкенда: этот же текст уже проходил через ремонт
function rpGroupKey(s, model) {
  const r = s.repair;
  if (!r) return "none";
  /* Заход, отменённый СБОЕМ перепроверки, сервер намеренно не засчитывает
     (source_hash не пишется), поэтому tried у него false. В «текст менялся»
     такие класть нельзя: текст как раз не менялся, не состоялась проверка. */
  if (r.retryable && !r.tried) return r.retryReason === "rules" ? "rules" : "failed";
  if (!r.tried) return "changed";
  /* Другая модель — другой заход (repair.triedModels с сервера): клеймо чужой
     модели выбранную не держит, и сервер берёт такие сегменты «со вторым
     мнением» — группа отмечена по умолчанию, иначе строка плана обещала бы N,
     а кнопка под ней отправляла меньше. Сравниваем только ЯВНО выбранную
     модель: пустой выбор означает модель по умолчанию, чей id браузер
     не разрешает, — тогда честнее прежняя группа, чем угаданная. */
  if (model) {
    const tried = r.triedModels || (r.model ? [r.model] : null);
    if (tried && tried.indexOf(model) === -1) return "second";
  }
  return r.applied ? "applied" : "rejected";
}

/* Второй заход по тому же тексту даёт то же самое, поэтому группы уже
   чинившихся по умолчанию сняты. «failed» — не второй заход: там первый
   не состоялся, и сегмент ждёт своей очереди наравне с нетронутыми. */
function rpGroupDefault(key) {
  /* «rules» отмечена по умолчанию: прежний вердикт вынесен правилом, которого
     больше нет, а значит он ничего не говорит о нынешнем заходе. Это не второй
     заход по тем же правилам, ради которого группы «уже чинилось» и сняты.
     «second» — тоже: другая модель даст другой ответ, сервер берёт такие сам. */
  return key === "none" || key === "changed" || key === "failed"
    || key === "rules" || key === "second";
}

/* ── Составной прогон: весь конвейер одной кнопкой ──────────────────────
   Порядок ЗДЕСЬ повторяет FULL_RUN_STEPS на сервере и обязан ему совпадать:
   карточка показывает, что произойдёт, а произойдёт то, что решил сервер.
   Ремонт идёт перед детерминированными проверками — проверка описывает окончательный текст,
   а не тот, который через шаг перепишут.

   Состав сегментов больше не считается здесь: его отдаёт /run-plan тем же
   кодом, который потом и работает. Раньше браузер считал своими правилами,
   сервер отбирал своими, и снятая галочка уменьшала смету, но не работу. */
// Названия и подписи шагов живут в строках таблицы (fullRunRows) — здесь
// только порядок, и он обязан совпадать с FULL_RUN_STEPS на сервере: карточка
// показывает, что произойдёт, а произойдёт то, что решил сервер.
/* Порядок и состав — зеркало FULL_RUN_STEPS на сервере. Забыть здесь шаг
   значит: галочка снята по умолчанию, состав шага пуст, строка показывает
   «—», кнопка соло погашена, в задачу уходит список без него — а сервер
   при этом планирует работу и обещает её человеку. Ровно то расхождение,
   ради которого состав вынесен на сервер. */
const FULL_STEP_KEYS = ["translate", "review", "backcheck", "termcheck", "termaudit",
                        "repair", "medical_qa"];

function fmtDuration(sec) {
  if (sec < 90) return Math.round(sec) + TR(" с");
  if (sec < 5400) return Math.round(sec / 60) + TR(" мин");
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return h + TR(" ч") + (m ? " " + m + TR(" мин") : "");
}

function TabEditor({ store, toast }) {
  const project = store.activeProject;
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState(() => {              // где искать: везде / оригинал / перевод
    let v = null;
    try { v = localStorage.getItem(SEARCH_SCOPE_LS_KEY); } catch (e) { /* приватный режим */ }
    return SEARCH_SCOPES.indexOf(v) !== -1 ? v : "all";
  });
  const [riskFilter, setRiskFilter] = useState("all");
  /* Откуда сегмент: из абзаца документа или из надписи на картинке. Без этого
     фильтра распознанное растворяется среди двух с половиной тысяч строк,
     а проверять его надо отдельно — там своя цена ошибки. */
  const [originFilter, setOriginFilter] = useState("all");
  const [height, setHeight] = useState(440);
  const [selId, setSelId] = useState(project ? (project.segments[0] && project.segments[0].id) : null);
  const [busy, setBusy] = useState({});       // {segId: 'translate'|'qa'}
  const [batchRun, setBatchRun] = useState(null); // {engine, done, total} — производное от job
  const [job, setJob] = useState(null);           // активный серверный прогон
  // Состав шагов запущенного прогона: из него полоса прогресса берёт «осталось».
  const [runSnap, setRunSnap] = useState(readRunSnap);
  const lastJobId = useRef(null);                 // прогон, результат которого ещё не забрали
  const reportedJob = useRef(null);               // чтобы отчитаться о завершении один раз
  const pullBusy = useRef(null);                  // подстановка проекта уже идёт
  const pullFails = useRef(0);                    // сколько раз подряд не удалось её забрать
  const driftAt = useRef(0);                      // когда в последний раз сверка тянула проект
  const [checkedSegs, setCheckedSegs] = useState(new Set()); // ручной выбор
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(1);
  /* Переход к сегменту по номеру — маленькая строка над колонкой «#».
     Показывается не страница, а ЗОНА: сегменты ДО и ПОСЛЕ введённого
     (ZONE_HALF в каждую сторону). Страница на десять строк на этот вопрос
     не отвечает — искомый сегмент оказывается то первой строкой, то
     последней, и «что стояло перед ним» видно через раз. */
  const [jump, setJump] = useState("");
  const [zone, setZone] = useState(null);        // номер сегмента-центра | null
  /* Переход снимает фильтры и меняет страницу, а на то и другое подвешены
     сбросы (страница — на первую, выбранный сегмент — в null), которые
     утащили бы нас обратно. Флажок живёт ровно один коммит: его гасит
     эффект БЕЗ списка зависимостей, объявленный ПОСЛЕ этих сбросов. */
  const jumpRef = useRef(false);
  /* За каким составом проекта уже ходили: "id:число сегментов". Ответ придёт
     с новым числом, эффект пересчитается — и без этой отметки он пошёл бы
     за проектом снова. */
  const staleFetch = useRef(null);
  const [revertTarget, setRevertTarget] = useState(null);
  const [propagateAsk, setPropagateAsk] = useState(null);  // предложение разослать перевод по повторам
  const [gptModels, setGptModels] = useState([]);          // каталог с ценами из /api/models
  const [gptModel, setGptModel] = useState(() => {
    try { return localStorage.getItem(GPT_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [batchPlan, setBatchPlan] = useState(null);        // смета перед запуском GPT-пакета
  const [retranslate, setRetranslate] = useState(false);   // перегнать заново уже переведённые
  const [providerPick, setProviderPick] = useState(null);  // Set<ключ группы> | null = по умолчанию
  const [bcModel, setBcModel] = useState(() => {
    try { return localStorage.getItem(BC_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [tcModel, setTcModel] = useState(() => {
    try { return localStorage.getItem(TC_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [tcxModel, setTcxModel] = useState(() => {
    try { return localStorage.getItem(TCX_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [rpModel, setRpModel] = useState(() => {
    try { return localStorage.getItem(RP_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [rvModel, setRvModel] = useState(() => {
    try { return localStorage.getItem(RV_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [impact, setImpact] = useState(null);     // сегменты, не соответствующие одобренным терминам
  const [impactBusy, setImpactBusy] = useState(false);
  const [impactConfirmed, setImpactConfirmed] = useState(false);  // трогать ли подтверждённые
  const [tkSum, setTkSum] = useState(null);       // корзины «под ключ» с сервера (/analysis) для карточки «Анализ»
  const [bcJudge, setBcJudge] = useState(false);          // LLM-судья для средней зоны
  const [judgeModel, setJudgeModel] = useState(() => {
    try { return localStorage.getItem(JUDGE_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [judgeZone, setJudgeZone] = useState([50, 97]);
  // Уровни находок termcheck, по которым работает ремонт. Приходят с сервера
  // (/api/models → termcheckActionable): держать их здесь литералом значит
  // однажды разойтись с _repair_findings и показать под кнопкой число,
  // которого прогон не найдёт. Значение по умолчанию — на случай, если ответ
  // ещё не пришёл; оно совпадает с серверным TERMCHECK_ACTIONABLE.
  const [tcActionable, setTcActionable] = useState(["critical", "major", "minor"]);
  // Порог «оригинал слишком короток, чтобы лексика что-то значила». Тоже
  // с сервера: подсказка у тумблера судьи называет это число словами, и вбитое
  // сюда оно разошлось бы с medical_qa.BACKCHECK_MIN_STEMS молча.
  const [bcMinStems, setBcMinStems] = useState(3);
  // По умолчанию выключено: back-check ничего не портит, а проверить подтверждённое
  // даже полезнее — если ошибка прошла ревью, узнать об этом важнее всего.
  const [bcSkipConfirmed, setBcSkipConfirmed] = useState(() => {
    try { return localStorage.getItem(BC_SKIP_CONFIRMED_LS_KEY) === "1"; } catch (e) { return false; }
  });
  const [bcGroupPick, setBcGroupPick] = useState(null);   // Set<ключ группы> | null = по умолчанию
  const [tcGroupPick, setTcGroupPick] = useState(null);   // то же для проверки терминологии
  const [rpGroupPick, setRpGroupPick] = useState(null);   // то же для ремонта
  // Чинить ли заверенное человеком. По умолчанию выключено и НАМЕРЕННО
  // не запоминается: это разрешение на конкретный прогон, а не настройка.
  // Переключатель живёт в раскрытой строке ремонта, поэтому взведённым
  // с прошлого раза он был бы не виден — а главная кнопка всё равно снимала бы
  // отметку «подтвердил человек», в том числе в другом проекте.
  const [rpFixConfirmed, setRpFixConfirmed] = useState(false);
  // То же самое, но для переперевода (шаг «Перевод», solo-запуск): без него
  // подтверждённые сегменты не показываются даже в разбивке «переведено
  // через» — их вообще не с чем перевести повторно, пока человек явно не
  // разрешит. Composite-прогон («Перевести и проверить») этот флаг не видит
  // и никогда не трогает подтверждённые — см. _job_chunk_full на бэкенде.
  const [rtFixConfirmed, setRtFixConfirmed] = useState(false);
  // Составной прогон: какие шаги входят. null = все.
  const [fullSteps, setFullSteps] = useState(null);
  // Раскрыта одна строка за раз: развёрнутые все сразу — это снова простыня,
  // из которой человек выковыривает нужную галочку.
  const [openStep, setOpenStep] = useState(null);
  // Разбор автоодобрения (dry_run): что попадёт в глоссарий и чем это
  // подтверждено. Считает сервер, вызовов модели внутри нет.
  const [autoPreview, setAutoPreview] = useState(null);
  /* Разрешение на приказы по согласию сегментов — на один запуск, как и в
     панели «Знаний»: не в localStorage. Храним ПРОЕКТ, которому оно выдано,
     а не булев флаг: сброс эффектом при смене проекта успевал отправить
     разрешение прошлого проекта в разбор нового и оставить его цифры на
     экране под выключенным тумблером. */
  const [ordersFor, setOrdersFor] = useState(null);
  const termOrders = !!project && ordersFor === project.id;
  const PAGE_SIZE = 10;
  const ZONE_HALF = 10;      // сколько сегментов показывать до и после введённого

  // Каталог моделей грузим один раз; пустой список — значит бэкенд старый или ключа нет
  useEffect(() => {
    if (!window.API || !window.API.models) return;
    window.API.safeCall(() => window.API.models()).then(d => {
      if (!d || !d.models) return;
      setGptModels(d.models);
      setGptModel(cur => (cur && d.models.some(m => m.id === cur)) ? cur : (d.default || ""));
      setBcModel(cur => (cur && d.models.some(m => m.id === cur)) ? cur : (d.backcheckDefault || d.default || ""));
      setJudgeModel(cur => (cur && d.models.some(m => m.id === cur)) ? cur : (d.judgeDefault || d.default || ""));
      setTcModel(cur => (cur && d.models.some(m => m.id === cur)) ? cur : (d.termcheckDefault || d.default || ""));
      setRpModel(cur => (cur && d.models.some(m => m.id === cur)) ? cur : (d.repairDefault || d.default || ""));
      // Сверка терминов сюда не попадала, и её выбор оставался пустым: список
      // моделей рисовался без выбранной строки, а цены у шага не было вовсе —
      // от одного такого шага смета ГЛАВНОЙ кнопки становилась прочерком.
      setTcxModel(cur => (cur && d.models.some(m => m.id === cur)) ? cur : (d.termauditDefault || d.default || ""));
      setRvModel(cur => (cur && d.models.some(m => m.id === cur)) ? cur : (d.reviewDefault || d.default || ""));
      AUX_PRICES = d.aux || {};
      EMBED_MODEL_ID = d.embedModel || "";
      // Полосы кладём в общее место: по ним красят балл и эта таблица,
      // и карточка сегмента, и экран экспорта.
      window.setBcBands(d.backcheckBands);
      if (d.judgeZone) setJudgeZone(d.judgeZone);
      if (d.termcheckActionable && d.termcheckActionable.length) setTcActionable(d.termcheckActionable);
      if (d.backcheckMinStems) setBcMinStems(d.backcheckMinStems);
    });
  }, []);

  // Сменились модель, выборка или сам режим — возвращаем выбор групп к умолчанию
  useEffect(() => { setProviderPick(null); },
    [retranslate, gptModel, store.segmentFilter, checkedSegs.size]);
  useEffect(() => { setBcGroupPick(null); },
    [bcModel, bcJudge, bcSkipConfirmed, store.segmentFilter, checkedSegs.size]);
  /* Подстановка проекта ЦЕЛИКОМ — одна на все поводы (конец прогона, сверка
     статусов). Три правила, и каждое куплено дорого:

     1) идёт РОВНО ОДНА за раз. setJob(null) пересоздаёт эффект опроса, и новый
        экземпляр немедленно делает свой tick — без замка конец каждого прогона
        стоил бы двух-трёх ответов по пять мегабайт подряд, причём на
        единственном воркере uvicorn, который в этот момент занят;
     2) отставший ответ не затирает обогнавший — это следствие первого правила,
        а не отдельная проверка: второго запроса просто нет. Иначе старый
        снимок лёг бы поверх нового и с экрана пропала бы отметка «подтвердил
        человек», которую только что поставили;
     3) кладём по id ИЗ ЗАМЫКАНИЯ, а не в «текущий» проект: человек мог уйти
        в другой, и результат обязан лечь туда, откуда его просили.

     Три исхода, а не два: свежий проект, null (сходили и не вышло) и undefined
     (не ходили — тянет другой заход). Смешать последние два нельзя, иначе
     счётчик попыток сгорал бы на заходах, которых не было. */
  const pullProject = async (pid) => {
    if (pullBusy.current) return undefined;
    pullBusy.current = pid;
    try {
      const fresh = await window.API.safeCall(() => window.API.getProject(pid));
      if (!fresh || !fresh.segments) return null;
      store.replaceProjectSegments(pid, fresh.segments);
      return fresh;
    } finally { pullBusy.current = null; }
  };
  // Опрос прогонов. Идёт работа — раз в 2 с, простой — раз в 15 с: прогон мог
  // быть запущен из другой вкладки или до перезагрузки страницы.
  useEffect(() => {
    if (!window.API || !window.API.listJobs || !project) return;
    let dead = false;
    const tick = async () => {
      const res = await window.API.safeCall(() => window.API.listJobs(project.id));
      if (dead || !res) return;
      const active = (res.active || [])[0] || null;
      setJob(active);
      if (active) {
        lastJobId.current = active.id;
        return;
      }
      // Прогон закончился между опросами — отчитываемся и подтягиваем результат
      const finished = (res.jobs || []).find(j => j.id === lastJobId.current);
      if (finished && finished.status !== "queued" && finished.status !== "running") {
        /* Отчёт — один раз, подстановка — сколько понадобится: события разные,
           и отметки у них разные. Прогон опознаётся ТРОЙКОЙ «номер + проект +
           время создания» — той же, что и снимок состава (см. runStepRows):
           номера задач живут в памяти процесса и после рестарта сервиса
           начинаются с единицы заново, поэтому по голому номеру отчёт
           о чужом третьем прогоне считался бы уже сделанным и пропал бы
           молча — вместе с ценой, ошибками и обновлением карточек. */
        const key = finished.id + ":" + finished.project + ":" + finished.created;
        if (reportedJob.current !== key) {
          reportedJob.current = key;
          reportJobResult(finished);
          loadImpact();
          loadAutoPreview();    // прогон мог родить новых кандидатов
          loadAnalysis(true);   // корзины «под ключ» изменились этим же прогоном
        }
        /* Проверки dead здесь НЕТ, и это не недосмотр. Строкой выше
           setJob(null) меняет зависимость !!job — React делает cleanup
           эффекта, и dead становится true ЗАДОЛГО до того, как
           пятимегабайтный проект доедет по сети. То есть условие отменяло
           подстановку не иногда, а ВСЕГДА: человек видел отчёт о прогоне
           и свежие карточки, а таблица оставалась с допрогонными статусами —
           «Новые 25» там, где на сервере ноль. */
        const fresh = await pullProject(project.id);
        if (fresh === undefined) return;    // тянет другой заход — он и отчитается
        if (fresh) { lastJobId.current = null; pullFails.current = 0; return; }
        /* Не забрали. Отметку не снимаем — следующий опрос зайдёт снова, иначе
           одна моргнувшая сеть оставляет таблицу устаревшей навсегда. Но и
           бесконечно долбить самый тяжёлый эндпоинт нельзя: воркер ОДИН.
           Кончились попытки — сдаёмся ВСЛУХ, потому что молча оставленные
           допрогонные статусы это ровно тот баг, который здесь и чинится. */
        pullFails.current += 1;
        if (pullFails.current >= PULL_TRIES) {
          lastJobId.current = null;
          pullFails.current = 0;
          toast.warning(TR("Результат прогона не забран"),
            TR("Сервер не отдал проект ") + PULL_TRIES + TR(" раза подряд. Обновите страницу: ")
            + TR("иначе в таблице останутся статусы, какими они были до прогона."));
        }
      }
    };
    tick();
    const id = setInterval(tick, job ? 2000 : 15000);
    return () => { dead = true; clearInterval(id); };
  }, [project && project.id, !!job]);

  // Прогресс в карточках читается из job — форма та же, что была у локального цикла
  useEffect(() => {
    setBatchRun(job ? { engine: job.kind, done: job.done, total: job.total } : null);
  }, [job && job.id, job && job.done, job && job.total, job && job.status]);

  // Пока прогон идёт, подтягиваем ТОЛЬКО что он успел посчитать. Раньше сюда
  // каждые 8 секунд приезжал весь проект — на 2670 сегментах это 5 МБ на запрос
  // и заметно подвисающая таблица. Теперь сервер называет обработанные id,
  // и мы забираем именно их.
  useEffect(() => {
    if (!job || job.status !== "running" || !window.API || !window.API.fetchSegments) return;
    let dead = false;
    const id = setInterval(async () => {
      const ids = (job.recent || []).slice();
      if (!ids.length) return;
      const res = await window.API.safeCall(() => window.API.fetchSegments(project.id, ids));
      if (dead || !res || !res.segments) return;
      res.segments.forEach(s => store.updateSegment(project.id, s.id, s));
    }, 3000);
    return () => { dead = true; clearInterval(id); };
  }, [job && job.id, job && job.status, job && (job.recent || []).join(",")]);

  // Расхождения с одобренными терминами считает сервер тем же матчером, что и
  // инъекция в промпт. Пересчитываем при смене проекта и после каждого прогона:
  // одобрили термин и перевели заново — счётчик должен упасть сам.
  /* byHand — нажали «Пересчитать» руками. Тогда отвечаем словами: расчёт
     идёт доли секунды, и «нажал, ничего не произошло» неотличимо от сломанной
     кнопки. Сравниваем с прежним числом — «столько же» это тоже ответ. */
  const loadImpact = async (byHand) => {
    if (!window.API || !window.API.glossaryImpact || !project) return;
    setImpactBusy(true);
    const before = impact ? impact.segments.length : null;
    const res = await window.API.safeCall(() => window.API.glossaryImpact(project.id, !!byHand));
    setImpactBusy(false);
    if (!res || !res.ok) {
      if (byHand) toast.error(TR("Пересчёт не выполнен"), TR("Сервер не ответил."));
      return;
    }
    setImpact(res);
    if (!byHand) return;
    const now = res.segments.length;
    if (before === null || before === now)
      toast.info(TR("Пересчитано: ") + now, TR("Столько сегментов расходится с глоссарием."));
    else
      toast.success(TR("Пересчитано: было ") + before + TR(", стало ") + now,
        now < before ? TR("Расхождений стало меньше на ") + (before - now)
                     : TR("Расхождений стало больше на ") + (now - before));
  };
  // Разбор автоодобрения в режиме «показать»: сервер считает вердикты и
  // возвращает, что попадёт и чем подтверждено. Ничего не меняет и не стоит
  // денег, поэтому обновляем вместе с отчётом о глоссарии.
  // Ответ может идти секунды (до 200 внешних запросов), а пользователь за это
  // время успевает переключить проект. Без сверки id разбор ЧУЖОГО проекта
  // лёг бы в карточку, и кнопка «Одобрить» считала бы одно, а применяла другое.
  const loadAutoPreview = async () => {
    if (!window.API || !window.API.autoApprove || !project) return;
    const pid = project.id;
    const res = await window.API.safeCall(() => window.API.autoApprove({
      project: pid, dry_run: true, allow_verified: termOrders }));
    if (res && res.ok && store.activeProject && store.activeProject.id === pid) {
      setAutoPreview(res);
    }
  };
  /* Корзины «под ключ» для карточки «Анализ» в блоках запуска. Считает СЕРВЕР
     (/analysis → turnkey) теми же предикатами, что и прогон, — браузер числа
     не повторяет: второй расчёт однажды разошёлся бы с работой. До первого
     перевода карточки нет и запрос не идёт: в проекте из одних «новых»
     корзины тривиальны, а интерфейс они бы только загромождали.
     afterRun — прогон только что закончился: копия браузера могла ещё не
     узнать о новых статусах, но сам факт прогона открывает карточку. */
  const loadAnalysis = async (afterRun) => {
    if (!window.API || !window.API.analysis || !project) return;
    // «нет статуса = new» — та же нормализация, что в statusCountsOf и на сервере.
    const started = project.segments.some(s => (s.status || "new") !== "new");
    if (!started && !afterRun) return;
    const pid = project.id;
    const res = await window.API.safeCall(() => window.API.analysis(pid));
    // Сверка id — как у loadAutoPreview: ответ мог доехать после смены проекта.
    if (res && res.ok && res.turnkey && store.activeProject && store.activeProject.id === pid) {
      setTkSum(res);
    }
  };
  useEffect(() => { setTkSum(null); loadAnalysis(); }, [project && project.id]);
  /* Человек изменил состояние сегмента руками (подтвердил, снял отметку).
     Пересчитывать это обязана та же сторона, что и после прогона: корзины
     считает СЕРВЕР, и без запроса карточка «Анализ» держала бы доподтверждённые
     цифры до перезагрузки страницы — то есть звала бы доделывать работу,
     которую человек только что сделал. Раньше это стоило секунд единственного
     воркера, теперь разбор пересчитывает только изменившиеся сегменты
     (`_ANALYSIS_ROWS` на сервере) и отвечает за десятые доли секунды.
     Соответствие глоссарию тянем тем же движением: подтверждение меняет
     в нём срез «из них подтверждённых». */
  const refreshAfterHand = () => { loadAnalysis(true); loadImpact(); };

  // Один эффект на оба: разрешение выводится из id проекта (см. ordersFor),
  // поэтому лишнего прохода при смене проекта не будет. Цифра на кнопке
  // обязана считаться с теми же параметрами, с которыми пойдёт задача.
  useEffect(() => { setImpact(null); setAutoPreview(null); loadImpact(); loadAutoPreview(); },
    [project && project.id, termOrders]);

  // Смена проекта гасит разрешение: заверял сегменты человек в ТОМ проекте,
  // и переносить на новый разрешение их переписать нельзя.
  useEffect(() => { setRpFixConfirmed(false); }, [project && project.id]);
  useEffect(() => { setRtFixConfirmed(false); }, [project && project.id]);

  useEffect(() => { setTcGroupPick(null); }, [tcModel, store.segmentFilter, checkedSegs.size]);
  useEffect(() => { setRpGroupPick(null); }, [rpModel, store.segmentFilter, checkedSegs.size]);

  const gptModelInfo = gptModels.find(m => m.id === gptModel) || null;
  const pickRpModel = (id) => {
    setRpModel(id);
    try { localStorage.setItem(RP_MODEL_LS_KEY, id); } catch (e) { /* приватный режим — не страшно */ }
  };

  const pickTcModel = (id) => {
    setTcModel(id);
    try { localStorage.setItem(TC_MODEL_LS_KEY, id); } catch (e) { /* приватный режим — не страшно */ }
  };

  const pickTcxModel = (id) => {
    setTcxModel(id);
    try { localStorage.setItem(TCX_MODEL_LS_KEY, id); } catch (e) { /* приватный режим */ }
  };

  const pickRvModel = (id) => {
    setRvModel(id);
    try { localStorage.setItem(RV_MODEL_LS_KEY, id); } catch (e) { /* приватный режим */ }
  };

  const pickScope = (v) => {
    setScope(v);
    try { localStorage.setItem(SEARCH_SCOPE_LS_KEY, v); } catch (e) { /* приватный режим — не страшно */ }
  };

  const pickGptModel = (id) => {
    setGptModel(id);
    try { localStorage.setItem(GPT_MODEL_LS_KEY, id); } catch (e) { /* приватный режим — не страшно */ }
  };
  const bcModelInfo = gptModels.find(m => m.id === bcModel) || null;
  const pickBcModel = (id) => {
    setBcModel(id);
    try { localStorage.setItem(BC_MODEL_LS_KEY, id); } catch (e) { /* приватный режим — не страшно */ }
  };
  const toggleRpFixConfirmed = () => setRpFixConfirmed(v => !v);
  const toggleBcSkipConfirmed = () => setBcSkipConfirmed(v => {
    const next = !v;
    try { localStorage.setItem(BC_SKIP_CONFIRMED_LS_KEY, next ? "1" : "0"); } catch (e) { /* приватный режим */ }
    return next;
  });
  // Кандидаты back-check до отбора по группам «чем уже проверено»
  const bcCandidate = (s, idSet) =>
    (s.target || "").trim() &&
    !(bcSkipConfirmed && s.status === "confirmed") &&
    (!idSet || idSet.has(s.id));

  const judgeModelInfo = gptModels.find(m => m.id === judgeModel) || null;
  // Объявлено ЗДЕСЬ, а не рядом со строками шагов: смета главной кнопки
  // (fullEst) считается выше по файлу, а const до объявления не доступен.
  const tcxModelInfo = gptModels.find(m => m.id === tcxModel) || null;
  const tcModelInfo = gptModels.find(m => m.id === tcModel) || null;
  const rpModelInfo = gptModels.find(m => m.id === rpModel) || null;
  const rvModelInfo = gptModels.find(m => m.id === rvModel) || null;
  const pickJudgeModel = (id) => {
    setJudgeModel(id);
    try { localStorage.setItem(JUDGE_MODEL_LS_KEY, id); } catch (e) { /* приватный режим — не страшно */ }
  };

  useEffect(() => {
    if (jumpRef.current) return;      // фильтры снял сам переход — зону не рушим
    setPage(1); setZone(null);
  }, [filter, query, scope, riskFilter, originFilter, project && project.id, store.segmentFilter]);
  useEffect(() => { setCheckedSegs(new Set()); }, [project && project.id, store.segmentFilter]);
  useEffect(() => { if (jumpRef.current) return; setSelId(null); }, [page]);
  // Гасим флажок перехода: без списка зависимостей — то есть после КАЖДОГО
  // коммита и обязательно после сбросов выше (порядок объявления = порядок
  // выполнения). Иначе переход, не изменивший ни фильтров, ни страницы,
  // оставил бы флажок взведённым и съел бы следующий честный сброс.
  useEffect(() => { jumpRef.current = false; });

  // Сегмент-центр стоит посередине окна, то есть ниже первого экрана таблицы:
  // без прокрутки «перешли» выглядит как «ничего не произошло».
  useEffect(() => {
    if (zone == null) return;
    try {
      const el = document.querySelector('tr[data-seg="' + zone + '"]');
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch (e) { /* вне браузера (тест рендера) — не страшно */ }
  }, [zone]);

  useEffect(() => {
    if (project && !project.segments.find(s => s.id === selId)) setSelId(project.segments[0] && project.segments[0].id);
  }, [project && project.id]);

  // Navigate to a specific segment (from drill-down)
  useEffect(() => {
    if (!store.gotoSegId || !project) return;
    const id = store.gotoSegId;
    store.clearGotoSeg();
    // Find index in unfiltered project segments (filter was cleared before goToSegment)
    const allSegs = project.segments;
    const idx = allSegs.findIndex(s => s.id === id);
    if (idx < 0) return;
    // Reset filters so segment is visible
    setFilter("all");
    setQuery("");
    setRiskFilter("all");
    // Page is idx / PAGE_SIZE + 1 (in unfiltered list)
    setPage(Math.floor(idx / PAGE_SIZE) + 1);
    setSelId(id);
  }, [store.gotoSegId]);

  // Приоритет выборки: чекбоксы > активный фильтр анализа > весь проект.
  // Считается ДО раннего return: от выборки зависит разбор прогона ниже,
  // а хук обязан вызываться на каждом рендере и в одном и том же порядке.
  const hasExplicitCheck = checkedSegs.size > 0;
  const currentIdSet = hasExplicitCheck ? checkedSegs : (store.segmentFilter || window._mcat_sf || null);

  /* ── Разбор составного прогона: считает сервер ──────────────────────────
     Раньше состав и смету считал этот файл, а работу отбирал сервер — своими
     предикатами. Разойтись они были обязаны: список сегментов у прогона ОДИН,
     объединение целей всех шагов, и каждый шаг брал оттуда всё, что проходило
     ЕГО серверную проверку, а не то, что человек отметил галочками в карточке
     соседнего шага. Снятая галочка уменьшала смету, но не работу.

     Теперь оба ответа даёт один код на сервере, а карточка показывает его
     целиком — вместе с причинами, по которым сегменты пропущены. Человеку
     больше не нужно угадывать, какую галочку снять, чтобы не переплатить
     и не понизить качество: это решение принято до него и объяснено. */
  const [runPlan, setRunPlan] = useState(null);
  const [planBusy, setPlanBusy] = useState(false);
  // Ключ строкой, а не списком зависимостей: Set и массивы сравниваются по
  // ссылке, и эффект уходил бы в сеть на каждом рендере таблицы.
  //
  // В ключ входит и отпечаток самих сегментов: список из разбора уходит потом
  // в задачу, и устаревший разбор — это не «неточная смета», а прогон не по
  // тем сегментам. Перевели или проверили строку мимо прогона — отпечаток
  // изменится, разбор пересчитается.
  const planFp = project ? project.segments.reduce((a, s) =>
    a + (s.target || "").length + (s.status || "").length * 7
      + (s.backcheck ? 3 : 0) + (s.termcheck ? 5 : 0) + (s.qa_result ? 11 : 0)
      + (s.repair ? 13 : 0), 0) : 0;
  const scopeFp = currentIdSet
    ? currentIdSet.size + ":" + Array.from(currentIdSet).reduce((a, i) => a + i, 0) : "all";
  const planKey = [
    project && project.id, gptModel, bcModel, tcModel, tcxModel, rpModel, rvModel, bcJudge,
    fullSteps ? Array.from(fullSteps).sort().join(",") : "*",
    rpGroupPick ? Array.from(rpGroupPick).sort().join(",") : "*",
    rpFixConfirmed ? "rc" : "",
    scopeFp, planFp,
    job ? job.id + ":" + job.status : "",
  ].join("|");
  useEffect(() => {
    if (!project || !window.API) { setRunPlan(null); return; }
    // Пока прогон идёт, разбор не пересчитываем: сегменты меняются каждые
    // несколько секунд, а воркер на сервере ОДИН — разбор дрался бы за него
    // с самим прогоном. Карточка в это время показывает прогресс, а не состав;
    // по окончании прогона статус задачи изменится и разбор пересчитается сам.
    if (job && job.status === "running") return;
    let alive = true;
    setPlanBusy(true);
    const ids = currentIdSet
      ? project.segments.filter(s => currentIdSet.has(s.id)).map(s => s.id) : null;
    /* Отпечаток наших правок сегментов ДО запроса: см. сверку статусов ниже. */
    const editsBefore = window.API.segEdits ? window.API.segEdits() : null;
    window.API.safeCall(() => window.API.runPlan(project.id, {
      steps: fullSteps ? FULL_STEP_KEYS.filter(k => fullSteps.has(k)) : null,
      segment_ids: ids,
      model: gptModel, bc_model: bcModel, tc_model: tcModel, rp_model: rpModel,
      tcx_model: tcxModel, rv_model: rvModel,
      use_judge: bcJudge,
      // Тот же признак, что и у карточки ремонта: отмечены группы уже
      // чинившихся — значит человек просит второй заход.
      retry: !!(rpGroupPick && (rpGroupPick.has("applied") || rpGroupPick.has("rejected"))),
      include_confirmed: rpFixConfirmed,
    })).then(async res => {
      if (!alive) return;
      setPlanBusy(false);
      setRunPlan(res && res.steps ? res : null);
      /* Сегменты могли прибавиться мимо этой вкладки — например, разбором
         картинок с экрана экспорта. Тогда состав прогона (его считает сервер)
         говорит про 41 непереведённый сегмент, а в таблице их нет: выбрать
         их нечем, фильтры их не видят, «Новые» показывает ноль. Сверяем
         дешёвым числом из того же ответа и подтягиваем ОДИН раз. */
      const n = res && res.projectSegments;
      if (!n) return;
      /* А статусы могли РАЗОЙТИСЬ при совпавшем числе, и это отдельная беда.
         Прогон идёт на сервере, вкладка забирает только те сегменты, что
         сервер назвал в job.recent, — а ушедшая в фон вкладка душится
         браузером до одного опроса в минуту и пропускает порции целиком.
         Тогда в одном окне стоят два ответа на один вопрос: строка «Перевод»
         говорит «—» (её считает сервер), а фильтр — «Новые 25» (его считает
         браузер по своей копии). Число сегментов при этом сходится, и старая
         сверка молчала.

         Сверяем ТОЛЬКО когда наших правок нет ни в пути, ни за время запроса:
         правка применяется в браузере сразу, а на сервер уходит отдельно, и
         разбор, посланный между этими событиями, честно вернёт статусы ДО неё.
         Без этой оговорки каждое нажатие «Подтвердить» тянуло бы весь проект
         заново. */
      const editsNow = window.API.segEdits ? window.API.segEdits() : null;
      const quiet = !!editsBefore && !editsNow.busy && !editsNow.failed
        && editsNow.ticket === editsBefore.ticket;
      const srvSig = res.projectStatus ? statusSig(res.projectStatus) : null;
      const mySig = statusSig(statusCountsOf(project.segments));
      /* Результат прогона ещё не забран — этим занят опрос задач, и проект он
         тянет сам. Наша сверка в это время сравнивала бы ДОПРОГОННУЮ копию
         с послепрогонным ответом: те же пять мегабайт второй раз и тост про
         аварию после каждого штатного прогона. */
      const settled = !lastJobId.current;
      const cool = Date.now() - driftAt.current > DRIFT_PAUSE_MS;
      const drift = n !== project.segments.length
        || (settled && quiet && cool && srvSig !== null && srvSig !== mySig);
      if (!drift) return;
      /* Замок — не «идёт запрос», а «за ЭТИМ составом уже ходили». Замок
         по факту запроса откладывал синхронизацию навсегда: эффект,
         наткнувшийся на него, просто выходил, а тот, что нёс замок, к тому
         времени мог оказаться устаревшим (человек тронул настройки) и тоже
         выходил — сегменты не подтягивались, и следующего повода не было. */
      const sig = project.id + ":" + n + ":" + (srvSig || "");
      if (staleFetch.current === sig) return;
      staleFetch.current = sig;
      /* Подставляем и из устаревшего эффекта: проект в замыкании свой,
         а отказ означал бы потерянную синхронизацию. */
      const fresh = await pullProject(project.id);
      if (!fresh) { staleFetch.current = null; return; }
      driftAt.current = Date.now();
      const added = fresh.segments.length - project.segments.length;
      if (added > 0) {
        toast.info(TR("Подтянуты новые сегменты"),
          TR("их завели мимо этой вкладки: ") + added + TR(". Теперь они видны в таблице и фильтрах."));
      } else if (added < 0) {
        /* Сегментов стало МЕНЬШЕ — например, надпись на картинке пометили
           надпечаткой из другого окна. Пропавшие с экрана строки выглядят
           благополучнее, чем есть, поэтому число называется вслух. */
        toast.info(TR("Сегментов стало меньше"),
          TR("их убрали мимо этой вкладки: ") + (-added) + ".");
      } else if (srvSig !== null && srvSig !== mySig) {
        /* Молчать нельзя: статусы в таблице сейчас поменяются сами собой,
           и без объяснения это выглядит как сбой. */
        toast.info(TR("Таблица показывала устаревшее"),
          TR("на сервере статусы сегментов уже другие — подтянули свежие."));
      }
    });
    return () => { alive = false; };
  }, [planKey]);

  if (!project) return React.createElement(NoProject, { store });

  const counts = store.statusCounts(project);
  const activeFilter = store.segmentFilter || window._mcat_sf || null;
  /* Зона — окно вокруг введённого номера. Прочий отбор она отменяет
     намеренно: просили показать соседей ЦЕЛИКОМ, а не тех из них, кто уцелел
     после фильтра. Центр ищется ПО НОМЕРУ, а не запоминается индексом:
     сегменты приезжают с сервера заново после каждого прогона, и запомненный
     индекс однажды указал бы на чужую строку. Номера нет в проекте —
     зоны нет: показываем обычный список, а не пустоту. */
  const zoneIdx = zone == null ? -1 : project.segments.findIndex(s => s.id === zone);
  const inZone = zoneIdx >= 0;
  const zoneFrom = Math.max(0, zoneIdx - ZONE_HALF);
  const zoneTo = Math.min(project.segments.length, zoneIdx + ZONE_HALF + 1);
  const filtered = inZone ? project.segments.slice(zoneFrom, zoneTo) : project.segments.filter(s => {
    if (activeFilter && !activeFilter.has(s.id)) return false;
    if (filter !== "all" && s.status !== filter) return false;
    if (riskFilter !== "all" && s.risk !== riskFilter) return false;
    if (originFilter !== "all"
        && (originFilter === "image") !== !!(s.origin && s.origin.kind === "image")) return false;
    if (query && !segMatches(s, query, scope)) return false;
    return true;
  });
  const selected = project.segments.find(s => s.id === selId);
  // Зона показывается целиком: 21 строку резать на страницы по десять —
  // значит снова спрятать половину соседей, ради которых её и открывали.
  const totalPages = inZone ? 1 : Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const curPage = Math.min(page, totalPages);
  const paged = inZone ? filtered : filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);
  const wordCount = (arr) => arr.reduce((a, s) => a + (s.source.trim() ? s.source.trim().split(/\s+/).length : 0), 0);
  const charCount = (arr) => arr.reduce((a, s) => a + s.source.length, 0);

  /* Переход к сегменту по номеру. Всё, что сузило список, снимается — под
     фильтром соседей не видно, а зона именно про них. Снятое НАЗЫВАЕТСЯ:
     молча убранный фильтр человек потом ищет глазами по всей панели. */
  const goToZone = (raw) => {
    const n = parseInt(String(raw == null ? "" : raw).replace(/[^0-9]/g, ""), 10);
    if (!isFinite(n)) {
      toast.warning(TR("Номер сегмента"), TR("Введите номер сегмента — например 128."));
      return;
    }
    const idx = project.segments.findIndex(s => s.id === n);
    if (idx < 0) {
      const ids = project.segments.map(s => s.id);
      toast.warning(TR("Сегмента #") + n + TR(" в проекте нет"),
        ids.length ? TR("Номера идут от ") + Math.min.apply(null, ids) + TR(" до ") + Math.max.apply(null, ids) + "."
                   : TR("В проекте нет сегментов."));
      return;
    }
    const dropped = [];
    if (filter !== "all") { setFilter("all"); dropped.push(TR("фильтр статуса")); }
    if (riskFilter !== "all") { setRiskFilter("all"); dropped.push(TR("фильтр риска")); }
    if (originFilter !== "all") { setOriginFilter("all"); dropped.push(TR("фильтр источника")); }
    if (query) { setQuery(""); dropped.push(TR("поиск")); }
    if (activeFilter) { window._mcat_sf = null; store.setSegmentFilter(null); dropped.push(TR("выборку из анализа")); }
    jumpRef.current = true;
    setZone(n);
    setSelId(n);
    setJump(String(n));
    if (dropped.length) toast.info(TR("Зона сегмента #") + n,
      TR("Снял ") + dropped.join(", ") + TR(": под ним соседних сегментов не видно."));
  };

  const setSegBusy = (id, kind) => setBusy(b => ({ ...b, [id]: kind }));
  const clearBusy = (id) => setBusy(b => { const n = { ...b }; delete n[id]; return n; });

  // Движок один — выбранная модель. Параметра engine больше нет: он обещал
  // выбор, которого не существует.
  const doTranslate = async (seg, force = false) => {
    if (busy[seg.id]) return;
    setSegBusy(seg.id, "translate");
    let result = null;
    if (window.API) {
      result = await window.API.safeCall(() => window.API.translate(project.id, seg.id, force, gptModel));
    }
    if (result && result.segment) {
      store.updateSegment(project.id, seg.id, {
        target: result.segment.target,
        status: result.segment.status,
        route: result.segment.route,
      });
      const label = gptModelInfo ? gptModelInfo.label : TR("модель");
      const src = result.source === "TM" ? TR(" (из TM)") : result.usedRealApi ? "" : TR(" (демо)");
      toast.success(TR("Сегмент переведён"), label + TR(" · сегмент #") + seg.id + src);
    } else {
      // НЕ подставляем демо-заглушку в перевод: сегмент остаётся как был,
      // пользователь видит честную ошибку и может повторить попытку.
      toast.error(TR("Перевод не выполнен"), TR("Сегмент #") + seg.id + TR(" не изменён. Сервер недоступен или движки перевода вернули ошибку — попробуйте ещё раз."));
    }
    clearBusy(seg.id);
  };

  const doQA = async (seg) => {
    if (busy[seg.id]) return;
    setSegBusy(seg.id, "qa");
    let result = null;
    if (window.API) {
      result = await window.API.safeCall(() => window.API.qa(project.id, seg.id));
    }
    if (result && result.segment) {
      store.updateSegment(project.id, seg.id, { status: result.segment.status, qa: result.segment.qa });
      const n = (result.issues || []).length;
      if (n === 0) toast.info(TR("Проверка QA завершена"), TR("Сегмент #") + seg.id + TR(" — замечаний не найдено."));
      else toast.warning("QA: " + n + TR(" замечан."), TR("Сегмент #") + seg.id);
    } else {
      // Честная ошибка вместо ложного "замечаний не найдено" при недоступном сервере
      toast.error(TR("QA не выполнен"), TR("Сегмент #") + seg.id + TR(": сервер недоступен, статус не изменён."));
    }
    clearBusy(seg.id);
  };

  const doChecks = async (seg) => {
    if (busy[seg.id]) return;
    if (!seg.target) {
      toast.warning(TR("Проверки"), TR("Сначала переведите сегмент #") + seg.id + ".");
      return;
    }
    setSegBusy(seg.id, "medical_qa");
    let result = null;
    if (window.API) {
      result = await window.API.safeCall(() => window.API.runChecks(project.id, seg.id));
    }
    if (result && result.segment) {
      store.updateSegment(project.id, seg.id, {
        status: result.segment.status,
        qa: result.segment.qa || [],
        qa_result: result.segment.qa_result,
        qa_issues: result.segment.qa_issues || [],
        term_candidates: result.segment.term_candidates || [],
        risk_score: result.segment.risk_score,
        risk_color: result.segment.risk_color,
        risk: result.segment.risk,
        backtranslated_ru: result.segment.backtranslated_ru,
        engine_qa: result.segment.engine_qa,
      });
      const qa = result.qa_result || result.segment.qa_result || {};
      const color = qa.risk_color || result.segment.risk_color || "green";
      const score = qa.risk_score != null ? qa.risk_score : result.segment.risk_score;
      const n = (result.issues || result.segment.qa_issues || []).length;
      const title = color === "red" ? TR("Проверки: нужен review") : color === "yellow" ? TR("Проверки: есть правки") : TR("Проверки: зелёный");
      const msg = TR("Сегмент #") + seg.id + " · risk " + color.toUpperCase() + " · score " + (score == null ? 0 : score) + " · issues: " + n;
      (color === "red" ? toast.warning : color === "yellow" ? toast.warning : toast.success)(title, msg);
    } else {
      toast.error(TR("Проверки"), result && result.error ? result.error : TR("Не удалось выполнить проверку."));
    }
    clearBusy(seg.id);
  };

  const doConfirm = async (seg, draftTarget) => {
    // Если передан отредактированный черновик — сначала сохранить его на сервере
    if (draftTarget !== undefined && draftTarget !== seg.target) {
      if (window.API) await window.API.safeCall(() => window.API.update(project.id, seg.id, { target: draftTarget }));
      store.updateSegment(project.id, seg.id, { target: draftTarget });
    }
    const res = window.API ? await window.API.safeCall(() => window.API.confirm(project.id, seg.id)) : null;
    store.updateSegment(project.id, seg.id, { status: "confirmed" });
    // Что именно система выучила — говорим вслух: молчаливое обучение в
    // рабочем инструменте пугает сильнее, чем отсутствие обучения.
    const learned = [];
    if (res && res.tm === "updated") learned.push(TR("память переводов обновлена (прежний вариант заменён)"));
    else if (res && res.tm === "added") learned.push(TR("пара добавлена в память переводов"));
    const cands = (res && res.termCandidates) || [];
    if (cands.length) learned.push(cands.length + TR(" терминов ждут решения в «Глоссарий → Кандидаты»"));
    /* Исправленные внутри сегмента термины. Пары и споры называются
       поимённо — молчаливое обучение в медицинском инструменте пугает
       сильнее его отсутствия, а молча съеденное несогласие запрещено.
       Причина пропуска приходит КОДОМ (закон корзин CLEAN_*): подстрока
       русской фразы сломалась бы от правки формулировки на сервере. */
    const eh = res && res.editHarvest;
    if (eh && (eh.pairs || []).length)
      learned.push(TR("исправления выучены: ")
        + eh.pairs.map(p => "«" + p.src + " → " + p.tgt + "»").join(", "));
    if (eh && (eh.disputed || []).length)
      learned.push(TR("правка расходится с приказом глоссария: ")
        + eh.disputed.map(p => "«" + p.src + " → " + p.tgt + "»" + TR(" (в глоссарии «") + p.gloss + "»)").join("; ")
        + TR(" — решается правкой самой записи"));
    if (eh && eh.skipped)
      learned.push(eh.skipped === "limit" ? TR("исправленные термины не разобраны: исчерпан лимит расходов")
        : eh.skipped === "no_key" ? TR("исправленные термины не разобраны: нет ключа OpenAI")
        : TR("исправленные термины не разобраны: модель не ответила"));
    toast.success(TR("Подтверждено"), TR("Сегмент #") + seg.id + (learned.length ? ". " + learned.join("; ") + "." : "."));
    const prop = res && res.propagate;
    if (prop && (prop.pending.length || prop.confirmed.length)) setPropagateAsk({ seg, prop });
    refreshAfterHand();
  };

  // Распространение подтверждённого перевода на сегменты с тем же исходником.
  // Только по явному согласию: подтверждённые чужой рукой сегменты по умолчанию
  // не трогаем — так же ведут себя Phrase и Trados.
  const doPropagate = async (includeConfirmed) => {
    if (!propagateAsk) return;
    const { seg } = propagateAsk;
    const res = window.API ? await window.API.safeCall(() => window.API.propagate(project.id, seg.id, null, includeConfirmed)) : null;
    setPropagateAsk(null);
    if (!res || !res.ok) { toast.error(TR("Не удалось разослать перевод"), TR("Сервер не ответил.")); return; }
    (res.changed || []).forEach(id => store.updateSegment(project.id, id, {
      target: seg.target, status: "translated", provider: "tm", route: "EXACT_TM" }));
    toast.success(TR("Перевод разослан"), res.changed.length + TR(" сегментов обновлено")
      + (res.skippedConfirmed && res.skippedConfirmed.length
          ? TR("; подтверждённых пропущено: ") + res.skippedConfirmed.length : "") + ".");
  };

  const doRevert = async (seg) => {
    if (seg.status === "confirmed") { setRevertTarget(seg); return; }
    if (seg.status === "failed") {
      if (window.API) await window.API.safeCall(() => window.API.revert(project.id, seg.id));
      store.updateSegment(project.id, seg.id, { status: "new", target: "" });
      toast.info(TR("Статус сброшен"), TR("Сегмент #") + seg.id + TR(" возвращён в «Новый»."));
    }
  };

  const confirmRevert = async () => {
    const seg = revertTarget; setRevertTarget(null);
    if (window.API) await window.API.safeCall(() => window.API.revert(project.id, seg.id));
    store.updateSegment(project.id, seg.id, { status: "translated" });
    toast.warning(TR("Подтверждение снято"), TR("Сегмент #") + seg.id + TR(" возвращён в «Переведён»."));
    refreshAfterHand();
  };

  // Ключ группировки «чем переведено». У сегментов, переведённых до появления поля
  // provider, движок известен лишь приблизительно — такие группы идут отдельно (с «≈»),
  // чтобы неточные данные не смешивались с точными.
  const providerKey = (seg) => {
    const p = providerOf(seg);
    return p ? (p.exact ? p.id : "~" + p.id) : "none";
  };

  // Подтверждённые группируем отдельным ключом от того же движка, а не вместе:
  // это другая по цене галочка — требует rtFixConfirmed и снимает отметку
  // «подтвердил человек», поэтому не должна прятаться внутри обычной группы
  // движка и не отмечается по умолчанию вместе с ней.
  const rtGroupKey = (s) => providerKey(s) + (s.status === "confirmed" ? ":confirmed" : "");

  // Сколько сегментов выборки переведено каким движком — для выбора галочками.
  // Как у back-check/термины/ремонта: нет явной выборки — считаем по всему
  // проекту, а не молчим. Раньше без currentIdSet список был всегда пуст,
  // и «Переводить заново» выглядело сломанным, пока не выбрать все строки.
  const providerGroups = (() => {
    if (!retranslate) return [];
    const by = new Map();
    project.segments.forEach(s => {
      if (currentIdSet && !currentIdSet.has(s.id)) return;
      const confirmed = s.status === "confirmed";
      if (confirmed && !rtFixConfirmed) return;
      const p = providerOf(s);
      const key = rtGroupKey(s);
      const label = (p ? ((p.exact ? "" : "≈ ") + providerLabel(p, gptModels)) : TR("ещё не переведён"))
        + (confirmed ? TR(" — подтверждён человеком") : "");
      const g = by.get(key) || { key, label, count: 0, exact: !!(p && p.exact), confirmed };
      g.count++;
      by.set(key, g);
    });
    return Array.from(by.values()).sort((a, b) => b.count - a.count);
  })();

  // По умолчанию отмечено всё, кроме уже переведённого выбранной моделью и кроме
  // подтверждённого человеком: последнее требует отдельной, осознанной галочки.
  const pickedProviders = providerPick
    || new Set(providerGroups.filter(g => g.key !== gptModel && !g.confirmed).map(g => g.key));

  const toggleProvider = (key) => setProviderPick(prev => {
    const next = new Set(prev || pickedProviders);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  // Ключ группировки «чем уже проверено». stale приходит с бэкенда: перевод
  // изменился после проверки, значит старая оценка уже не про этот текст.
  // Судья вне своей зоны не вызывается, поэтому там его отсутствие — не пробел.
  const bcGroupKey = (s) => {
    const bc = s.backcheck;
    if (!bc || bc.score == null) return "none";
    if (bc.stale) return "stale";
    // Обратный перевод делала модель-автор текста — по серверному правилу
    // (_backcheck_cached) это не проверка: она возвращает свой замысел.
    // Общий прогон возьмёт такой сегмент заново, поэтому группа отмечена
    // по умолчанию — иначе solo-состав разошёлся бы с общим.
    if (bc.model && s.provider && bc.model === s.provider) return "self";
    // needs_judge считает сервер (_segment_for_client): зона вызова судьи
    // зависит от длины оригинала в содержательных словах, а это русская
    // морфология из medical_qa. Повтори мы её здесь — состав под кнопкой
    // «запустить только этот шаг» разошёлся бы с серверным на коротких
    // сегментах, то есть ровно на тех, ради которых зону и открыли.
    if (bcJudge && bc.needs_judge) return "nojudge";
    return bc.model || "unknown";
  };

  const bcGroupLabel = (key) =>
    key === "none" ? TR("ещё не проверялся")
      : key === "stale" ? TR("перевод изменился после проверки")
      : key === "self" ? TR("проверял тот, кто переводил — это не проверка")
      : key === "nojudge" ? TR("проверено без судьи")
      : key === "unknown" ? TR("проверено (модель неизвестна)")
      : TR("проверено: ") + (providerLabel({ id: key, exact: true }, gptModels) || key);

  // Сколько сегментов выборки в каком состоянии проверки — для выбора галочками.
  // Непроверенное и устаревшее идут первыми: ради них back-check и запускают.
  const bcGroups = (() => {
    const order = { none: 0, stale: 1, self: 2, nojudge: 3 };
    const rank = (k) => (order[k] === undefined ? 4 : order[k]);
    const by = new Map();
    project.segments.forEach(s => {
      if (!bcCandidate(s, currentIdSet)) return;
      const key = bcGroupKey(s);
      const g = by.get(key) || { key, label: bcGroupLabel(key), count: 0 };
      g.count++;
      by.set(key, g);
    });
    return Array.from(by.values()).sort((a, b) => rank(a.key) - rank(b.key) || b.count - a.count);
  })();

  // По умолчанию отмечено всё, кроме уже проверенного выбранной моделью с тем же
  // переводом: платить второй раз за тот же результат незачем, но галочку можно вернуть.
  // У back-check ранга нет и быть не может: сильная модель там ХУЖЕ — чинит
  // кривой английский на лету и прячет искомую ошибку. Поэтому свежая проверка
  // любой моделью считается сделанной, и по умолчанию отмечено только то, что
  // не проверено, устарело или недопроверено без судьи, — ровно то, что возьмёт
  // и общий прогон.
  const BC_DEFAULT_GROUPS = ["none", "stale", "self", "nojudge"];
  const pickedBcGroups = bcGroupPick
    || new Set(bcGroups.filter(g => BC_DEFAULT_GROUPS.indexOf(g.key) !== -1).map(g => g.key));

  const toggleBcGroup = (key) => setBcGroupPick(prev => {
    const next = new Set(prev || pickedBcGroups);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  // Один предикат для счётчика на карточке и для самого прогона — чтобы не разошлись.
  // Правило по умолчанию применяем к сегменту, а не к готовому набору групп: перед
  // прогоном данные перечитываются с бэкенда, и там могут появиться новые группы.
  const backcheckable = (s, idSet) => {
    if (!bcCandidate(s, idSet)) return false;
    const key = bcGroupKey(s);
    return bcGroupPick ? bcGroupPick.has(key) : BC_DEFAULT_GROUPS.indexOf(key) !== -1;
  };

  // Один и тот же отбор для счётчика на карточке и для самого пакета — иначе цифры расходятся.
  const pickTargets = (segs) => {
    const idSet = currentIdSet;
    // Галочки и режим «заново» — это явный выбор пользователя, фильтры статуса и риска
    // к нему не применяем. Явной выборки для «заново» больше не требуем (как
    // и у back-check/термины/ремонта): без неё берём весь проект, а не молчим.
    // Одним кликом это не перегоняет ничего — разбивка по группам видна ДО
    // запуска, отмечена не «всё», а «всё кроме выбранной сейчас модели», и перед
    // самим прогоном всё равно всплывает модалка с подтверждением состава.
    const explicit = hasExplicitCheck || retranslate;
    let targets;
    if (explicit) {
      targets = segs.filter(s => (!idSet || idSet.has(s.id))
        && (s.status !== "confirmed" || (retranslate && rtFixConfirmed)));
      // В режиме «заново» берём только отмеченные группы «чем переведено»
      if (retranslate) targets = targets.filter(s => pickedProviders.has(rtGroupKey(s)));
    } else {
      // Раньше здесь сегменты делились по risk между Google и моделью, и запуск
      // «не той» кнопки молча оставлял половину проекта непереведённой.
      // Предикат зеркалит серверный _needs_translation: failed с ПУСТЫМ
      // переводом — это «не переведён» (ошибка перевода сегмент не тронула),
      // и без него кнопка слала бы force=false со списком БЕЗ таких
      // сегментов — сервер бы их взял, а браузер не дал.
      targets = segs.filter(s => (s.status === "new"
          || (s.status === "failed" && !(s.target || "").trim()))
        && (!idSet || idSet.has(s.id)));
    }
    return { targets, explicit, selectionSize: idSet ? idSet.size : 0 };
  };

  // Собрать список целей пакета по свежим данным с бэкенда.
  const collectBatchTargets = async () => {
    let currentSegs = project.segments;
    if (window.API) {
      const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
      if (fresh && fresh.segments) {
        store.replaceProjectSegments(project.id, fresh.segments); // только локальный state
        currentSegs = fresh.segments;
      }
    }
    const { targets, explicit } = pickTargets(currentSegs);
    return { targets, hasExplicitCheck: explicit };
  };

  // Клик по кнопке пакета: сначала смета — перевод платный.
  const askRunBatch = async () => {
    if (batchRun) return;  // не запускать второй пакет поверх незавершённого
    // explicitSel, а не hasExplicitCheck: не путать с одноимённой константой выше
    const { targets, hasExplicitCheck: explicitSel } = await collectBatchTargets();
    if (!targets.length) { toast.warning(TR("Нет подходящих сегментов"), TR("Все сегменты уже переведены или не подходят под фильтр.")); return; }
    // Смету показываем всегда: перевод платный, и запускать его без цифры нельзя.
    setBatchPlan({ targets, hasExplicitCheck: explicitSel });
  };

  const runBatch = (targets, hasExplicitCheck) => {
    setBatchPlan(null);
    setCheckedSegs(new Set());
    startJob("translate", targets,
      // Без этого флага бэкенд сам молча пропустит подтверждённые из targets
      // (см. batch_translate: force+segment_ids не значит include_confirmed) —
      // тогда счётчик «переведено: 0» на явно отмеченных сегментах выглядел бы
      // как сбой, а не как защита.
      { force: !!hasExplicitCheck, model: gptModel, include_confirmed: retranslate && rtFixConfirmed },
      TR("Все подходящие сегменты уже переведены."),
      estimateRun("translate", targets, gptModelInfo));
  };

  // ── Прогоны ─────────────────────────────────────────────────────
  // Порции крутит сервер (см. фоновые прогоны в main.py). Браузер ставит задачу
  // и опрашивает статус: закрытая вкладка больше не обрывает работу, а вернувшись
  // на страницу, пользователь видит прогресс с того места, где тот сейчас есть.
  // Возвращает поставленную задачу (или null): по её id составной прогон
  // запоминает состав шагов — без него полосе прогресса неоткуда взять остаток.
  const startJob = async (kind, targets, params, emptyMsg, est) => {
    if (batchRun) { toast.warning(TR("Прогон уже идёт"), TR("Дождитесь окончания или остановите текущий.")); return null; }
    if (!targets.length) { toast.warning(TR("Нечего запускать"), emptyMsg); return null; }
    if (!window.API) return null;
    // Смету отдаём серверу вместе с задачей. Не ради сервера: он её не читает
    // и работу по ней не меняет. Ради того, чтобы рядом с фактическим расходом
    // лежало то самое число, которое человек видел под кнопкой, — врозь они
    // не сравниваются, а без сравнения смету не на чем поправить.
    const withEst = (est == null || est.cost == null) ? params
      : Object.assign({}, params, { est_cost: est.cost });
    const res = await window.API.safeCall(() => window.API.createJob(project.id, kind, targets.map(s => s.id), withEst));
    if (!res || !res.ok) { toast.error(TR("Не удалось запустить"), TR("Сервер не принял задачу.")); return null; }
    setJob(res.job);
    toast.info(JOB_LABELS[kind] + TR(": запущено"), targets.length + TR(" сегментов. Можно закрыть вкладку — прогон идёт на сервере."));
    return res.job;
  };

  // Итог завершившегося прогона. Отчитываемся по счётчикам, которые вернул сервер:
  // они те же, что раньше собирал браузер, только считать их теперь некому кроме него.
  const reportJobResult = (j) => {
    const c = j.counters || {};
    const name = JOB_LABELS[j.kind] || j.kind;
    // Факт расхода — в каждом итоге, а не только в успешном: прерванный прогон
    // тоже стоил денег, и умолчать об этом значит показать его бесплатным.
    const sp = spendOf(j);
    // Расхождение называем в ту сторону, в какую оно есть, и только когда оно
    // заметное: «в 1.0 раза» — это шум, а не наблюдение. Заниженная смета важнее
    // завышенной, поэтому про неё говорим прямо.
    const ratio = (sp && sp.est != null && sp.cost > 0) ? sp.est / sp.cost : null;
    const ratioMsg = ratio == null ? ""
      : ratio >= 1.15 ? TR(" — смета выше факта в ") + ratio.toFixed(1) + TR(" раза")
      : ratio <= 0.87 ? TR(" — смета НИЖЕ факта в ") + (1 / ratio).toFixed(1) + TR(" раза")
      : "";
    const costMsg = !sp ? ""
      : TR(" · потрачено ") + fmtCost(sp.cost)
        + (sp.est != null ? TR(" при смете ") + fmtCost(sp.est) + ratioMsg : "")
        + (sp.unpriced ? TR(" · вызовов по неизвестной цене: ") + sp.unpriced : "");
    const errMsg = c.errors ? TR(" · ошибок: ") + c.errors : "";
    // Работа, ушедшая в никуда. Ноль — норма и в отчёте не появляется;
    // не ноль человек должен увидеть там же, где итог, а не в журнале сервера.
    const lossMsg = (c.desync ? TR(" · у ") + c.desync + TR(" сегментов текст разошёлся с записью о ремонте") : "")
      + (c.terms_dropped ? TR(" · кандидатов в глоссарий выброшено (очередь полна): ") + c.terms_dropped : "");
    const dupMsg = c.duplicates ? TR(" · повторов зачтено без вызова: ") + c.duplicates : "";
    if (j.status === "error") {
      // У «Одобрить и применить» глоссарий меняется ДО сегментов. Оборвался
      // ремонт — термины уже записаны, и молчать об этом нельзя: человек должен
      // знать, что откатывать, если результат его не устроил.
      const glossNote = (j.kind === "apply_terms" && c.termsApproved)
        ? TR(" Термины (") + c.termsApproved + TR(") уже в глоссарии — пачку можно откатить в «Глоссарии».") : "";
      toast.error(name + TR(": прогон прерван"),
        j.done + TR(" из ") + j.total + TR(" обработано и сохранено. ") + (j.error || "") + glossNote + costMsg);
      return;
    }
    if (j.status === "stopped") {
      toast.warning(name + TR(": остановлено"), j.done + TR(" из ") + j.total + TR(" обработано и сохранено.") + errMsg + costMsg);
      return;
    }
    if (j.kind === "apply_terms") {
      const t = c.termsApproved || 0;
      toast.success(TR("Одобрено и применено"),
        t + TR(" терминов в глоссарий (приказом: ") + (c.termsVerified || 0) + ")"
        + (c.termsRejected ? TR(" · отклонено по смыслу: ") + c.termsRejected : "")
        + TR(" · сегментов исправлено: ") + (c.applied || 0)
        + (c.reverted ? TR(" · откачено: ") + c.reverted : "")
        + (c.skipped_confirmed ? TR(" · подтверждённых не тронуто: ") + c.skipped_confirmed : "")
        + errMsg + lossMsg + costMsg + TR(" · откатить пачку можно в «Глоссарии»"));
      return;
    }
    if (j.kind === "full") {
      // Отчитываемся по шагам: «обработано 2670» ничего не говорит о том,
      // что именно произошло, а прогон стоил денег на каждом шаге.
      const part = [
        c.translate ? TR("переведено ") + c.translate : null,
        c.backcheck ? "back-check " + c.backcheck : null,
        c.termcheck ? TR("термины ") + c.termcheck : null,
        // Сверка терминов: показываем не «сколько сегментов прошло», а что
        // она ОТВЕТИЛА — снятые претензии и найденные неверные передачи.
        // Число пройденных сегментов тут ни о чём не говорит: в большинстве
        // из них сверять нечего.
        (c.settled || c.wrong)
          ? TR("сверка терминов: снято ") + (c.settled || 0) + TR(", неверных ") + (c.wrong || 0)
          : (c.termaudit ? TR("сверка терминов ") + c.termaudit : null),
        c.medical_qa ? TR("Проверки ") + c.medical_qa : null,
        // Ревизия считается ОТДЕЛЬНО от ремонта: это разные работы, и общее
        // число не отвечает на вопрос, чем именно исправлено. Молчать о ней
        // нельзя — она переписывает текст клиента.
        c.revised ? TR("ревизия переписала ") + c.revised : null,
        c.suspect ? TR("оригинал под подозрением: ") + c.suspect : null,
        c.applied ? TR("исправлено ") + c.applied : null,
      ].filter(Boolean).join(" · ") || TR("нового ничего не потребовалось");
      const blockedMsg = c.step_skips ? TR(" · шаги пропускались (нет ключа или модуля)") : "";
      const skipConfMsg = c.skipped_confirmed ? TR(" · подтверждённых не тронуто: ") + c.skipped_confirmed : "";
      toast.success(TR("Перевод и проверка завершены"),
        j.done + TR(" сегментов пройдено · ") + part + dupMsg + skipConfMsg + blockedMsg + errMsg
        + (c.flagged ? TR(" · замечания в ") + c.flagged : "") + lossMsg + costMsg);
      return;
    }
    if (j.kind === "translate") {
      const tmMsg = c.tm_hits ? TR(" · из TM без вызова: ") + c.tm_hits : "";
      // Пропущенные подтверждённые называем вслух: иначе «переведено 0» выглядит
      // как поломка, хотя сервер просто не тронул заверенное человеком.
      const skipMsg = c.skipped_confirmed ? TR(" · пропущено подтверждённых: ") + c.skipped_confirmed : "";
      toast.success(TR("Перевод завершён"), j.done + TR(" сегментов переведено") + tmMsg + dupMsg + skipMsg + errMsg + costMsg);
    } else if (j.kind === "termcheck") {
      const skipMsg = c.skipped_trivial ? TR(" · без вызова модели: ") + c.skipped_trivial : "";
      if (c.flagged) toast.warning(TR("Проверка терминологии завершена"),
        TR("Замечания в ") + c.flagged + TR(" из ") + j.done + TR(" сегментов") + dupMsg + skipMsg + errMsg + costMsg
        + TR(" · предложения замены — в «Глоссарий → Кандидаты»"));
      else toast.success(TR("Проверка терминологии завершена"), j.done + TR(" сегментов без замечаний") + dupMsg + skipMsg + errMsg + costMsg);
    } else if (j.kind === "repair") {
      const revMsg = c.reverted ? TR(" · откачено (не стало лучше): ") + c.reverted : "";
      if (c.applied) toast.success(TR("Ремонт завершён"),
        TR("Исправлено ") + c.applied + TR(" сегментов") + revMsg + errMsg + lossMsg + costMsg + TR(" · статус «Требует проверки», подтвердите вручную"));
      else toast.warning(TR("Ничего не исправлено"), TR("Ни один вариант не улучшил оценку — все откачены.") + errMsg + costMsg);
    } else if (j.kind === "backcheck") {
      toast.success(TR("Back-check завершён"), j.done + TR(" сегментов проверено") + dupMsg + errMsg + costMsg + TR(" · разбивка в Анализе"));
    } else {
      toast.success(name + TR(" завершён"), j.done + TR(" сегментов обработано") + errMsg);
    }
  };

  // Переперевод сегментов, где перевод расходится с одобренными терминами.
  // Это обычный пакетный перевод с force: сегменты уже переведены, и без force
  // отбор по статусу их бы отбросил. include_confirmed передаём отдельно: без
  // него сервер молча выбрасывал подтверждённые, и галочка ничего не делала.
  const runImpactRetranslate = () => {
    if (!impact) return;
    const ids = new Set(impactConfirmed ? impact.segments : impact.pending);
    startJob("translate", project.segments.filter(s => ids.has(s.id)),
      // via помечает, ЧЬЯ это задача: прогон один и тот же («перевод»),
      // но прогресс должен зажечься на той карточке, с которой его запустили.
      { force: true, model: gptModel, include_confirmed: !!impactConfirmed, via: "impact" },
      TR("Все переводы уже соответствуют одобренным терминам."));
  };

  const stopJob = async () => {
    if (!job || !window.API || job.stopping) return;
    setJob(j => (j ? { ...j, stopping: true } : j));   // отклик сразу, не дожидаясь опроса
    const res = await window.API.safeCall(() => window.API.stopJob(job.id));
    if (!res || !res.ok) {
      setJob(j => (j ? { ...j, stopping: false } : j));
      toast.error(TR("Не удалось остановить"), TR("Сервер не ответил — попробуйте ещё раз."));
      return;
    }
    toast.info(TR("Останавливаем"), TR("Текущий сегмент досчитается и сохранится, дальше прогон не пойдёт."));
  };

  const runBackcheckBatch = () => {
    // skip_cached выключен: состав уже отобран галочками «Что проверять»,
    // иначе сервер вырезал бы из порции ровно то, что попросили перепроверить.
    const targets = project.segments.filter(s => backcheckable(s, currentIdSet));
    startJob("backcheck", targets,
      { model: bcModel || null, use_judge: bcJudge, judge_model: judgeModel || null, skip_cached: false },
      bcSkipConfirmed
        ? TR("В выборке нет непроверенных сегментов, кроме подтверждённых, а их вы просили пропускать.")
        : TR("В выборке нет непроверенных сегментов. Отметьте нужные группы в «Что проверять»."),
      estimateRun("backcheck", targets, bcModelInfo, { judge: bcJudge, judgeModel: judgeModelInfo }));
  };

  const runTermcheckBatch = () => {
    const targets = project.segments.filter(s => termcheckable(s, currentIdSet));
    startJob("termcheck", targets,
      { model: tcModel || null, skip_cached: false },
      TR("Всё в выборке уже проверено этой моделью. Отметьте нужные группы в «Что проверять», чтобы прогнать заново."),
      estimateRun("termcheck", targets, tcModelInfo));
  };

  const runReview = () => {
    // Список — из серверного разбора: кого шаг возьмёт, решает `_plan_step`
    // теми же предикатами, что и сам прогон.
    const plan = stepPlan("review");
    const ids = new Set((plan && plan.ids) || []);
    const targets = project.segments.filter(s => ids.has(s.id));
    startJob("review", targets,
      { model: rvModel || null },
      TR("Ревизовать нечего: в выборке нет переведённых сегментов, ")
      + TR("либо все уже ревизованы этим переводом."),
      estimateRun("review", targets, rvModelInfo));
  };

  const runTermAudit = () => {
    // Список берём из серверного разбора, а не считаем сами: приказные термины
    // сегмента считает `_verified_hits`, и повторить его в браузере нечем.
    const plan = stepPlan("termaudit");
    const ids = new Set((plan && plan.ids) || []);
    const targets = project.segments.filter(s => ids.has(s.id));
    startJob("termaudit", targets,
      { model: tcxModel || null },
      TR("Сверять нечего: в выборке нет сегментов с утверждёнными терминами, ")
      + TR("либо все уже сверены этим переводом."),
      estimateRun("termaudit", targets, tcxModelInfo));
  };

  const runRepairBatch = () => {
    const targets = project.segments.filter(s => repairable(s, currentIdSet));
    startJob("repair", targets,
      { model: rpModel || null, bc_model: bcModel || null, tc_model: tcModel || null,
        use_judge: bcJudge, judge_model: judgeModel || null, retry: repairRetry(),
        include_confirmed: rpFixConfirmed },
      rpGroups.length
        ? TR("Все сегменты с находками уже проходили ремонт. Отметьте нужные группы в «Что чинить».")
        : TR("Нет сегментов с проверяемыми находками. Сначала прогоните back-check или проверку терминологии."),
      estimateRun("repair", targets, rpModelInfo, { recheckModel: bcModelInfo }));
  };

  const runChecksBatch = () => {
    const idSet = currentIdSet;
    const targets = project.segments.filter(s =>
      s.target && s.target.trim() &&
      ["translated", "qa", "review", "confirmed"].includes(s.status) &&
      (!idSet || idSet.has(s.id)));
    startJob("medical_qa", targets,
      // Модель обратного перевода — та же, что у back-check. Своей у Medical QA
      // нет: правила детерминированные, вызов нужен только там, где готового
      // обратного перевода не осталось.
      { bc_model: bcModel }, TR("Нет переведённых сегментов для пакетной проверки."),
      // Платит она только за те сегменты, у которых своего обратного перевода
      // нет: остальным его отдал back-check. Тот же фильтр, что и в soloEst.
      estimateRun("medical_qa",
        targets.filter(s => !(s.backcheck && !s.backcheck.stale && s.backcheck.back)), bcModelInfo));
  };

  // Подписи с реальными языками проекта: "Оригинал (RU)" / "Перевод (EN)"
  const scopeOpts = [
    ["all", TR("Везде")],
    ["src", TR("Оригинал (") + project.src + ")"],
    ["tgt", TR("Перевод (") + project.tgt + ")"],
  ];
  const searchPlaceholder = scope === "src" ? TR("Поиск по оригиналу (") + project.src + ")…"
    : scope === "tgt" ? TR("Поиск по переводу (") + project.tgt + ")…"
    : TR("Поиск по оригиналу и переводу…");

  // ── Проверка терминологии: группы «что уже прогонялось» ──────────
  // Ключ разделяет не только «проверено/нет», но и «с замечаниями/без»:
  // после правок обычно нужно перепрогнать именно те, где замечания были.
  const tcCandidate = (s, idSet) => !!(s.target && s.target.trim()) && (!idSet || idSet.has(s.id));

  const tcGroupLabel = (key) => {
    if (key === "none") return TR("ещё не проверялся");
    if (key === "stale") return TR("перевод изменился после проверки");
    if (key === "skip") return TR("нечего проверять (без вызова модели)");
    const [kind, mdl] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
    const name = mdl === "unknown" ? TR("модель неизвестна") : (providerLabel({ id: mdl, exact: true }, gptModels) || mdl);
    return (kind === "hit" ? TR("проверено, есть замечания: ") : TR("проверено, замечаний нет: ")) + name;
  };

  const tcGroups = (() => {
    const order = { none: 0, stale: 1 };
    const rank = (k) => (order[k] !== undefined ? order[k] : k.indexOf("hit:") === 0 ? 2 : k === "skip" ? 4 : 3);
    const by = new Map();
    project.segments.forEach(s => {
      if (!tcCandidate(s, currentIdSet)) return;
      const key = tcGroupKey(s);
      const g = by.get(key) || { key, label: tcGroupLabel(key), count: 0 };
      g.count++;
      by.set(key, g);
    });
    return Array.from(by.values()).sort((a, b) => rank(a.key) - rank(b.key) || b.count - a.count);
  })();

  // По умолчанию отмечено непроверенное и устаревшее. Уже проверенное текущей
  // моделью и пропущенные сегменты сняты: результат будет тот же, а вызов платный.
  const tcDefaultPicked = (key) => tcGroupDefault(key, tcModel, gptModels);
  const pickedTcGroups = tcGroupPick || new Set(tcGroups.filter(g => tcDefaultPicked(g.key)).map(g => g.key));
  const toggleTcGroup = (key) => setTcGroupPick(prev => {
    const next = new Set(prev || pickedTcGroups);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  // Один предикат для счётчика на карточке и для самого прогона — чтобы не разошлись
  const termcheckable = (s, idSet) => {
    if (!tcCandidate(s, idSet)) return false;
    const key = tcGroupKey(s);
    return tcGroupPick ? tcGroupPick.has(key) : tcDefaultPicked(key);
  };

  // ── Ремонт: кандидаты и группы «что уже чинилось» ────────────────
  // Критерий кандидата повторяет серверный _repair_findings: иначе кнопка
  // обещала бы работу, которой сервер не найдёт.
  /* БЕЗ TR(): это не надписи, а КОДЫ ПРИЧИН, которые сравниваются
     с `backcheck.reasons` — русским текстом, пришедшим с сервера. Оберни их
     переводом, и в узбекском интерфейсе `indexOf` перестанет находить
     совпадения: кнопка «Починить» погаснет на сегментах, которые чинить
     МОЖНО, и понять почему будет неоткуда. Тот же закон, что у ключей
     объекта и операндов сравнения (CLAUDE.md, инвариант 17). */
  const REPAIR_REASONS = ["расхождение чисел", "расхождение единиц", "инверсия отрицания",
                          "подмена на противоположное", "обратный перевод про другое", "потерян термин"];
  // Расхождения с глоссарием сервер тоже считает поводом чинить. Берём их из
  // уже загруженного отчёта о соответствии — он и есть тот же расчёт, только
  // посчитанный один раз на проект. pending, а не segments: подтверждённые
  // сегменты автоматика по умолчанию не переписывает.
  // Обычная переменная, а не useMemo: этот код идёт после раннего return по
  // отсутствию проекта, и хук здесь сломал бы порядок хуков компонента.
  // Два набора расхождений с глоссарием: pending — без подтверждённых,
  // segments — со всеми. Какой из них в силе, решает галочка ниже; сервер
  // считает ровно так же (glossary_impact), и разойтись они не должны.
  const impactPendingIds = new Set((impact && impact.pending) || []);
  const impactAllIds = new Set((impact && impact.segments) || []);
  // Есть ли у сегмента находка, по которой ремонту есть что делать.
  const rpFindingHit = (s, glossIds) => {
    if (!(s.target && s.target.trim())) return false;
    const bc = s.backcheck && !s.backcheck.stale ? s.backcheck : null;
    const tc = s.termcheck && !s.termcheck.stale ? s.termcheck : null;
    const bcHit = bc && ((bc.terms_lost || []).length > 0
      || (bc.reasons || []).some(r => REPAIR_REASONS.some(h => r.indexOf(h) !== -1))
      || (bc.judge && ["major", "critical"].indexOf(bc.judge.severity) !== -1));
    const tcHit = tc && (tc.findings || []).some(f => tcActionable.indexOf(f.severity) !== -1);
    return !!(bcHit || tcHit || glossIds.has(s.id));
  };
  const rpCandidate = (s, idSet) => {
    if (idSet && !idSet.has(s.id)) return false;
    // Подтверждённые — только по явной галочке, и ровно по тому же правилу,
    // что на сервере. Без этой строки счётчик и смета считали работу, которую
    // прогон молча пропускал (skipped_confirmed), — числа под кнопкой врали.
    if (s.status === "confirmed" && !rpFixConfirmed) return false;
    return rpFindingHit(s, rpFixConfirmed ? impactAllIds : impactPendingIds);
  };
  // Сколько заверенного человеком ждёт починки — показываем ВСЕГДА, даже при
  // снятой галочке: иначе о запертой работе можно узнать, только случайно
  // включив переключатель.
  const rpConfirmedWaiting = project.segments.filter(s =>
    s.status === "confirmed" && (!currentIdSet || currentIdSet.has(s.id))
    && rpFindingHit(s, impactAllIds)).length;

  // tried приходит с бэкенда: этот же текст уже проходил через ремонт
  const rpGroupLabel = (key) =>
    key === "none" ? TR("ремонт не запускался")
      : key === "changed" ? TR("текст менялся после прошлого ремонта")
      : key === "failed" ? TR("заход не состоялся — сбой перепроверки")
      : key === "rules" ? TR("правило отмены изменилось — прежний вердикт устарел")
      : key === "second" ? TR("чинила другая модель — выбранная зайдёт со вторым мнением")
      : key === "applied" ? TR("уже чинилось, замечания остались")
      : TR("правка была откачена (не стало лучше)");

  const rpGroups = (() => {
    const order = { none: 0, changed: 1, failed: 2, rules: 3, second: 4,
                    applied: 5, rejected: 6 };
    const by = new Map();
    project.segments.forEach(s => {
      if (!rpCandidate(s, currentIdSet)) return;
      const key = rpGroupKey(s, rpModel || null);
      const g = by.get(key) || { key, label: rpGroupLabel(key), count: 0 };
      g.count++;
      by.set(key, g);
    });
    return Array.from(by.values()).sort((a, b) => order[a.key] - order[b.key]);
  })();

  // По умолчанию чиним то, что ещё не чинили. Повторный заход по тому же тексту
  // даст тот же результат, поэтому такие группы сняты — но галочку можно вернуть.
  const rpDefaultPicked = (key) => rpGroupDefault(key);
  const pickedRpGroups = rpGroupPick || new Set(rpGroups.filter(g => rpDefaultPicked(g.key)).map(g => g.key));
  const toggleRpGroup = (key) => setRpGroupPick(prev => {
    const next = new Set(prev || pickedRpGroups);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  const repairable = (s, idSet) => {
    if (!rpCandidate(s, idSet)) return false;
    // Та же модель, что у rpGroups: группировка и отбор — один расчёт.
    const key = rpGroupKey(s, rpModel || null);
    return rpGroupPick ? rpGroupPick.has(key) : rpDefaultPicked(key);
  };

  // Отмечены группы уже чинившихся — серверу нужно разрешение на второй заход
  const repairRetry = () => (pickedRpGroups.has("applied") || pickedRpGroups.has("rejected"));
  /* Сколько сегментов с находками отложено СНЯТЫМИ галочками. Считается по тем
     же rpGroups, что и таблица ниже, — второй расчёт разошёлся бы с ней. */
  const rpWaiting = rpGroups.reduce(
    (a, g) => a + (pickedRpGroups.has(g.key) ? 0 : g.count), 0);

  const pickedFull = fullSteps || new Set(FULL_STEP_KEYS);
  // Состав шагов — ответ сервера, а не расчёт браузера. Пока разбор не пришёл,
  // показываем пусто и не даём запустить: обещать работу, состав которой ещё
  // не известен, значит снова разойтись со сметой.
  const segById = new Map(project.segments.map(s => [s.id, s]));
  const planByStep = {};
  ((runPlan && runPlan.steps) || []).forEach(p => { planByStep[p.step] = p; });
  const fullStepTargets = {};
  FULL_STEP_KEYS.forEach(k => {
    const p = planByStep[k];
    fullStepTargets[k] = p ? p.ids.map(i => segById.get(i)).filter(Boolean) : [];
  });
  // Серверу отдаём ровно то объединение, которое он же и посчитал.
  const fullRunIds = runPlan ? runPlan.ids.map(i => segById.get(i)).filter(Boolean) : [];
  /* Модель шага, которой пойдёт ПРОГОН. Пустой выбор в браузере означает
     «возьми свою по умолчанию», и её id знает только сервер — он называет его
     в разборе (plan.model), тем же кодом, которым потом и работает. Без этой
     подстановки шаг с невыбранной моделью стоил «не знаю», а один такой шаг
     обнуляет ВСЮ смету главной кнопки: под кнопкой, делающей тысячи платных
     вызовов, оставался прочерк без единой причины. Так и вышло со сверкой
     терминов, чей выбор каталог не заполнял. Выбор человека сильнее: он
     и уходит в задачу. */
  const stepModel = (key, picked) => picked
    || (planByStep[key] && gptModels.find(m => m.id === planByStep[key].model)) || null;
  const toggleFullStep = (key) => setFullSteps(prev => {
    const next = new Set(prev || pickedFull);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  // Смета — сумма смет по шагам, каждая своей моделью. Показываем до запуска:
  // составной прогон дороже одиночного, и узнавать об этом постфактум нельзя.
  const fullEst = (() => {
    // Сегменты, которые прогон переведёт, к своим проверкам уже будут
    // переведены — сервер их в списки проверок включил сам, поэтому добавлять
    // их здесь второй раз не нужно: получилось бы удвоение.
    const parts = [
      pickedFull.has("translate") && estimateRun("translate", fullStepTargets.translate,
        stepModel("translate", gptModelInfo)),
      pickedFull.has("backcheck") && estimateRun("backcheck", fullStepTargets.backcheck,
        stepModel("backcheck", bcModelInfo), { judge: bcJudge, judgeModel: judgeModelInfo }),
      pickedFull.has("termcheck") && estimateRun("termcheck", fullStepTargets.termcheck,
        stepModel("termcheck", tcModelInfo)),
      // Ревизия. Шаг с работой и без цены обнуляет ВСЮ смету намеренно,
      // поэтому забыть его здесь — значит поставить прочерк под кнопкой,
      // которая сделает тысячи платных вызовов.
      pickedFull.has("review") && estimateRun("review", fullStepTargets.review || [],
        stepModel("review", rvModelInfo)),
      // Сверка терминов моделью. Без неё смета главной кнопки была занижена
      // на четверть: шаг по умолчанию включён, работу делает, а цены не имел —
      // ровно то молчание, от которого этот блок и заведён. Заодно это число
      // уходит в историю расхода как est_cost, по которому калибруется смета.
      pickedFull.has("termaudit") && estimateRun("termaudit", fullStepTargets.termaudit,
        stepModel("termaudit", tcxModelInfo)),
      // Medical QA платит только там, где готового обратного перевода нет:
      // остальным его отдаёт back-check. И платит она по цене back-check —
      // модель обратного перевода у них теперь общая.
      pickedFull.has("medical_qa") && estimateRun("medical_qa",
        fullStepTargets.medical_qa.filter(s => !(s.backcheck && !s.backcheck.stale && s.backcheck.back)),
        stepModel("medical_qa", bcModelInfo)),
      // Судья считается ТЕМИ ЖЕ опциями, что в строке шага. Ремонт зовёт его
      // симметрично прежней оценке, то есть и при выключенном тумблере: без
      // этой строки итог был меньше суммы строк над ним, а его число уходит
      // в est_cost и калибрует поправку estRatio по всей системе.
      pickedFull.has("repair") && estimateRun("repair", fullStepTargets.repair,
        stepModel("repair", rpModelInfo), { recheckModel: stepModel("backcheck", bcModelInfo),
          judge: bcJudge, judgeModel: judgeModelInfo || stepModel("backcheck", bcModelInfo) }),
    ].filter(Boolean);
    // Шаг, у которого есть работа, но нет цены (модель не выбрана или каталог
    // не загрузился), обнуляет всю смету: «$0.00» под кнопкой, которая сделает
    // тысячи платных вызовов, — худший вид молчания.
    const unpriced = parts.some(p => p.count > 0 && p.cost == null);
    return {
      cost: unpriced ? null : parts.reduce((a, p) => a + (p.cost || 0), 0),
      seconds: parts.reduce((a, p) => a + p.seconds, 0),
      count: fullRunIds.length,
    };
  })();

  /* ── Строки таблицы составного прогона ───────────────────────────────
     У каждой строки два состава и две цены, и путать их нельзя:
       plan* — что сделает ОБЩИЙ прогон. Считает сервер, галочки групп на это
               не влияют: он сам не берёт готовое и не даёт слабой модели
               переписать вердикт сильной.
       solo* — что сделает кнопка «Запустить только этот шаг». Считается
               здесь, ПО ГАЛОЧКАМ, и идёт со skip_cached=false — это способ
               намеренно перепроверить то, что общий прогон считает сделанным.
     По умолчанию оба состава совпадают: галочки групп выставлены по тому же
     правилу рангов, что и на сервере. Разойтись они могут только если человек
     сам отметил лишнюю группу — и тогда это его решение, а не сюрприз. */
  const groupTable = (title, groups, pickedGroups, onToggleGroup, empty) =>
    React.createElement("div", { key: "g" },
      React.createElement("div", { style: { fontSize: 12, fontWeight: 600, marginBottom: 5 } }, title),
      groups.length === 0
        ? React.createElement("div", { className: "dim", style: { fontSize: 11.5 } }, empty)
        : groups.map(g => React.createElement("div", {
            key: g.key, className: "row between", style: { padding: "2px 0", fontSize: 12.5 } },
            React.createElement(Checkbox, { checked: pickedGroups.has(g.key),
              onChange: () => onToggleGroup(g.key) }, g.label),
            React.createElement("b", { style: { fontSize: 12.5, fontVariantNumeric: "tabular-nums" } }, g.count))));

  const transSolo = pickTargets(project.segments);
  const confirmedInScope = project.segments.filter(s => s.status === "confirmed"
    && (s.target || "").trim() && (!currentIdSet || currentIdSet.has(s.id))).length;
  const qaSolo = project.segments.filter(s => s.target && s.target.trim()
    && ["translated", "qa", "review", "confirmed"].includes(s.status)
    && (!currentIdSet || currentIdSet.has(s.id)));
  const stepPlan = (k) => planByStep[k] || null;
  const planEstOf = (k, model, opts) => estimateRun(k, fullStepTargets[k] || [], model, opts);

  const fullRunRows = [
    {
      key: "translate", label: FULL_STEP_LABELS.translate, hint: TR("только те, что ещё не переведены"),
      modelId: gptModel, onModel: pickGptModel, plan: stepPlan("translate"),
      planEst: planEstOf("translate", stepModel("translate", gptModelInfo)),
      soloEst: estimateRun("translate", transSolo.targets, stepModel("translate", gptModelInfo)),
      onSolo: askRunBatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "translate"
        && !(job && job.params && job.params.via === "impact") ? batchRun : null,
      soloNote: !retranslate
        ? TR("Берёт только сегменты со статусом «Новый». Включите «Переводить заново», чтобы перегнать уже переведённое.")
        : rtFixConfirmed
          ? TR("Перегоняет выбранные заново, включая подтверждённые человеком — с них снимется отметка «подтвердил человек». Точное совпадение с памятью переводов не подставляется, прежний перевод перезаписывается.")
          : TR("Перегоняет выбранные заново. Подтверждённые не трогаются, точное совпадение с памятью переводов не подставляется, прежний перевод перезаписывается."),
      options: React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
        React.createElement("div", { className: "row between", style: { gap: 12, flexWrap: "wrap" } },
          React.createElement("div", null,
            React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600 } }, TR("Переводить заново уже переведённые")),
            React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
              (currentIdSet ? TR("Применится к текущей выборке")
                            : TR("Применится ко всему проекту — сузить можно галочками в таблице или фильтром из Анализа")))),
          React.createElement(Switch, { on: retranslate, label: TR("Переводить заново"),
            onClick: () => setRetranslate(v => !v) })),
        // Подтверждённые — отдельная, более дорогая по последствиям галочка:
        // без неё их вообще не видно в разбивке ниже, и это не баг, а тот же
        // предохранитель, что и у ремонта («чинить подтверждённые»).
        retranslate && React.createElement("div", { className: "row between", style: { gap: 12 } },
          React.createElement("div", { style: { fontSize: 12.5 } }, TR("Переводить и подтверждённые человеком"),
            React.createElement("span", { className: "dim", style: { fontSize: 11.5, display: "block" } },
              confirmedInScope + TR(" в выборке; со снятых будет снята отметка «подтвердил человек»"))),
          React.createElement(Switch, { on: rtFixConfirmed, label: TR("Переводить подтверждённые"),
            onClick: () => setRtFixConfirmed(v => !v) })),
        retranslate && groupTable(TR("Сейчас переведено через — отметьте, что перевести заново:"),
          providerGroups.map(g => ({ key: g.key, count: g.count,
            label: g.label + (g.exact ? "" : TR(" (определено по маршруту)")) })),
          pickedProviders, toggleProvider,
          rtFixConfirmed ? TR("В выборке нет ни одного переведённого сегмента.")
                         : TR("В выборке нет сегментов для повторного перевода (все подтверждены)."))),
    },
    {
      key: "review", label: FULL_STEP_LABELS.review,
      hint: TR("читает пару целиком и сразу правит текст — единственный шаг, который не спорит с баллом"),
      modelId: rvModel, onModel: pickRvModel, plan: stepPlan("review"),
      planEst: planEstOf("review", stepModel("review", rvModelInfo)),
      soloEst: planEstOf("review", stepModel("review", rvModelInfo)),
      onSolo: runReview, onStop: stopJob,
      running: batchRun && batchRun.engine === "review" ? batchRun : null,
      soloNote: TR("Один вызов на сегмент. Правка ставится, только если оценка ")
        + TR("не выше порога И кандидат прошёл бесплатные сверки: числа, единицы, ")
        + TR("отрицание, сторона, утверждённые термины, регистр, письмо, повторы. ")
        + TR("Балл back-check в этом решении НЕ участвует — он вознаграждает кальку. ")
        + TR("Заверенное человеком не переписывается, откат есть у каждой пачки."),
    },
    {
      key: "backcheck", label: FULL_STEP_LABELS.backcheck, hint: TR("обратный перевод другой моделью"),
      modelId: bcModel, onModel: pickBcModel, plan: stepPlan("backcheck"),
      planEst: planEstOf("backcheck", stepModel("backcheck", bcModelInfo),
        { judge: bcJudge, judgeModel: judgeModelInfo }),
      soloEst: estimateRun("backcheck", project.segments.filter(s => backcheckable(s, currentIdSet)),
        stepModel("backcheck", bcModelInfo), { judge: bcJudge, judgeModel: judgeModelInfo }),
      onSolo: runBackcheckBatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "backcheck" ? batchRun : null,
      options: React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
        React.createElement("div", { className: "row between", style: { gap: 12, flexWrap: "wrap" } },
          React.createElement("div", null,
            React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, display: "flex", alignItems: "center" } },
              TR("Судья для средней зоны"),
              React.createElement(InfoTip, { title: TR("Когда зовут судью"),
                body: TR("Балл ") + judgeZone[0] + "–" + judgeZone[1] + TR("% — зона, где лексика уже не отвечает, а смысл ещё под вопросом. Наверху и внизу шкалы решение принято детерминированными проверками, и платить за подтверждение очевидного незачем. При жёсткой находке (числа, единицы, отрицание) судья тоже не вызывается: отменить её он не может.")
                  + TR("\n\nИсключение — короткий оригинал (меньше ") + bcMinStems + TR(" содержательных слов). Мера, по которой считается балл, на таком отрезке даёт только 0 или 100%, и любой синоним в обратном переводе роняет его в ноль при верном переводе: «Фтизиатрия → Phthisiology → Фтизиология». Ноль здесь значит «нечем измерить», поэтому низ зоны для таких сегментов открыт до нуля. Обратный перевод при этом берётся готовый — платим только за судью.") })),
            React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
              TR("балл ") + judgeZone[0] + "–" + judgeZone[1] + TR("%, а на оригиналах короче ") + bcMinStems + TR(" слов — от 0"))),
          React.createElement("div", { className: "row", style: { gap: 8 } },
            bcJudge && React.createElement(Select, { value: judgeModel || "", disabled: !!job,
              onChange: (e) => pickJudgeModel(e.target.value), style: { fontSize: 12.5, maxWidth: 170 } },
              gptModels.map(m => React.createElement("option", { key: m.id, value: m.id }, m.label))),
            React.createElement(Switch, { on: bcJudge, label: TR("Судья"), onClick: () => setBcJudge(v => !v) }))),
        React.createElement("div", { className: "row between", style: { gap: 12 } },
          React.createElement("div", { style: { fontSize: 12.5 } }, TR("Пропускать подтверждённые человеком"),
            React.createElement("span", { className: "dim", style: { fontSize: 11.5, display: "block" } },
              confirmedInScope + TR(" в выборке"))),
          React.createElement(Switch, { on: bcSkipConfirmed, label: TR("Пропускать подтверждённые"),
            onClick: toggleBcSkipConfirmed })),
        groupTable(TR("Что проверять отдельным прогоном:"), bcGroups, pickedBcGroups, toggleBcGroup,
          TR("В выборке нечего проверять."))),
    },
    {
      key: "termcheck", label: FULL_STEP_LABELS.termcheck, hint: TR("третья модель смотрит только на результат"),
      modelId: tcModel, onModel: pickTcModel, plan: stepPlan("termcheck"),
      planEst: planEstOf("termcheck", stepModel("termcheck", tcModelInfo)),
      soloEst: estimateRun("termcheck", project.segments.filter(s => termcheckable(s, currentIdSet)),
        stepModel("termcheck", tcModelInfo)),
      onSolo: runTermcheckBatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "termcheck" ? batchRun : null,
      options: groupTable(TR("Что проверять отдельным прогоном:"), tcGroups, pickedTcGroups, toggleTcGroup,
        TR("В выборке нечего проверять.")),
    },
    {
      key: "termaudit", label: FULL_STEP_LABELS.termaudit,
      hint: TR("модель смотрит термин В РЯДУ соседей — то, чего морфология не умеет"),
      modelId: tcxModel, onModel: pickTcxModel, plan: stepPlan("termaudit"),
      planEst: planEstOf("termaudit", stepModel("termaudit", tcxModelInfo)),
      // Состав ОБЕИХ кнопок берём у сервера: приказные термины сегмента
      // браузер не считает и считать не должен — повтори мы этот расчёт,
      // под соседними кнопками встали бы разные числа (замер на боевом
      // проекте: 713 против 2711, разница в 3.8 раза).
      soloEst: planEstOf("termaudit", stepModel("termaudit", tcxModelInfo)),
      onSolo: runTermAudit, onStop: stopJob,
      running: batchRun && batchRun.engine === "termaudit" ? batchRun : null,
      soloNote: TR("Один вызов на сегмент, сколько бы утверждённых терминов в нём ")
        + TR("ни было. Вердикт «передан верно» СНИМАЕТ претензию: ремонт по ней ")
        + TR("больше не пойдёт. «Передан неверно» уходит человеку на экран «Анализ» ")
        + TR("— это вопрос к записи глоссария, а не к строке."),
    },
    {
      key: "repair", label: FULL_STEP_LABELS.repair,
      /* Подсказка в СВЁРНУТОЙ строке. Группы «уже чинилось» и «правка была
         откачена» сняты по умолчанию и живут в раскрытой части, поэтому
         сегменты с непочиненными находками просто не видны: на боевом проекте
         так молча стояли 510 строк, и понять, почему состав шага «—», было
         неоткуда. Молчать об отложенной работе нельзя — это тот же закон, что
         у `impact["futile"]`: расходиться с находками они не перестали. */
      hint: rpWaiting
        ? TR("правит по всем находкам · ещё ") + rpWaiting
          + TR(" с находками ждут второго захода — раскройте строку")
        : TR("правит по всем находкам, включая глоссарий"),
      modelId: rpModel, onModel: pickRpModel, plan: stepPlan("repair"),
      planEst: planEstOf("repair", stepModel("repair", rpModelInfo),
        { recheckModel: stepModel("backcheck", bcModelInfo),
          judge: bcJudge, judgeModel: judgeModelInfo || stepModel("backcheck", bcModelInfo) }),
      soloEst: estimateRun("repair", project.segments.filter(s => repairable(s, currentIdSet)),
        stepModel("repair", rpModelInfo), { recheckModel: stepModel("backcheck", bcModelInfo),
          judge: bcJudge, judgeModel: judgeModelInfo || stepModel("backcheck", bcModelInfo) }),
      onSolo: runRepairBatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "repair" ? batchRun : null,
      soloNote: TR("Правка плюс перепроверка теми же проверками: если оценка упадёт, текст откатится. Один заход на один текст — второй даст то же самое за те же деньги."),
      options: React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
        React.createElement("div", { className: "row between", style: { gap: 12, flexWrap: "wrap" } },
          React.createElement("div", { style: { minWidth: 0 } },
            React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, display: "flex", alignItems: "center" } },
              TR("Чинить подтверждённые человеком"),
              React.createElement(InfoTip, { title: TR("Что произойдёт"), body: TR("Ремонт правит только по конкретным находкам и меняет минимум слов — сегмент не переводится заново, и полной цены прогона тут нет. Но прежний текст уйдёт в «прошлый перевод», статус станет «требует проверки», а отметка «подтвердил человек» снимется: она относилась к тексту, которого больше нет.\n\nЕсли после правки оценка УПАЛА, текст откатывается вместе с прежними проверками — ровные оценки правку не отменяют.\n\nУ захода, где кроме мелких замечаний по терминам ничего не было, правило строже: он принимается, только если снял хотя бы одно из тех замечаний, ради которых заходили. Иначе это размен одной придирки на другую — работа за деньги без движения к концу.\n\nГалочка действует только на этот шаг. Перевод по ней ничего не перегоняет.") })),
            React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
              rpConfirmedWaiting
                ? rpConfirmedWaiting + TR(" заверенных сегментов с находками ждут решения")
                : TR("в выборке нет заверенных сегментов с находками"))),
          React.createElement(Switch, { on: rpFixConfirmed, label: TR("Чинить подтверждённые"),
            onClick: toggleRpFixConfirmed })),
        rpFixConfirmed && React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
          TR("С этих сегментов снимется отметка «подтвердил человек» — их придётся заверить заново.")),
        groupTable(TR("Что чинить — отметьте, если нужен второй заход:"),
          rpGroups, pickedRpGroups, toggleRpGroup,
          TR("Нет сегментов с находками. Сначала прогоните back-check или проверку терминов."))),
    },
    {
      key: "medical_qa", label: FULL_STEP_LABELS.medical_qa, hint: TR("числа и отрицания; обратный перевод берёт у back-check"),
      modelId: null, onModel: null, plan: stepPlan("medical_qa"),
      modelNote: ((stepModel("medical_qa", bcModelInfo) || {}).label || "—") + TR(" · от back-check"),
      planEst: planEstOf("medical_qa", stepModel("medical_qa", bcModelInfo)),
      // Своей модели у неё нет: правила детерминированные. Платный вызов —
      // только обратный перевод и только там, где готового от back-check нет.
      soloEst: estimateRun("medical_qa",
        qaSolo.filter(s => !(s.backcheck && !s.backcheck.stale && s.backcheck.back)),
        stepModel("medical_qa", bcModelInfo)),
      onSolo: runChecksBatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "medical_qa" ? batchRun : null,
      soloNote: TR("Считает заново по всей выборке. Сегментам со свежим back-check это бесплатно — обратный перевод у них уже есть."),
    },
  ];

  // Проверка, которую делает та же модель, что переводила, — не независимая,
  // а на независимости стоит автоодобрение терминов. Молчать об этом нельзя.
  // Ремонт тоже: он переписывает перевод, и если это делает та же модель,
  // что переводила, она правит по собственному пониманию текста.
  /* Конфликт по РОЛИ, а не по силе. Ревизия здесь особая: она не переводит,
     но ПИШЕТ окончательный текст и ставит себя провайдером сегмента — значит
     back-check её же моделью станет проверкой себя, сервер молча уйдёт
     на запасную модель (`_backcheck_model`), и смета поплывёт. */
  const modelWarn = (() => {
    const on = (k) => pickedFull.has(k);
    if (on("translate") && [["backcheck", bcModel], ["termcheck", tcModel], ["repair", rpModel]]
        .some(([k, m]) => on(k) && m && m === gptModel))
      return TR("Перевод и проверку делает одна модель. Она не найдёт собственную ошибку — ")
        + TR("выберите другую модель для back-check, терминов или ремонта.");
    /* Ревизия пишет ОКОНЧАТЕЛЬНЫЙ текст и становится провайдером сегмента,
       поэтому back-check её же моделью — проверка себя: сервер уйдёт
       на запасную модель, и смета поплывёт. */
    if (on("review") && on("backcheck") && rvModel && rvModel === bcModel)
      return TR("Back-check той же моделью, что и ревизия. На переписанных ею сегментах ")
        + TR("это проверка себя: сервер возьмёт запасную модель, и смета поплывёт.");
    if (on("review") && on("translate") && rvModel && rvModel === gptModel)
      return TR("Ревизия той же моделью, что и перевод: она перечитывает собственный ")
        + TR("текст и находит в нём меньше.");
    return null;
  })();

  const runFullJob = async () => {
    const steps = FULL_STEP_KEYS.filter(k => pickedFull.has(k));
    if (!steps.length) { toast.warning(TR("Не выбрано ни одного шага"), TR("Отметьте хотя бы один.")); return; }
    // Состав, посчитанный сервером, запоминаем ДО запуска: через секунду
    // разбор уже не пересчитается (см. readRunSnap), а полоса прогресса
    // должна говорить не только «сделано», но и «осталось».
    const planned = {};
    steps.forEach(k => { planned[k] = (fullStepTargets[k] || []).length; });
    const started = await startJob("full", fullRunIds, {
      steps,
      model: gptModel, bc_model: bcModel, tc_model: tcModel, tcx_model: tcxModel,
      rp_model: rpModel, rv_model: rvModel,
      use_judge: bcJudge, judge_model: judgeModel || null,
      // Тот же retry, что и у карточки ремонта: карточка выше посчитала
      // и оценила сегменты по этому же правилу, и разойтись они не должны.
      retry: repairRetry(),
      // Разрешение сервер отдаёт только шагу ремонта (см. _job_chunk_full):
      // перевод по этой галочке не перегоняет ничего.
      include_confirmed: rpFixConfirmed,
    }, TR("В выбранных сегментах нечего делать."), fullEst);
    if (!started) return;
    // Проект и время создания — часть опознания снимка (см. runStepRows):
    // одного номера мало, они начинаются заново после рестарта сервиса.
    const snap = { jobId: started.id, project: started.project,
                   created: started.created, steps: planned };
    writeRunSnap(snap);
    setRunSnap(snap);
  };

  /* ── Второй клик: одобрить термины и применить их к переводу ──────
     Состав сегментов здесь не выбирается и выбираться не может: пока термины
     не одобрены, неизвестно, какие сегменты с ними разойдутся. Список считает
     сервер сразу после одобрения. */
  const runApplyTerms = async () => {
    if (batchRun) { toast.warning(TR("Прогон уже идёт"), TR("Дождитесь окончания.")); return; }
    if (!window.API) return;
    const res = await window.API.safeCall(() => window.API.createJob(project.id, "apply_terms", [], {
      max_tier: null, term_limit: 2000,
      allow_verified: termOrders,
      rp_model: rpModel, bc_model: bcModel, tc_model: tcModel,
      use_judge: bcJudge, judge_model: judgeModel || null,
      include_confirmed: !!impactConfirmed,
    }));
    if (!res || !res.ok) { toast.error(TR("Не удалось запустить"), TR("Сервер не принял задачу.")); return; }
    setJob(res.job);
    toast.info(TR("Одобряем и применяем"),
      TR("Термины уходят в глоссарий, затем сегменты чинятся по ним. Вкладку можно закрыть."));
  };

  const filterDefs = [
    ["all", TR("Все"), counts.all], ["new", TR("Новые"), counts.new], ["translated", TR("Переведено"), counts.translated],
    ["qa", "QA", counts.qa], ["confirmed", TR("Подтверждено"), counts.confirmed], ["failed", TR("Ошибки"), counts.failed],
  ];

  return React.createElement("div", { className: "col", style: { minHeight: 0 } },
    // ---- Toolbar ----
    React.createElement("div", { className: "editor-toolbar" },
      React.createElement("div", { className: "row between row-wrap" },
        React.createElement("div", { className: "row", style: { gap: 10 } },
          React.createElement(Icon, { name: "folder", size: 18, style: { color: "var(--c-primary)" } }),
          React.createElement(Select, { value: project.id, onChange: (e) => store.openProject(Number(e.target.value)), style: { width: "auto", minWidth: 280, fontWeight: 600 } },
            store.projects.map(p => React.createElement("option", { key: p.id, value: p.id }, "#" + p.id + " — " + p.title))),
          React.createElement(LangPair, { src: project.src, tgt: project.tgt })
        ),
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement("span", { className: "dim", style: { fontSize: 13 } }, TR("Высота таблицы")),
          React.createElement("input", { type: "range", min: 320, max: 720, step: 20, value: height,
            onChange: (e) => setHeight(Number(e.target.value)), style: { width: 130 }, "aria-label": TR("Высота таблицы") }),
          React.createElement(IconBtn, { icon: "filter", label: TR("Доп. фильтры"), sm: true, active: showFilters, onClick: () => setShowFilters(s => !s) })
        )
      ),
      React.createElement("div", { className: "row between row-wrap" },
        React.createElement("div", { className: "segmented" },
          filterDefs.map(([v, l, n]) => React.createElement("button", { key: v, className: filter === v ? "on" : "", onClick: () => setFilter(v) },
            l, React.createElement("span", { className: "cnt" }, n)))
        ),
        // «Выбрать все N по фильтру» — без неё выбор всех сегментов под текущим
        // фильтром (например, всех переведённых Google) means тыкать чекбокс на
        // каждой из PAGE_SIZE-страниц вручную: при 2670 сегментах и странице
        // по 10 штук это сотни кликов. Список берём из filtered — он уже
        // учитывает статус/риск/поиск/фильтр из «Анализа», и именно на нём
        // потом строится разбивка «Переводить заново» по движку-донору.
        checkedSegs.size > 0
          ? React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setCheckedSegs(new Set()) },
              TR("Снять выбор (") + checkedSegs.size + ")")
          : filtered.length > 0 && React.createElement(Btn, { variant: "ghost", size: "sm",
              onClick: () => setCheckedSegs(new Set(filtered.map(s => s.id))) },
              TR("Выбрать все ") + filtered.length + (inZone ? TR(" в зоне")
                : (filter !== "all" || query || activeFilter ? TR(" по фильтру") : "")))
        // Поиска здесь больше нет: он один и стоит над таблицей, рядом
        // с переходом по номеру. Два поля на одно состояние — это два места,
        // где его ищут, и лишняя высота у залипающей панели, из-за которой
        // таблицу видно хуже.
      ),
      showFilters && React.createElement("div", { className: "row row-wrap", style: { gap: 14, padding: "4px 2px" } },
        React.createElement(Select, { value: riskFilter, onChange: (e) => setRiskFilter(e.target.value), style: { width: 200 } },
          [["all", TR("Любой риск")], ["low", TR("Низкий риск")], ["medium", TR("Средний риск")], ["high", TR("Высокий риск")], ["critical", TR("Критический риск")]]
            .map(([v, l]) => React.createElement("option", { key: v, value: v }, l))),
        React.createElement(Select, { value: originFilter, onChange: (e) => setOriginFilter(e.target.value), style: { width: 220 } },
          [["all", TR("Любой источник")], ["para", TR("Из абзацев документа")], ["image", TR("Из надписей на картинках")]]
            .map(([v, l]) => React.createElement("option", { key: v, value: v }, l)))
      ),

      // Идущий прогон: виден и после перезагрузки страницы. Живёт ВНУТРИ
      // залипающей панели намеренно — таблица длинная, а полоса нужна на
      // экране всё время, пока идёт работа: на ней и остановка.
      job && React.createElement(RunStrip, {
        job: job, steps: runStepRows(job, runSnap), onStop: stopJob })
    ),

    // ---- Segment filter banner ----
    activeFilter && React.createElement("div", { className: "editor-main", style: { paddingBottom: 0 } },
      React.createElement("div", { className: "card", style: { padding: "8px 14px", background: "var(--bg-sunken)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 } },
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement(Icon, { name: "filter", size: 15, style: { color: "var(--c-primary)" } }),
          React.createElement("span", { style: { fontSize: 13, fontWeight: 600 } }, TR("Фильтр: ") + activeFilter.size + TR(" сегментов из анализа"))),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "x", onClick: () => { window._mcat_sf = null; store.setSegmentFilter(null); } }, TR("К основному файлу"))
      )
    ),

    // ---- Составной прогон: одна кнопка на весь конвейер ----
    // Два блока запуска стоят рядом, а не друг под другом во всю ширину:
    // растянутые на монитор, они читались строчками по две тысячи пикселей,
    // и до второй кнопки приходилось листать. Узко — не значит меньше: состав
    // и причины в строках шагов остались целиком.
    React.createElement("div", { className: "editor-main", style: { paddingBottom: 0 } },
      React.createElement("div", { className: "run-decks" },
        React.createElement(FullRunCard, {
          running: job && job.kind === "full" ? job : null,
          onRun: runFullJob, onStop: stopJob,
          rows: fullRunRows, picked: pickedFull, onToggle: toggleFullStep,
          scopeSize: fullRunIds.length,
          planBusy: planBusy, planReady: !!runPlan,
          openStep: openStep, onOpenStep: setOpenStep,
          checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf),
            est: fullEst, modelWarn: modelWarn,
          fixConfirmed: rpFixConfirmed, fixConfirmedCount: rpConfirmedWaiting,
          models: gptModels, disabled: !!job }),
        // Одобрение терминов и то, что из него следует, — расхождения готовых
        // переводов с одобренным. Один сюжет, но две СОСЕДНИЕ колонки: одна
        // под другой карточка соответствия уезжала под сгиб, а смотрят на неё
        // сразу после одобрения.
        React.createElement(ApplyTermsCard, {
          running: job && job.kind === "apply_terms" ? job : null,
          onRun: runApplyTerms, onStop: stopJob, disabled: !!job,
          preview: autoPreview, sources: autoPreview && autoPreview.sources,
          includeConfirmed: impactConfirmed,
          onIncludeConfirmed: () => setImpactConfirmed(v => !v),
          confirmedCount: impact ? impact.confirmed.length : 0,
          orders: termOrders,
          onOrders: () => setOrdersFor(v => (v === project.id ? null : project.id)),
          // Состав ремонта — тот же список, что показывает секция соответствия
          // ниже, МИНУС застрявшие: сервер их не возьмёт, и обещать по ним
          // работу значит показать под кнопкой число, которого не будет.
          pendingSegs: impact
            ? (impactConfirmed ? impact.segments : impact.pending)
                .filter(i => (impact.futile || []).indexOf(i) === -1).length : 0,
          futileSegs: impact ? (impact.futile || []).length : 0,
          // Соответствие глоссарию живёт секцией ЭТОЙ карточки, а не отдельной
          // колонкой: списки «По терминам» и начертание — на вкладке «Анализ»,
          // здесь остались команды, которых больше нигде нет («Пересчитать»
          // с refresh и «Перевести заново»). Секция не прячется при нуле —
          // вместе с ней исчезал бы «Пересчитать», единственный способ
          // убедиться, что ноль настоящий, а не остался с прошлого расчёта.
          impact: impact, impactBusy: impactBusy,
          onImpactRefresh: () => loadImpact(true),
          onRetranslate: runImpactRetranslate,
          onDrill: (ids) => { store.setSegmentFilter(ids); setPage(1); },
          retEst: impact ? estimateRun("translate", project.segments.filter(s =>
            new Set(impactConfirmed ? impact.segments : impact.pending).has(s.id)), gptModelInfo) : null,
          retRunning: !!(batchRun && batchRun.engine === "translate" && job && job.params && job.params.via === "impact") }),
        // «Анализ» — те же три корзины, что на одноимённой вкладке, только
        // рядом с кнопками, которые их осушают. Появляется ПОСЛЕ первого
        // прогона (см. loadAnalysis): в проекте из одних «новых» корзины
        // тривиальны. Числа считает сервер — браузер их не повторяет.
        tkSum && React.createElement(EditorAnalysisCard, {
          sum: tkSum,
          onDrill: (ids) => { store.setSegmentFilter(ids); setPage(1); },
          onOpen: () => store.go("preflight") }))),

    // ---- Body: table + detail ----
    React.createElement("div", { className: "editor-body" },
      React.createElement("div", { className: "editor-main" },
        /* Поиск и переход по номеру — прямо над таблицей, и поиск тут
           единственный. Раньше он жил в залипающей панели, то есть за двумя
           блоками запуска высотой в экран: до таблицы от него было далеко,
           а рядом с таблицей его не было вовсе.
           Поиск раздельный по оригиналу и переводу: искать английский термин
           по русскому тексту бессмысленно и наоборот. */
        React.createElement("div", { className: "table-head" },
          React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
            // Маленькая строка стоит над колонкой «#» — туда и вводят номер.
            React.createElement("div", { className: "seg-jump" },
              React.createElement("span", { className: "sj-hash" }, "#"),
              React.createElement("input", { className: "input", value: jump, inputMode: "numeric",
                placeholder: "№",
                "aria-label": TR("Перейти к сегменту по номеру"),
                title: TR("Номер сегмента: покажу его и по ") + ZONE_HALF + TR(" соседей до и после"),
                onChange: (e) => setJump(e.target.value),
                onKeyDown: (e) => { if (e.key === "Enter") goToZone(jump); } })),
            React.createElement(IconBtn, { icon: "arrowR", label: TR("Перейти к сегменту"), sm: true,
              onClick: () => goToZone(jump) }),
            React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value),
              placeholder: searchPlaceholder }),
            React.createElement(Select, { value: scope, onChange: (e) => pickScope(e.target.value),
              style: { width: "auto", flex: "0 0 auto" }, "aria-label": TR("Где искать") },
              scopeOpts.map(([v, l]) => React.createElement("option", { key: v, value: v }, l))),
            query && React.createElement(IconBtn, { icon: "close", label: TR("Очистить поиск"), sm: true, onClick: () => setQuery("") }),
            query && React.createElement("span", { className: "dim", style: { fontSize: 12, whiteSpace: "nowrap" } },
              filtered.length ? TR("найдено: ") + filtered.length : TR("ничего не найдено"))
          ),
          // Пока открыта зона, в таблице не весь файл. Сказать об этом обязаны
          // мы: иначе «куда делись сегменты» человек ищет в фильтрах, которых
          // мы же и не оставили.
          inZone && React.createElement("div", { className: "zone-strip" },
            React.createElement(Icon, { name: "target", size: 14, style: { color: "var(--c-primary)" } }),
            React.createElement("span", null,
              TR("Зона сегмента #") + zone + ": " + (zoneIdx - zoneFrom) + TR(" до и ") + (zoneTo - zoneIdx - 1) + TR(" после")
              + TR(" — строки ") + (zoneFrom + 1) + "–" + zoneTo + TR(" из ") + project.segments.length),
            // Выход из зоны оставляет человека НА ТОМ ЖЕ месте файла: страница
            // берётся по сегменту-центру. Иначе «Весь файл» телепортирует
            // на первую страницу, и найденное место приходится искать заново.
            React.createElement(Btn, { variant: "secondary", size: "sm", icon: "close",
              onClick: () => {
                jumpRef.current = true;                 // страницу сменили мы — выбор не сбрасывать
                setPage(Math.floor(zoneIdx / PAGE_SIZE) + 1);
                setZone(null); setJump("");
              } }, TR("Весь файл"))
          )
        ),
        React.createElement("div", { className: "table-wrap" },
          React.createElement("div", { className: "tbl-scroll", style: { maxHeight: height } },
            React.createElement("table", { className: "tbl" },
              React.createElement("thead", null, React.createElement("tr", null,
                React.createElement("th", { style: { width: 36, textAlign: "center" } },
                  React.createElement("input", { type: "checkbox",
                    checked: paged.length > 0 && paged.every(s => checkedSegs.has(s.id)),
                    ref: el => { if (el) el.indeterminate = paged.some(s => checkedSegs.has(s.id)) && !paged.every(s => checkedSegs.has(s.id)); },
                    onChange: (e) => {
                      setCheckedSegs(prev => {
                        const next = new Set(prev);
                        if (e.target.checked) paged.forEach(s => next.add(s.id));
                        else paged.forEach(s => next.delete(s.id));
                        return next;
                      });
                    }
                  })
                ),
                React.createElement("th", { className: "col-id" }, "#"),
                React.createElement("th", null, TR("Оригинал · ") + (project.src || "")),
                React.createElement("th", null, TR("Перевод · ") + (project.tgt || "")),
                React.createElement("th", { style: { width: 132 } }, TR("Статус")),
                React.createElement("th", { style: { width: 76 },
                  title: TR("Ремонт, находки по терминам, back-check") }, TR("Проверки")),
                React.createElement("th", { style: { width: 56 } }, "")
              )),
              React.createElement("tbody", null,
                paged.map(s => React.createElement(SegRow, {
                  key: s.id, seg: s, selected: s.id === selId, busy: busy[s.id],
                  checked: checkedSegs.has(s.id), models: gptModels,
                  hlSrc: scope !== "tgt" ? query : "", hlTgt: scope !== "src" ? query : "",
                  onCheck: (e) => { e.stopPropagation(); setCheckedSegs(prev => { const n = new Set(prev); n.has(s.id) ? n.delete(s.id) : n.add(s.id); return n; }); },
                  onSelect: () => setSelId(s.id),
                  onTranslate: () => doTranslate(s),
                  onConfirm: () => doConfirm(s), onRevert: () => doRevert(s),
                }))
              )
            )
          )
        ),
        filtered.length === 0 && React.createElement("div", { style: { padding: 20 } },
          React.createElement(EmptyState, { icon: "filter", title: TR("Нет сегментов по фильтру"),
            sub: query ? "«" + query + TR("» не найдено — ") + scopeOpts.find(o => o[0] === scope)[1].toLowerCase() + TR(". Смените область поиска или очистите запрос.")
                       : TR("Измените фильтр статуса или поиск.") })),
        React.createElement("div", { className: "row", style: { gap: 16, marginTop: 12, fontSize: 12, color: "var(--text-3)", flexWrap: "wrap" } },
          React.createElement(LegendDot, { color: "var(--st-new-fg)", label: TR("Новый") }),
          React.createElement(LegendDot, { color: "var(--c-primary)", label: TR("Переведён") }),
          React.createElement(LegendDot, { color: "var(--c-warning)", label: "QA" }),
          React.createElement(LegendDot, { color: "var(--c-success)", label: TR("Подтверждён") }),
          React.createElement(LegendDot, { color: "var(--c-error)", label: TR("Ошибка") })
        ),
        filtered.length > 0 && totalPages > 1 && React.createElement(Pagination, { page: curPage, totalPages, onGo: setPage }),
        React.createElement(StatusBar, {
          segShown: filtered.length, segTotal: project.segments.length,
          wordsShown: wordCount(filtered), wordsTotal: wordCount(project.segments),
          charsShown: charCount(filtered), charsTotal: charCount(project.segments),
        })
      ),

      // ---- Detail sidebar ----
      React.createElement("div", { className: "editor-side" },
        selected
          ? React.createElement(SegDetail, { key: selected.id, seg: selected, project, store, toast, busy: busy[selected.id],
              onTranslate: () => doTranslate(selected, true), onQA: () => doQA(selected), onChecks: () => doChecks(selected), onConfirm: (draftTarget) => doConfirm(selected, draftTarget),
              bcModels: gptModels, bcModel: bcModel, onBcModel: pickBcModel,
              bcJudge: bcJudge, judgeModel: judgeModel,
              tcModel: tcModel, rpModel: rpModel, tcActionable: tcActionable })
          : React.createElement(EmptyState, { icon: "edit", title: TR("Сегмент не выбран"), sub: TR("Выберите строку в таблице.") })
      )
    ),

    batchPlan && (() => {
      const est = estimateBatch(batchPlan.targets, gptModelInfo);
      return React.createElement(Modal, {
        title: TR("Запустить GPT-пакет?"), icon: "zap", onClose: () => setBatchPlan(null),
        footer: React.createElement(React.Fragment, null,
          React.createElement(Btn, { variant: "ghost", onClick: () => setBatchPlan(null) }, TR("Отмена")),
          React.createElement(Btn, { variant: "primary", icon: "zap",
            onClick: () => runBatch(batchPlan.targets, batchPlan.hasExplicitCheck) }, TR("Запустить"))) },
        React.createElement("div", { style: { display: "grid", gap: 10, fontSize: 14 } },
          React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, TR("Сегментов")),
            React.createElement("b", null, batchPlan.targets.length)),
          React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, TR("Модель")),
            React.createElement("b", null, gptModelInfo ? gptModelInfo.label : TR("по умолчанию"))),
          React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, TR("Примерное время")),
            React.createElement("b", null, "≈ " + fmtDuration(est.seconds))),
          est.cost != null && React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, TR("Примерная стоимость")),
            React.createElement("b", null, "≈ " + fmtCost(est.cost))),

          // Последний экран перед запуском — здесь и должно быть видно
          // последствие, а не только в свёрнутой строке шага, где галочку
          // включили несколько кликов назад.
          (() => {
            const n = batchPlan.targets.filter(s => s.status === "confirmed").length;
            return n > 0 && React.createElement("div", {
              style: { fontSize: 12.5, lineHeight: 1.5, padding: "7px 9px", borderRadius: "var(--r-md)",
                       background: "var(--bg-sunken)", border: "1px solid var(--c-warning)", color: "var(--text-2)" } },
              React.createElement("b", { style: { color: "var(--c-warning)" } }, TR("Среди них подтверждённых: ") + n),
              TR(" — с них снимется отметка «подтвердил человек»."));
          })(),

          // Чем эти сегменты переведены сейчас — чтобы было видно, что именно
          // перегоняется и не уходит ли на повтор уже сделанное нужной моделью
          (() => {
            const by = {};
            batchPlan.targets.forEach(s => {
              const l = providerLabel(providerOf(s), gptModels) || TR("ещё не переведён");
              by[l] = (by[l] || 0) + 1;
            });
            const rows = Object.keys(by).sort((a, b) => by[b] - by[a]);
            if (rows.length === 1 && rows[0] === "ещё не переведён") return null;
            return React.createElement("div", { style: { borderTop: "1px solid var(--border)", paddingTop: 10 } },
              React.createElement("div", { className: "muted", style: { marginBottom: 6 } }, TR("Сейчас переведено через")),
              rows.map(l => React.createElement("div", { key: l, className: "row between", style: { fontSize: 13, padding: "2px 0" } },
                /* `l` — ключ группировки, он обязан остаться русским
                   (по нему идёт сравнение строкой ниже). Переводится РОВНО
                   место показа; название модели словарь не знает и вернёт
                   его как есть. */
                React.createElement("span", null, TR(l)),
                React.createElement("b", null, by[l]))));
          })(),
          React.createElement("p", { className: "muted", style: { margin: 0, fontSize: 12.5, lineHeight: 1.6 } },
            TR("Оценка ориентировочная: считается по объёму текста, фактический расход зависит от ответа модели. ") +
            TR("Прогон идёт на сервере порциями по ") + BATCH_CHUNK + TR(" сегментов, переводы сохраняются после каждой — ") +
            TR("вкладку можно закрыть, а остановка не откатывает уже сделанное."))
        )
      );
    })(),

    propagateAsk && React.createElement(Modal, {
      title: TR("Такой же исходник есть ещё в проекте"), icon: "repeat", onClose: () => setPropagateAsk(null),
      footer: React.createElement(React.Fragment, null,
        React.createElement(Btn, { variant: "ghost", onClick: () => setPropagateAsk(null) }, TR("Не сейчас")),
        propagateAsk.prop.confirmed.length > 0 && React.createElement(Btn, { variant: "secondary", icon: "alert", onClick: () => doPropagate(true) },
          TR("Перезаписать и подтверждённые (") + (propagateAsk.prop.pending.length + propagateAsk.prop.confirmed.length) + ")"),
        propagateAsk.prop.pending.length > 0 && React.createElement(Btn, { variant: "primary", icon: "repeat", onClick: () => doPropagate(false) },
          TR("Применить к ") + propagateAsk.prop.pending.length)) },
      React.createElement("div", { className: "col", style: { gap: 12 } },
        React.createElement("p", { className: "muted", style: { margin: 0, lineHeight: 1.6 } },
          TR("Подтверждённый перевод сегмента "),
          React.createElement("b", { style: { color: "var(--text)" } }, "#" + propagateAsk.seg.id),
          TR(" отличается от перевода других сегментов с тем же исходным текстом.")),
        React.createElement("div", { className: "card", style: { padding: "10px 14px", background: "var(--bg-sunken)", fontSize: 13, lineHeight: 1.7 } },
          propagateAsk.prop.pending.length > 0 && React.createElement("div", null,
            TR("Не подтверждено — можно обновить сразу: "),
            React.createElement("b", null, propagateAsk.prop.pending.map(id => "#" + id).join(", "))),
          propagateAsk.prop.confirmed.length > 0 && React.createElement("div", { style: { marginTop: 6, color: "var(--c-warning)" } },
            TR("Уже подтверждено кем-то — перезапись только по явной команде: "),
            React.createElement("b", null, propagateAsk.prop.confirmed.map(id => "#" + id).join(", ")))),
        React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 12.5, lineHeight: 1.6 } },
          TR("Обновлённые сегменты получат статус «Переведён», а не «Подтверждён»: заверить перевод должен человек. Прежний текст сохраняется и виден в карточке сегмента.")))
    ),

    revertTarget && React.createElement(Modal, {
      title: TR("Снять подтверждение?"), icon: "warn", onClose: () => setRevertTarget(null),
      footer: React.createElement(React.Fragment, null,
        React.createElement(Btn, { variant: "ghost", onClick: () => setRevertTarget(null) }, TR("Отмена")),
        React.createElement(Btn, { variant: "primary", icon: "repeat", onClick: confirmRevert }, TR("Снять подтверждение"))) },
      React.createElement("p", { className: "muted", style: { margin: 0, lineHeight: 1.6 } },
        TR("Сегмент "), React.createElement("b", { style: { color: "var(--text)" } }, "#" + revertTarget.id),
        TR(" будет возвращён из статуса «Подтверждён» в «Переведён». Запись в памяти переводов сохранится."))
    )
  );
}

function Pagination({ page, totalPages, onGo }) {
  const [goto, setGoto] = useState("");
  const nums = [];
  if (totalPages <= 7) { for (let i = 1; i <= totalPages; i++) nums.push(i); }
  else {
    nums.push(1);
    if (page > 3) nums.push("…");
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) nums.push(i);
    if (page < totalPages - 2) nums.push("…");
    nums.push(totalPages);
  }
  const submitGoto = (e) => {
    if (e.key !== "Enter") return;
    const n = parseInt(goto, 10);
    if (n >= 1 && n <= totalPages) onGo(n);
    setGoto("");
  };
  return React.createElement("div", { className: "pagination" },
    React.createElement("button", { className: "page-num", disabled: page <= 1, onClick: () => onGo(page - 1), "aria-label": TR("Назад") },
      React.createElement(Icon, { name: "chevL", size: 15 })),
    nums.map((n, i) => n === "…"
      ? React.createElement("span", { key: "e" + i, className: "page-ellipsis" }, "…")
      : React.createElement("button", { key: n, className: "page-num" + (n === page ? " on" : ""), onClick: () => onGo(n), "aria-current": n === page ? "page" : null }, n)),
    React.createElement("button", { className: "page-num", disabled: page >= totalPages, onClick: () => onGo(page + 1), "aria-label": TR("Вперёд") },
      React.createElement(Icon, { name: "chevR", size: 15 })),
    React.createElement("span", { className: "dim", style: { marginLeft: 6, fontSize: 13 } }, TR("Перейти:")),
    React.createElement("input", { className: "input page-goto", value: goto, onChange: (e) => setGoto(e.target.value.replace(/\D/g, "")),
      onKeyDown: submitGoto, placeholder: String(page), "aria-label": TR("Перейти к странице") })
  );
}

function StatusBar({ segShown, segTotal, wordsShown, wordsTotal, charsShown, charsTotal }) {
  const fmt = (n) => n.toLocaleString("ru-RU");
  return React.createElement("div", { className: "statusbar" },
    React.createElement("div", { className: "row", style: { gap: 10, flexWrap: "wrap" } },
      React.createElement("span", { className: "sb-group" }, React.createElement(Icon, { name: "list", size: 14 }), TR(" Сегментов: "), React.createElement("b", null, segShown + "/" + segTotal)),
      React.createElement("span", { className: "sb-sep" }, "·"),
      React.createElement("span", { className: "sb-group" }, TR("Слов: "), React.createElement("b", null, fmt(wordsShown) + "/" + fmt(wordsTotal))),
      React.createElement("span", { className: "sb-sep" }, "·"),
      React.createElement("span", { className: "sb-group" }, TR("Знаков: "), React.createElement("b", null, fmt(charsShown) + "/" + fmt(charsTotal)))
    ),
    React.createElement("span", { className: "sb-save" }, React.createElement("span", { className: "sb-dot" }), TR("Автосохранение"), React.createElement(Icon, { name: "check", size: 13, stroke: 2.6, style: { color: "var(--c-success)" } }))
  );
}

function LegendDot({ color, label }) {
  return React.createElement("span", { className: "row", style: { gap: 6 } },
    React.createElement("span", { style: { width: 10, height: 10, borderRadius: 3, background: color, display: "inline-block" } }), label);
}

/* Составной прогон. Одна кнопка на весь конвейер, но состав виден до запуска:
   какие шаги входят, сколько сегментов затронет каждый и во что это обойдётся.
   Порядок шагов фиксирован на сервере и здесь только показан — Medical QA
   берёт обратный перевод из back-check, ремонту нужны находки всех остальных. */
/* ── Полоса идущего прогона ────────────────────────────────────────────
   Одна строка: что идёт, сколько сделано из скольких, чем это остановить —
   и шаги составного прогона отдельными значками.

   Про шаги здесь говорится ровно то, что известно достоверно. Счётчики
   приходят с сервера порциями по пять сегментов, поэтому «сделано» у шага —
   это факт, а не оценка браузера. Галочка означает «шаг взял всё, что ему
   отвёл разбор», и ничего больше. Подсветить один «текущий» шаг нельзя:
   каждая порция проходит все выбранные шаги по очереди, так что незакрытые
   шаги идут одновременно — на разных порциях.

   Остатка нет — значит прогон запущен не из этой вкладки и состав шагов
   неизвестен. Тогда показываем только сделанное: придумать «осталось»
   было бы враньём ровно того сорта, ради которого состав считает сервер. */
/* ── Сколько прогон потратил НА САМОМ ДЕЛЕ ────────────────────────────────
   Берётся из usage в ответах моделей (сервер складывает их в job.usage), а не
   из нашего пересчёта объёма текста. Разница принципиальная: смета — это
   предположение о том, сколько модель ответит, а здесь то, за что выставят счёт.

   Пока не было ни одного вызова — молчим. «$0.00» под идущим прогоном читается
   как «работа бесплатна», а не как «платить ещё не начали».

   Вызовы по неизвестной цене (модели нет в каталоге) называем отдельно и НЕ
   прибавляем нулём: расход, показанный меньше настоящего, — ровно то враньё,
   ради которого учёт и заводился. */
function spendOf(job) {
  const u = job && job.usage;
  if (!u || !u.calls) return null;
  const est = job.params ? job.params.est_cost : null;
  return { cost: u.cost, est: est == null ? null : est, unpriced: u.unpriced || 0, usage: u };
}

function spendTitle(sp) {
  const u = sp.usage;
  return TR("Считано с ответов моделей: ") + u.calls + TR(" вызовов, ")
    + Math.round(u.in / 1000) + TR("К входных токенов")
    + (u.cached_in ? TR(" (из них ") + Math.round(u.cached_in / 1000) + TR("К кэшированных — скидка на них тут не учтена, цифра завышена на неё)") : "")
    + ", " + Math.round(u.out / 1000) + TR("К выходных")
    + (u.reasoning ? TR(", включая ") + Math.round(u.reasoning / 1000) + TR("К на рассуждения") : "")
    + TR(".\n\nЦена — по каталогу моделей. Смета до запуска считается по объёму текста и точной быть не может; это число — то, за что выставят счёт.")
    + (sp.unpriced ? TR("\n\nВызовов по модели без цены: ") + sp.unpriced + TR(". Они в сумму НЕ входят.") : "");
}

function RunStrip({ job, steps, onStop }) {
  const spend = spendOf(job);
  const pct = Math.round(job.done / Math.max(1, job.total) * 100);
  const phase = job.stopping ? TR("останавливается")
    : job.status === "queued" ? TR("в очереди") : TR("идёт на сервере");
  const unknown = steps.length > 0 && steps.every(st => st.total == null);
  return React.createElement("div", { className: "run-strip" },
    React.createElement(Spinner, null),
    React.createElement("div", { className: "rs-main" },
      React.createElement("div", { className: "rs-title" },
        React.createElement("span", null, (JOB_LABELS[job.kind] || job.kind) + " — " + phase),
        React.createElement("span", { className: "rs-num" }, job.done + TR(" из ") + job.total),
        spend && React.createElement("span", { className: "rs-num", title: spendTitle(spend) },
          TR("потрачено ") + fmtCost(spend.cost)
          + (spend.est != null ? TR(" из ≈ ") + fmtCost(spend.est) : "")),
        React.createElement("span", { className: "dim", style: { fontWeight: 500, fontSize: 11.5 } },
          TR("вкладку можно закрыть — прогон продолжится"))),
      React.createElement(ProgressBar, { value: pct })),
    React.createElement(Btn, { variant: "ghost", size: "sm", onClick: onStop, disabled: !!job.stopping },
      job.stopping ? TR("Останавливаем…") : TR("Остановить")),

    steps.length > 0 && React.createElement("div", { className: "run-steps" },
      steps.map(st => React.createElement("span", {
        key: st.key,
        className: "run-step " + (st.complete ? "ok" : "on"),
        title: st.label + ": " + (
          // Состава нет — говорим только о сделанном. Сравнивать с total здесь
          // нельзя: в JS `4 > null` — правда, и подпись соврала бы про разбор.
          st.total == null ? TR("сделано ") + st.done
            + TR(" — сколько всего, неизвестно: прогон запущен не из этой вкладки")
          : st.total === 0 ? TR("разбор не отвёл ему ни одного сегмента")
          // Ремонт умеет выйти за план: находки рождают проверки этого же
          // прогона, а разбор считал по прежним. Так и говорим.
          : st.done > st.total ? TR("сделано ") + st.done + TR(" — больше, чем было в разборе (")
              + st.total + TR("): находки добавили проверки этого же прогона")
          : st.complete ? TR("взял все ") + st.total + TR(" сегм., которые ему отвёл разбор")
          : TR("сделано ") + st.done + TR(" из ") + st.total + TR(", осталось ") + st.left) },
        st.complete
          ? React.createElement(Icon, { name: "check", size: 12, stroke: 3 })
          : React.createElement("span", { className: "rs-dot" }),
        st.label,
        React.createElement("b", null, st.done),
        !st.complete && st.left != null
          ? React.createElement("span", { className: "dim" }, TR("· осталось ") + st.left) : null)),
      unknown && React.createElement("span", { className: "dim", style: { fontSize: 11.5, alignSelf: "center" } },
        TR("остаток по шагам не показываем: прогон запущен не из этой вкладки"))));
}

const FULL_RUN_TIP = TR("Один прогон вместо пяти: перевод → back-check → проверка терминов → ремонт → Medical QA. Порядок фиксирован и важен: терминологию в глоссарий собирает та из двух проверок, что отработала второй; ремонт чинит по находкам обеих; Medical QA идёт последней, чтобы описывать окончательный текст, а не тот, который через шаг перепишут.\n\nПереводит одна модель, проверяют другие — в этом весь смысл: проверка, сделанная той же моделью, что и перевод, независимой не является.\n\nСостав считает сервер и показывает целиком: разверните строку шага, чтобы увидеть, кого он возьмёт и почему пропустит остальных. Готовую проверку он второй раз не оплачивает, а вердикт более сильной модели не даёт перезаписать более слабой — подбирать это галочками вручную больше не нужно. Проверки посчитаны и по тем сегментам, которые будут переведены в этом же прогоне.\n\nВ той же строке любой шаг запускается отдельно и по своим галочкам: это способ намеренно перепроверить то, что общий прогон считает сделанным.\n\nЧтобы сузить прогон, отметьте сегменты галочками или включите фильтр. Прогон идёт на сервере — вкладку можно закрыть.");

/* ── Составной прогон: одна таблица на весь конвейер ───────────────────────
   Шаги, их модели, состав, цена и запуск по отдельности — в одном месте.
   Раньше это жило в двух: большая кнопка здесь, а галочки «что проверять» —
   в свёрнутом блоке «Отдельные прогоны». Скрытый переключатель менял то,
   что делает главная кнопка, и человек шёл его искать, чтобы не переплатить.

   Строка таблицы отвечает на четыре вопроса сразу: пойдёт ли шаг в общий
   прогон, какой моделью, сколько сегментов и почём. Развёрнутая строка —
   на пятый: почему именно столько и как запустить этот шаг отдельно. */
function StepRow({ row, on, onToggle, open, onOpen, disabled, models }) {
  const p = row.plan;
  const est = row.planEst;
  const cell = (extra) => Object.assign({ padding: "7px 0", alignSelf: "center" }, extra || {});
  const reasons = (items, prefix, color) => (items || []).length
    ? React.createElement("div", { style: { fontSize: 11.5, lineHeight: 1.55, color: color } },
        prefix + items.map(r => r.count + " " + r.reason).join(" · "))
    : null;
  return [
    // ── сама строка: галочка, модель, счёт, цена, раскрытие ──
    React.createElement("div", { key: row.key + "-name", style: cell({ opacity: on ? 1 : 0.5 }) },
      React.createElement(Checkbox, { checked: on, onChange: () => onToggle(row.key) },
        React.createElement("span", null,
          React.createElement("b", { style: { fontWeight: 600, fontSize: 13 } }, row.label),
          React.createElement("span", { className: "dim", style: { fontSize: 11.5, display: "block" } },
            row.hint)))),
    React.createElement("div", { key: row.key + "-model", style: cell({ opacity: on ? 1 : 0.5 }) },
      row.onModel
        ? React.createElement(Select, {
            value: row.modelId || "", disabled: disabled,
            onChange: (e) => row.onModel(e.target.value),
            style: { fontSize: 12.5, maxWidth: 200 } },
            (models || []).map(m => React.createElement("option", { key: m.id, value: m.id }, m.label)))
        : React.createElement("span", { className: "dim", style: { fontSize: 12 } }, row.modelNote)),
    React.createElement("div", { key: row.key + "-n", style: cell({ textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600, fontSize: 13, opacity: on ? 1 : 0.5, color: (est && est.count) ? "var(--text-1)" : "var(--text-3)" }) },
      est && est.count ? est.count : "—"),
    React.createElement("div", { key: row.key + "-c", style: cell({ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 12.5, color: "var(--text-2)", opacity: on ? 1 : 0.5 }) },
      est && est.count ? (est.cost != null ? fmtCost(est.cost) : "—") : ""),
    React.createElement("div", { key: row.key + "-x", style: cell({ textAlign: "right" }) },
      React.createElement(IconBtn, { icon: open ? "chevD" : "chevR", sm: true, size: 16,
        label: open ? TR("Свернуть") : TR("Подробнее и запуск по отдельности"),
        onClick: () => onOpen(open ? null : row.key) })),

    // ── раскрытая строка: причины, опции шага, запуск только его ──
    open && React.createElement("div", { key: row.key + "-d",
      style: { gridColumn: "1 / -1", background: "var(--bg-sunken)", borderRadius: 9,
               padding: "10px 13px", margin: "2px 0 8px", display: "flex",
               flexDirection: "column", gap: 9 } },
      p && React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 2 } },
        reasons(p.runs, TR("в общий прогон: "), "var(--text-2)"),
        reasons(p.skips, TR("пропустит: "), "var(--text-3)"),
        p.note && React.createElement("div", { style: { fontSize: 11.5, lineHeight: 1.5, color: "var(--text-3)" } }, p.note)),
      row.options,
      React.createElement("div", { style: { borderTop: "1px solid var(--border)", paddingTop: 9,
        display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 10, flexWrap: "wrap" } },
        React.createElement("div", null,
          React.createElement("div", { style: { fontSize: 12, fontWeight: 600 } }, TR("Запустить только этот шаг")),
          React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5, maxWidth: 460 } },
            row.soloNote || TR("По отмеченному выше, а не по решению сервера: так перепроверяют то, что общий прогон считает уже сделанным.")),
          React.createElement(EstLine, { est: row.soloEst })),
        row.running
          ? React.createElement(Btn, { variant: "ghost", size: "sm", onClick: row.onStop }, TR("Остановить"))
          : React.createElement(Btn, { variant: "secondary", size: "sm", icon: "zap",
              onClick: row.onSolo, disabled: disabled || !(row.soloEst && row.soloEst.count) },
              row.soloEst && row.soloEst.count ? TR("Запустить: ") + row.soloEst.count + TR(" сегм.") : TR("нечего запускать"))))
  ];
}

function FullRunCard({ running, onRun, onStop, rows, picked, onToggle, scopeSize,
                       checked, filtered, est, modelWarn, models, disabled,
                       openStep, onOpenStep, planBusy, planReady,
                       fixConfirmed, fixConfirmedCount }) {
  const anyWork = rows.some(r => picked.has(r.key) && r.planEst && r.planEst.count > 0);
  const head = (text, right) => React.createElement("div", {
    key: "h-" + text, className: "dim",
    style: { fontSize: 11, textTransform: "uppercase", letterSpacing: ".04em",
             padding: "0 0 6px", textAlign: right ? "right" : "left",
             borderBottom: "1px solid var(--border)" } }, text);
  return React.createElement("div", { className: "card card-pad-sm", style: { display: "flex", flexDirection: "column", gap: 11, borderLeft: "3px solid var(--c-primary)" } },

    React.createElement("div", { className: "row between row-wrap", style: { gap: 8 } },
      React.createElement("div", { className: "row", style: { gap: 9 } },
        React.createElement("span", { style: { width: 30, height: 30, borderRadius: 8, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-primary)", flex: "0 0 30px" } },
          React.createElement(Icon, { name: "zap", size: 17 })),
        React.createElement("div", null,
          React.createElement("div", { style: { fontWeight: 650, fontSize: 14, display: "flex", alignItems: "center" } }, TR("Перевести и проверить"),
            React.createElement(InfoTip, { title: TR("Что делает эта кнопка"), body: FULL_RUN_TIP })),
          React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
            TR("шаги идут по порядку, у каждого своя модель")))),
      React.createElement("span", { className: "dim", style: { fontSize: 11.5 } },
        TR("в работу пойдут ") + scopeSize + TR(" сегм.")
        + (checked > 0 ? TR(" · по галочкам") : filtered ? TR(" · по фильтру") : ""))),

    modelWarn && React.createElement("div", { style: { fontSize: 12.5, lineHeight: 1.5, color: "var(--c-warning)", background: "var(--bg-sunken)", padding: "8px 11px", borderRadius: 8 } },
      modelWarn),

    React.createElement("div", { style: { display: "grid", gridTemplateColumns: "minmax(170px,1fr) auto auto auto auto", columnGap: 12, alignItems: "center" } },
      head(TR("Шаг")), head(TR("Модель")), head(TR("Сегм."), true), head(TR("≈ цена"), true), head(" "),
      rows.map(r => StepRow({
        row: r, on: picked.has(r.key), onToggle, models, disabled,
        open: openStep === r.key, onOpen: onOpenStep }))),

    React.createElement(EstLine, { est }),
    React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: -6 } },
      planBusy ? TR("Считаем состав…")
        : !planReady ? TR("Состав прогона не получен от сервера — запуск вслепую не даём.")
        // Полностью это объяснено в подсказке у названия. Здесь коротко:
        // блок стоит в колонке, и абзац мелким текстом занимал в ней пять строк.
        : TR("Состав и смету посчитал сервер тем же кодом, который потом и работает.")),

    // Взведённое разрешение трогать заверенное человеком видно У КНОПКИ, а не
    // только в раскрытой строке ремонта. Иначе последствие — снятые отметки
    // «подтвердил человек» — наступало бы от нажатия, за которым на экране
    // ничего об этом не сказано.
    fixConfirmed && React.createElement("div", {
      style: { fontSize: 11.5, lineHeight: 1.5, padding: "7px 9px", borderRadius: "var(--r-md)",
               background: "var(--bg-sunken)", border: "1px solid var(--c-warning)",
               color: "var(--text-2)" } },
      React.createElement("b", { style: { color: "var(--c-warning)" } }, TR("Ремонт возьмёт и подтверждённые")),
      fixConfirmedCount ? " — " + fixConfirmedCount + TR(" заверенных сегментов с находками; ")
                        : TR(" — в выборке таких сейчас нет; "),
      TR("с исправленных снимется отметка «подтвердил человек». Выключается в строке «Ремонт».")),

    // Во время прогона цифры показывает полоса наверху — она залипающая и
    // видна всегда. Второй прогресс-бар здесь только повторял бы её и уезжал
    // за край экрана вместе с карточкой.
    running
      ? React.createElement("div", { className: "row between", style: { gap: 8, flexWrap: "wrap" } },
          React.createElement("span", { className: "muted", style: { fontSize: 12 } },
            TR("Идёт полный прогон — счёт по шагам на полосе наверху")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: onStop }, TR("Остановить")))
      : React.createElement(Btn, { variant: "primary", icon: "zap", onClick: onRun,
          disabled: disabled || !anyWork || !planReady },
          // «Всё уже сделано» и «ни один шаг не отмечен» — разные причины нулевой
          // работы, и молчать о разнице нельзя: сняли все галочки шагов — кнопка
          // выглядела бы как «весь проект готов», хотя работа просто не выбрана.
          !planReady ? TR("Считаем состав…")
            : picked.size === 0 ? TR("Отметьте хотя бы один шаг")
            : anyWork ? TR("Перевести и проверить") : TR("Всё уже сделано")));
}

/* Второй клик конвейера. Одобряет однозначные термины пачкой и тут же чинит
   ими сегменты. Состав сегментов не выбирается намеренно: пока термины не
   одобрены, неизвестно, какие сегменты с ними разойдутся — список считает
   сервер сразу после одобрения. */
function ApplyTermsCard({ running, onRun, onStop, disabled, preview, sources,
                          includeConfirmed, onIncludeConfirmed, confirmedCount,
                          orders, onOrders, pendingSegs, futileSegs,
                          impact, impactBusy, onImpactRefresh, onRetranslate,
                          onDrill, retEst, retRunning }) {
  const c = preview && preview.counts;
  // Состав «Перевести заново»: тот же выбор «трогать ли подтверждённые»,
  // что и у ремонта, — одна галочка на оба пути, состояние у них общее.
  const retTargets = impact ? (includeConfirmed ? impact.segments : impact.pending) : [];
  // Запрет области сервер присылает отдельным полем: он снимается ДО учёта
  // разрешения, поэтому тумблер не исчезает от того, что его включили.
  // Выводить его в браузере из allow_verified + humanOverride + cap_soft
  // значило бы держать второй источник правды рядом с AUTO_APPROVE_BY_DOMAIN.
  const banned = !!(preview && preview.policy && preview.policy.domainBanned);
  const ready = c ? (c.auto || 0) + (c.verified || 0) : 0;
  const dicts = (sources && sources.dictionaries) || [];
  const corpus = sources && sources.corpus;
  return React.createElement("div", { className: "card card-pad-sm", style: { display: "flex", flexDirection: "column", gap: 10, borderLeft: "3px solid var(--c-success)" } },

    React.createElement("div", { className: "row between row-wrap", style: { gap: 8 } },
      React.createElement("div", { className: "row", style: { gap: 9 } },
        React.createElement("span", { style: { width: 30, height: 30, borderRadius: 8, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-success)", flex: "0 0 30px" } },
          React.createElement(Icon, { name: "check", size: 17 })),
        React.createElement("div", null,
          React.createElement("div", { style: { fontWeight: 650, fontSize: 14, display: "flex", alignItems: "center" } }, TR("Одобрить и применить"),
            React.createElement(InfoTip, { title: TR("Что делает эта кнопка"),
              body: TR("Однозначные термины уходят в глоссарий пачкой, а затем сегменты чинятся по ним: расхождение с утверждённым термином — такая же находка ремонта, как потерянный термин или расхождение чисел.\n\nЧто считается однозначным: у термина ровно один вариант перевода; пара пришла из нескольких независимых сегментов, прошедших back-check и проверку терминов чисто; перевод встречается в текстах целевого языка.\n\nПриказом («use these exact translations») запись становится от человека, от трёх независимых чистых сегментов или от совпадения с ВЫВЕРЕННЫМ отраслевым справочником. У справочника есть уровень: краудсорсный (например выгрузка Wikidata) приказа в одиночку не даёт — он идёт подтверждающим голосом рядом с согласием сегментов и корпусом целевого языка. В медицине, фармацевтике и юриспруденции ни согласия сегментов, ни краудсорсного справочника для приказа НЕ хватает: там приказ даёт человек или выверенный справочник.\n\nЛюбую пачку можно откатить целиком в «Глоссарии».") })),
          React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
            TR("термины в глоссарий → ремонт по ним → перепроверка")))),
      React.createElement("span", { style: { fontVariantNumeric: "tabular-nums", fontWeight: 700, fontSize: 17, color: ready ? "var(--c-success)" : "var(--text-3)" } },
        ready)),

    // Чем проверялись термины. Покрытие по парам языков очень разное, и разницу
    // честнее назвать, чем дать пользователю обнаружить её на своих текстах.
    React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.55 } },
      TR("Проверяют: "),
      dicts.length
        ? dicts.map(d => d.label + " (" + d.terms
            + (d.tier === "verified" ? TR(", приказ") : TR(", голос")) + ")").join(" · ")
        : TR("справочников для этой пары языков нет"),
      corpus ? TR(" · корпус ") + corpus.label : TR(" · корпус недоступен"),
      preview && preview.corpusSkipped
        ? TR(" · сверх потолка не проверено: ") + preview.corpusSkipped : ""),

    // Цифра выше посчитана ДО обращения к корпусу: спрашивать его при каждом
    // открытии проекта — это минута ожидания на лимитах источника. При нажатии
    // он отработает, и часть кандидатов может отсеяться как отсутствующие
    // в целевом языке. Обещать больше, чем сделаем, нельзя.
    preview && (preview.corpusPending || preview.meaningPending) && React.createElement("div",
      { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
      TR("Это верхняя оценка: при нажатии термины пройдут ")
      + [preview.corpusPending && corpus ? TR("проверку по ") + corpus.label : null,
         preview.meaningPending ? TR("смысловую сверку судьёй (то же ли понятие)") : null]
        .filter(Boolean).join(TR(" и "))
      + TR(" — кальки и ложные друзья будут отклонены, а не записаны.")),

    c && c.skipped > 0 && React.createElement("div", { className: "dim", style: { fontSize: 12.5 } },
      TR("останется человеку: "), React.createElement("b", null, c.skipped),
      TR(" — разобрать в «Глоссарии»")),

    confirmedCount > 0 && React.createElement(Checkbox, {
      checked: !!includeConfirmed, onChange: onIncludeConfirmed },
      TR("Чинить и подтверждённые (") + confirmedCount + ")"),

    // Разрешение на приказы — только там, где область их запрещает, и только
    // на этот запуск (см. панель в «Знаниях»: то же правило, тот же откат).
    banned && React.createElement("div", { className: "col", style: { gap: 3 } },
      React.createElement(Checkbox, { checked: !!orders, onChange: onOrders },
        TR("Приказы по согласию сегментов")),
      React.createElement("div", { className: "dim", style: { fontSize: 11, lineHeight: 1.5 } },
        orders
          ? TR("Запрет области снят на этот запуск: согласие независимых чистых ")
            + TR("сегментов даст приказ. Каждый такой термин пройдёт смысловую ")
            + TR("сверку судьёй; пачка откатывается целиком в «Глоссарии».")
          : TR("Сейчас приказ в этой области даёт только человек или выверенный ")
            + TR("справочник — однозначные уходят подсказкой, которую модель ")
            + TR("вправе игнорировать."))),

    // Счёт — на полосе наверху, здесь только название текущей половины работы:
    // пока список сегментов не посчитан, идёт запись терминов в глоссарий.
    running
      ? React.createElement("div", { className: "row between", style: { gap: 8, flexWrap: "wrap" } },
          React.createElement("span", { className: "muted", style: { fontSize: 12 } },
            running.total ? TR("Применяем к сегментам…") : TR("Одобряем термины…")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: onStop }, TR("Остановить")))
      : React.createElement(Btn, { variant: "primary", icon: "check", onClick: onRun,
          // Одобрять нечего — это НЕ значит «работы нет»: расхождения с уже
          // утверждёнными терминами чинит та же задача, и это единственный
          // дешёвый путь. Запирая кнопку на нуле терминов, интерфейс оставлял
          // человеку только переперевод — вдвое дороже и без проверок.
          disabled: disabled || (!ready && !pendingSegs) },
          ready ? TR("Одобрить ") + ready + TR(" и применить")
            : pendingSegs ? TR("Применить к ") + pendingSegs + TR(" сегм.")
              : TR("Нечего применять")),
    !ready && pendingSegs > 0 && !running && React.createElement("div",
      { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
      TR("Новых однозначных терминов нет, но ") + pendingSegs + TR(" сегм. расходятся ")
      + TR("с уже утверждёнными — их починит ремонт.")),
    // Молчаливого отсева не бывает: если часть работы не пойдёт, сказать
    // почему — иначе человек жмёт кнопку по кругу и не понимает, отчего
    // список не пустеет.
    futileSegs > 0 && !running && React.createElement("div",
      { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5,
                                   cursor: onDrill && impact ? "pointer" : "default" },
        title: TR("Показать эти сегменты"),
        onClick: onDrill && impact ? () => onDrill(impact.futile || []) : null },
      TR("Ещё ") + futileSegs + TR(" сегм. расходятся, но ремонт их не возьмёт: тот же ")
      + TR("текст с теми же претензиями он уже проходил, и заход вернёт то же ")
      + TR("самое. Их правит человек, «Перевести заново» ниже — либо смените ")
      + TR("модель ремонта.")),

    /* ── Соответствие глоссарию ── Прежде отдельная карточка в третьей
       колонке; списки «По терминам» и начертание живут на вкладке «Анализ»,
       а здесь остались команды, которых больше нигде нет. Секция живёт
       и при нуле расхождений: пряча её, мы уносили бы «Пересчитать» —
       единственный способ убедиться, что ноль настоящий, а не остался
       с прошлого расчёта. */
    impact && React.createElement("div", { className: "col",
      style: { gap: 7, borderTop: "1px solid var(--border)", paddingTop: 9 } },
      React.createElement("div", { style: { fontSize: 12.5, fontWeight: 650, display: "flex", alignItems: "center" } },
        TR("Соответствие глоссарию"),
        React.createElement(InfoTip, { title: TR("Расхождения с одобренными терминами"),
          body: TR("Одобренный термин влияет только на будущие переводы — уже готовые сегменты сами не меняются. Здесь собраны все сегменты проекта, где термин есть в оригинале, а утверждённого варианта в переводе нет.\n\nСчитается только по проверенным записям глоссария: автоимпорт модель вправе игнорировать, требовать соответствия ему нельзя.\n\nДешёвый путь — ремонт по находкам (кнопка выше). «Перевести заново» переводит эти сегменты целиком, уже с новым термином в промпте, — дороже, зато берёт и застрявшие. Подтверждённые по умолчанию не трогаются; с галочкой они тоже переводятся заново, прежний текст сохраняется для отката, а статус становится «Требует проверки».\n\nРазбор по терминам и начертание — на вкладке «Анализ».") })),
      React.createElement("div", { className: "row between",
        style: { fontSize: 12.5, cursor: impact.segments.length && onDrill ? "pointer" : "default" },
        onClick: impact.segments.length && onDrill ? () => onDrill(impact.segments) : null,
        title: impact.segments.length ? TR("Показать эти сегменты") : undefined },
        React.createElement("span", { style: { fontWeight: 600,
          color: impact.segments.length ? "var(--c-warning)" : undefined } }, TR("Расходятся с глоссарием")),
        React.createElement("b", null, impact.segments.length)),
      impact.confirmed.length > 0 && React.createElement("div", { className: "row between",
        style: { fontSize: 12, cursor: onDrill ? "pointer" : "default" },
        onClick: onDrill ? () => onDrill(impact.confirmed) : null,
        title: TR("Показать эти сегменты") },
        React.createElement("span", { className: "dim" }, TR("из них подтверждено")),
        React.createElement("b", { className: "dim" }, impact.confirmed.length)),
      impact.terms.length === 0 && React.createElement("div",
        { className: "dim", style: { fontSize: 12, lineHeight: 1.55 } },
        TR("Все переводы соответствуют утверждённым терминам. Ноль бывает и после ")
        + TR("понижения записей сверкой смысла: требовать соответствия подсказке ")
        + TR("нельзя, поэтому она из расчёта уходит.")),
      retTargets.length > 0 && retEst && React.createElement(EstLine, { est: retEst }),
      retRunning
        ? React.createElement("div", { className: "dim", style: { fontSize: 12 } }, TR("Идёт перевод…"))
        : React.createElement("div", { className: "row between" },
            React.createElement("button", { className: "linklike", style: { fontSize: 12 },
              onClick: onImpactRefresh, disabled: impactBusy },
              impactBusy ? TR("Считаем…") : TR("Пересчитать")),
            React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat",
              onClick: onRetranslate, disabled: disabled || !retTargets.length },
              TR("Перевести заново (") + retTargets.length + ")"))));
}

// Блок «что прогонять»: группы по состоянию прошлых прогонов с количеством.
// Одна группа — выбирать не из чего, карточку не загромождаем.
function RunGroups({ title, tip, groups, pickedGroups, onToggleGroup }) {
  if (!groups || groups.length < 2) return null;
  return React.createElement("div", { className: "card", style: { padding: "9px 11px", background: "var(--bg-sunken)" } },
    React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, marginBottom: 6, display: "flex", alignItems: "center" } },
      title, React.createElement(InfoTip, { title: title, body: tip })),
    groups.map(g => React.createElement("div", { key: g.key, className: "row between", style: { padding: "2px 0" } },
      React.createElement(Checkbox, { checked: pickedGroups.has(g.key), onChange: () => onToggleGroup(g.key) }, g.label),
      React.createElement("b", { style: { fontSize: 12.5 } }, g.count))));
}

/* Итог «под ключ» рядом с кнопками, которые его меняют. Только показ:
   корзины пришли с сервера (/analysis → turnkey) — те же и тем же расчётом,
   что на вкладке «Анализ». Клик по строке фильтрует таблицу ниже, полный
   разбор и ручные команды — на самой вкладке. Долю считает tkPct из
   tab_preflight.jsx (все .jsx живут в одной глобальной области); запасной
   расчёт — для тестов, которые грузят только этот файл. */
function EditorAnalysisCard({ sum, onDrill, onOpen }) {
  const tk = sum.turnkey;
  const total = sum.total || 0;
  const ready = tk.ready || [], machine = tk.machine || [], human = tk.human || [];
  const pct = (n) => typeof tkPct === "function" ? tkPct(n, total)
    : (total ? Math.round(n / total * 100) + "%" : "0%");
  // Тернарник, а не `total && …`: при нуле выражение даёт ЧИСЛО 0, и React
  // честно его печатает (тот же урок, что у полосы в TurnkeySummary).
  const bar = (n, color) => (total > 0 && n > 0)
    ? React.createElement("div", { style: { width: (n / total * 100) + "%", background: color, height: "100%" } })
    : null;
  const row = (label, ids, color, hint) => React.createElement("div", {
    className: "row between",
    style: { fontSize: 12.5, gap: 8, cursor: ids.length && onDrill ? "pointer" : "default" },
    onClick: ids.length && onDrill ? () => onDrill(ids) : null,
    title: hint },
    React.createElement("span", { style: { fontWeight: 600, color: color } }, label),
    React.createElement("span", { className: "row", style: { gap: 8, alignItems: "baseline" } },
      React.createElement("b", { style: { fontVariantNumeric: "tabular-nums" } }, ids.length),
      React.createElement("span", { className: "dim", style: { fontSize: 11.5, minWidth: 40,
        textAlign: "right", fontVariantNumeric: "tabular-nums" } }, pct(ids.length))));
  return React.createElement("div", { className: "card card-pad-sm", style: { display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "row between row-wrap", style: { gap: 8 } },
      React.createElement("div", { className: "row", style: { gap: 9 } },
        React.createElement("span", { style: { width: 30, height: 30, borderRadius: 8, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-primary)", flex: "0 0 30px" } },
          React.createElement(Icon, { name: "target", size: 17 })),
        React.createElement("div", null,
          React.createElement("div", { style: { fontWeight: 650, fontSize: 14, display: "flex", alignItems: "center" } }, TR("Анализ"),
            React.createElement(InfoTip, { title: TR("Три корзины"),
              body: TR("Каждый сегмент проекта ровно в одной корзине, суммы сходятся с общим числом — считает сервер теми же правилами, что и сам прогон.\n\n«Готово к сдаче» — переведено, проверено, открытых вопросов нет.\n\n«Возьмёт ближайший прогон» — закроет кнопка «Перевести и проверить».\n\n«Нужно ваше решение» — то, что прогон не решает по построению: споры с глоссарием, заверенные сегменты с находками, откаченные правки. Команды — на вкладке «Анализ».\n\nЛюбая строка фильтрует таблицу ниже.") })),
          React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
            TR("что сейчас с переводом")))),
      React.createElement("span", { style: { fontVariantNumeric: "tabular-nums", fontWeight: 700, fontSize: 17,
        color: ready.length ? "var(--c-success)" : "var(--text-3)" } },
        pct(ready.length))),
    React.createElement("div", { style: { display: "flex", height: 10, borderRadius: 5,
      overflow: "hidden", background: "var(--bg-sunken)" } },
      bar(ready.length, "var(--c-success)"),
      bar(machine.length, "var(--c-primary)"),
      bar(human.length, "var(--c-warning)")),
    row(TR("Готово к сдаче"), ready, "var(--c-success)", TR("переведено и проверено, открытых вопросов нет")),
    row(TR("Возьмёт ближайший прогон"), machine, "var(--c-primary)", TR("перевод, проверки, судья и ремонт по находкам")),
    row(TR("Нужно ваше решение"), human, "var(--c-warning)", TR("прогон это не решит — состав и команды на вкладке «Анализ»")),
    (tk.confirmed || []).length > 0 && React.createElement("div", { className: "dim row between",
      style: { fontSize: 11.5, cursor: onDrill ? "pointer" : "default" },
      onClick: onDrill ? () => onDrill(tk.confirmed) : null,
      title: TR("входит в корзины выше") },
      React.createElement("span", null, TR("заверено вручную")),
      React.createElement("b", null, tk.confirmed.length)),
    React.createElement("div", { className: "row between", style: { gap: 8 } },
      React.createElement("span", { className: "dim", style: { fontSize: 11.5 } },
        ready.length + TR(" из ") + total + TR(" сегм. готово")),
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "target", onClick: onOpen },
        TR("Открыть «Анализ»"))));
}

function SegRow({ seg, selected, busy, checked, onCheck, onSelect, onTranslate, onConfirm, onRevert, models, hlSrc, hlTgt }) {
  const prov = providerOf(seg);
  const provText = providerLabel(prov, models);
  const revertable = seg.status === "confirmed" || seg.status === "failed";
  const actionCell = busy
    ? React.createElement("div", { style: { display: "grid", placeItems: "center" } }, React.createElement(Spinner, null))
    : seg.status === "new"
      ? React.createElement(IconBtn, { icon: "globe", label: TR("Перевести"), sm: true, onClick: onTranslate })
      : seg.status === "confirmed"
        ? React.createElement("button", { className: "status-cell-btn revertable", title: TR("Нажмите, чтобы снять подтверждение"), "aria-label": TR("Снять подтверждение"), onClick: onRevert },
            React.createElement(Icon, { name: "checkCircle", size: 18, style: { color: "var(--c-success)" } }))
        : seg.status === "failed"
          ? React.createElement("button", { className: "status-cell-btn revertable", title: TR("Нажмите, чтобы сбросить в «Новый»"), "aria-label": TR("Сбросить статус"), onClick: onRevert },
              React.createElement(Icon, { name: "close", size: 18, style: { color: "var(--c-error)" } }))
          : React.createElement(IconBtn, { icon: "check", label: TR("Подтвердить"), sm: true, onClick: onConfirm });
  // data-seg — якорь для прокрутки к сегменту зоны: искать строку по номеру
  // проще, чем тянуть ref через таблицу.
  return React.createElement("tr", { "data-seg": seg.id, className: "row-status-" + seg.status + (selected ? " selected" : "") + (checked ? " row-checked" : ""), onClick: onSelect },
    React.createElement("td", { style: { width: 36, textAlign: "center" }, onClick: (e) => e.stopPropagation() },
      React.createElement("input", { type: "checkbox", checked: !!checked, onChange: onCheck })),
    React.createElement("td", { className: "col-id" }, seg.id),
    React.createElement("td", { className: "src-cell" }, markHits(seg.source, hlSrc)),
    React.createElement("td", { className: seg.target ? "tgt-cell" : "tgt-cell tgt-empty" },
      seg.target ? markHits(seg.target, hlTgt) : TR("— не переведено —")),
    React.createElement("td", null,
      React.createElement(StatusBadge, { status: seg.status }),
      provText && React.createElement("div", {
        className: "dim",
        style: { fontSize: 10.5, marginTop: 3, whiteSpace: "nowrap", opacity: prov.exact ? 0.85 : 0.55 },
        title: prov.exact
          ? TR("Переведено: ") + provText
          : TR("Переведено предположительно через ") + provText + TR(" — сегмент переведён до того, как система начала записывать движок точно"),
      }, (prov.exact ? "" : "≈ ") + provText)),
    // Колонка проверок. Чипа TM здесь больше нет: tmScore писался единожды
    // нулём при импорте и не обновлялся ничем, то есть колонка показывала
    // красный ноль всем сегментам всех проектов всегда. Постоянный ложный
    // показатель хуже отсутствующего — по нему делают выводы о памяти
    // переводов, которых он не подтверждает. Реальные совпадения TM видны
    // в карточке сегмента (вкладка «TM»), где берутся из store.tm.
    React.createElement("td", null,
      // Процент соответствия обратного перевода: цифра + причина в подсказке
      seg.repair && seg.repair.applied && React.createElement("div", {
        style: { fontSize: 11, fontWeight: 700, marginTop: 4, whiteSpace: "nowrap", color: "var(--c-success)" },
        title: TR("Автоматически исправлено ") + (seg.repair.at || "")
          + TR("\nБыло: ") + (seg.repair.from || "")
          + TR("\nПричины: ") + (seg.repair.issues || []).map(TRS).join("; "),
      }, TR("✓ ремонт")),
      seg.termcheck && (seg.termcheck.findings || []).length > 0 && React.createElement("div", {
        style: { fontSize: 11, fontWeight: 700, marginTop: 4, whiteSpace: "nowrap",
                 color: seg.termcheck.severity === "critical" ? "var(--c-error)"
                   : seg.termcheck.severity === "major" ? "var(--c-warning)" : "var(--text-3)" },
        title: TR("Терминология: ") + seg.termcheck.findings.map(f =>
          f.tgt_term + (f.suggestion ? " → " + f.suggestion : "") + (f.why ? " (" + TRS(f.why) + ")" : "")).join("\n")
          + (seg.termcheck.stale ? TR("\n\nПеревод менялся после проверки — данные устарели.") : ""),
      }, (seg.termcheck.stale ? "≈ " : "") + TR("термин: ") + seg.termcheck.findings.length),
      seg.backcheck && seg.backcheck.score != null && React.createElement("div", {
        style: { fontSize: 11, fontWeight: 700, marginTop: 4, whiteSpace: "nowrap",
                 color: window.bcScoreColor(seg.backcheck.score) },
        title: TR("Соответствие обратного перевода: ") + seg.backcheck.score + "%"
          + ((seg.backcheck.reasons || []).length ? "\n" + seg.backcheck.reasons.map(TRS).join("; ") : "")
          + TR("\nОбратный перевод: ") + (seg.backcheck.back || ""),
      }, "↩ " + seg.backcheck.score + "%")),
    React.createElement("td", { onClick: (e) => e.stopPropagation() }, actionCell)
  );
}

function NoProject({ store }) {
  return React.createElement("div", { className: "page" },
    React.createElement(EmptyState, { icon: "folder",
      title: store.projects.length ? TR("Проект не выбран") : TR("Проектов пока нет"),
      sub: store.projects.length ? TR("Откройте существующий проект или импортируйте документ.")
                                 : TR("Начните с импорта .docx: документ разобьётся на сегменты, а перевод и проверки запустятся одной кнопкой."),
      action: React.createElement(Btn, { variant: "primary", icon: "upload", onClick: () => store.go("import") }, TR("К импорту")) }));
}
window.TabEditor = TabEditor;
