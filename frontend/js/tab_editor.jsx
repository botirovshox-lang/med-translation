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
/* Один источник ключей для панели «Анализа»: она читает и пишет ТЕ ЖЕ выборы
   моделей, что и карточки редактора. Свои литералы там завели бы второе
   хранилище того же выбора — модель, сменённая на одном экране, молча
   не доехала бы до другого. Имена параметров = имена полей run-plan. */
window.MODEL_LS = { model: GPT_MODEL_LS_KEY, bc_model: BC_MODEL_LS_KEY,
                    tc_model: TC_MODEL_LS_KEY, tcx_model: TCX_MODEL_LS_KEY,
                    rp_model: RP_MODEL_LS_KEY, judge_model: JUDGE_MODEL_LS_KEY };
const JOB_LABELS = { translate: "Перевод", backcheck: "Back-check", termcheck: "Проверка терминологии",
                     termaudit: "Сверка терминов моделью",
                     repair: "Автоматический ремонт", medical_qa: "Medical QA",
                     full: "Перевод и проверка", apply_terms: "Одобрение и применение" };

// Короткие имена шагов составного прогона. Одни и те же в таблице состава и
// в полосе прогресса: разойдись они — человек не свяжет галочку на полосе
// со строкой, галочками в которой он этот шаг и набирал.
const FULL_STEP_LABELS = { translate: "Перевод", backcheck: "Back-check", termcheck: "Термины",
                           termaudit: "Сверка терминов",
                           repair: "Ремонт", medical_qa: "Medical QA" };

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
    "Ориентировочно: ",
    React.createElement("b", { style: { color: "var(--text-2)" } },
      est.cost != null ? fmtCost(est.cost) : "—"),
    " · " + fmtDuration(est.seconds) + " на " + est.count + " сегм.");
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
// в медицинских текстах они пишутся вперемешку, и точный поиск иначе врёт.
const SEARCH_SCOPES = ["all", "src", "tgt"];
function normText(t) { return (t || "").toLowerCase().replace(/ё/g, "е"); }

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
function rpGroupKey(s) {
  const r = s.repair;
  if (!r) return "none";
  /* Заход, отменённый СБОЕМ перепроверки, сервер намеренно не засчитывает
     (source_hash не пишется), поэтому tried у него false. В «текст менялся»
     такие класть нельзя: текст как раз не менялся, не состоялась проверка. */
  if (r.retryable && !r.tried) return r.retryReason === "rules" ? "rules" : "failed";
  if (!r.tried) return "changed";
  return r.applied ? "applied" : "rejected";
}

/* Второй заход по тому же тексту даёт то же самое, поэтому группы уже
   чинившихся по умолчанию сняты. «failed» — не второй заход: там первый
   не состоялся, и сегмент ждёт своей очереди наравне с нетронутыми. */
function rpGroupDefault(key) {
  /* «rules» отмечена по умолчанию: прежний вердикт вынесен правилом, которого
     больше нет, а значит он ничего не говорит о нынешнем заходе. Это не второй
     заход по тем же правилам, ради которого группы «уже чинилось» и сняты. */
  return key === "none" || key === "changed" || key === "failed" || key === "rules";
}

/* ── Составной прогон: весь конвейер одной кнопкой ──────────────────────
   Порядок ЗДЕСЬ повторяет FULL_RUN_STEPS на сервере и обязан ему совпадать:
   карточка показывает, что произойдёт, а произойдёт то, что решил сервер.
   Ремонт идёт перед Medical QA — проверка описывает окончательный текст,
   а не тот, который через шаг перепишут.

   Состав сегментов больше не считается здесь: его отдаёт /run-plan тем же
   кодом, который потом и работает. Раньше браузер считал своими правилами,
   сервер отбирал своими, и снятая галочка уменьшала смету, но не работу. */
// Названия и подписи шагов живут в строках таблицы (fullRunRows) — здесь
// только порядок, и он обязан совпадать с FULL_RUN_STEPS на сервере: карточка
// показывает, что произойдёт, а произойдёт то, что решил сервер.
const FULL_STEP_KEYS = ["translate", "backcheck", "termcheck", "termaudit",
                        "repair", "medical_qa"];

function fmtDuration(sec) {
  if (sec < 90) return Math.round(sec) + " с";
  if (sec < 5400) return Math.round(sec / 60) + " мин";
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return h + " ч" + (m ? " " + m + " мин" : "");
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
  const [impact, setImpact] = useState(null);     // сегменты, не соответствующие одобренным терминам
  const [impactBusy, setImpactBusy] = useState(false);
  const [impactConfirmed, setImpactConfirmed] = useState(false);  // трогать ли подтверждённые
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
          toast.warning("Результат прогона не забран",
            "Сервер не отдал проект " + PULL_TRIES + " раза подряд. Обновите страницу: "
            + "иначе в таблице останутся статусы, какими они были до прогона.");
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
      if (byHand) toast.error("Пересчёт не выполнен", "Сервер не ответил.");
      return;
    }
    setImpact(res);
    if (!byHand) return;
    const now = res.segments.length;
    if (before === null || before === now)
      toast.info("Пересчитано: " + now, "Столько сегментов расходится с глоссарием.");
    else
      toast.success("Пересчитано: было " + before + ", стало " + now,
        now < before ? "Расхождений стало меньше на " + (before - now)
                     : "Расхождений стало больше на " + (now - before));
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
    project && project.id, gptModel, bcModel, tcModel, tcxModel, rpModel, bcJudge,
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
      tcx_model: tcxModel,
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
        toast.info("Подтянуты новые сегменты",
          "их завели мимо этой вкладки: " + added + ". Теперь они видны в таблице и фильтрах.");
      } else if (added < 0) {
        /* Сегментов стало МЕНЬШЕ — например, надпись на картинке пометили
           надпечаткой из другого окна. Пропавшие с экрана строки выглядят
           благополучнее, чем есть, поэтому число называется вслух. */
        toast.info("Сегментов стало меньше",
          "их убрали мимо этой вкладки: " + (-added) + ".");
      } else if (srvSig !== null && srvSig !== mySig) {
        /* Молчать нельзя: статусы в таблице сейчас поменяются сами собой,
           и без объяснения это выглядит как сбой. */
        toast.info("Таблица показывала устаревшее",
          "на сервере статусы сегментов уже другие — подтянули свежие.");
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
      toast.warning("Номер сегмента", "Введите номер сегмента — например 128.");
      return;
    }
    const idx = project.segments.findIndex(s => s.id === n);
    if (idx < 0) {
      const ids = project.segments.map(s => s.id);
      toast.warning("Сегмента #" + n + " в проекте нет",
        ids.length ? "Номера идут от " + Math.min.apply(null, ids) + " до " + Math.max.apply(null, ids) + "."
                   : "В проекте нет сегментов.");
      return;
    }
    const dropped = [];
    if (filter !== "all") { setFilter("all"); dropped.push("фильтр статуса"); }
    if (riskFilter !== "all") { setRiskFilter("all"); dropped.push("фильтр риска"); }
    if (originFilter !== "all") { setOriginFilter("all"); dropped.push("фильтр источника"); }
    if (query) { setQuery(""); dropped.push("поиск"); }
    if (activeFilter) { window._mcat_sf = null; store.setSegmentFilter(null); dropped.push("выборку из анализа"); }
    jumpRef.current = true;
    setZone(n);
    setSelId(n);
    setJump(String(n));
    if (dropped.length) toast.info("Зона сегмента #" + n,
      "Снял " + dropped.join(", ") + ": под ним соседних сегментов не видно.");
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
      const label = gptModelInfo ? gptModelInfo.label : "модель";
      const src = result.source === "TM" ? " (из TM)" : result.usedRealApi ? "" : " (демо)";
      toast.success("Сегмент переведён", label + " · сегмент #" + seg.id + src);
    } else {
      // НЕ подставляем демо-заглушку в медицинский перевод: сегмент остаётся как был,
      // пользователь видит честную ошибку и может повторить попытку.
      toast.error("Перевод не выполнен", "Сегмент #" + seg.id + " не изменён. Сервер недоступен или движки перевода вернули ошибку — попробуйте ещё раз.");
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
      if (n === 0) toast.info("Проверка QA завершена", "Сегмент #" + seg.id + " — замечаний не найдено.");
      else toast.warning("QA: " + n + " замечан.", "Сегмент #" + seg.id);
    } else {
      // Честная ошибка вместо ложного "замечаний не найдено" при недоступном сервере
      toast.error("QA не выполнен", "Сегмент #" + seg.id + ": сервер недоступен, статус не изменён.");
    }
    clearBusy(seg.id);
  };

  const doMedicalQA = async (seg) => {
    if (busy[seg.id]) return;
    if (!seg.target) {
      toast.warning("Medical QA", "Сначала переведите сегмент #" + seg.id + ".");
      return;
    }
    setSegBusy(seg.id, "medical_qa");
    let result = null;
    if (window.API) {
      result = await window.API.safeCall(() => window.API.medicalQA(project.id, seg.id));
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
      const title = color === "red" ? "Medical QA: нужен review" : color === "yellow" ? "Medical QA: есть правки" : "Medical QA: зелёный";
      const msg = "Сегмент #" + seg.id + " · risk " + color.toUpperCase() + " · score " + (score == null ? 0 : score) + " · issues: " + n;
      (color === "red" ? toast.warning : color === "yellow" ? toast.warning : toast.success)(title, msg);
    } else {
      toast.error("Medical QA", result && result.error ? result.error : "Не удалось выполнить проверку.");
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
    // медицинском инструменте пугает сильнее, чем отсутствие обучения.
    const learned = [];
    if (res && res.tm === "updated") learned.push("память переводов обновлена (прежний вариант заменён)");
    else if (res && res.tm === "added") learned.push("пара добавлена в память переводов");
    const cands = (res && res.termCandidates) || [];
    if (cands.length) learned.push(cands.length + " терминов ждут решения в «Глоссарий → Кандидаты»");
    toast.success("Подтверждено", "Сегмент #" + seg.id + (learned.length ? ". " + learned.join("; ") + "." : "."));
    const prop = res && res.propagate;
    if (prop && (prop.pending.length || prop.confirmed.length)) setPropagateAsk({ seg, prop });
  };

  // Распространение подтверждённого перевода на сегменты с тем же исходником.
  // Только по явному согласию: подтверждённые чужой рукой сегменты по умолчанию
  // не трогаем — так же ведут себя Phrase и Trados.
  const doPropagate = async (includeConfirmed) => {
    if (!propagateAsk) return;
    const { seg } = propagateAsk;
    const res = window.API ? await window.API.safeCall(() => window.API.propagate(project.id, seg.id, null, includeConfirmed)) : null;
    setPropagateAsk(null);
    if (!res || !res.ok) { toast.error("Не удалось разослать перевод", "Сервер не ответил."); return; }
    (res.changed || []).forEach(id => store.updateSegment(project.id, id, {
      target: seg.target, status: "translated", provider: "tm", route: "EXACT_TM" }));
    toast.success("Перевод разослан", res.changed.length + " сегментов обновлено"
      + (res.skippedConfirmed && res.skippedConfirmed.length
          ? "; подтверждённых пропущено: " + res.skippedConfirmed.length : "") + ".");
  };

  const doRevert = async (seg) => {
    if (seg.status === "confirmed") { setRevertTarget(seg); return; }
    if (seg.status === "failed") {
      if (window.API) await window.API.safeCall(() => window.API.revert(project.id, seg.id));
      store.updateSegment(project.id, seg.id, { status: "new", target: "" });
      toast.info("Статус сброшен", "Сегмент #" + seg.id + " возвращён в «Новый».");
    }
  };

  const confirmRevert = async () => {
    const seg = revertTarget; setRevertTarget(null);
    if (window.API) await window.API.safeCall(() => window.API.revert(project.id, seg.id));
    store.updateSegment(project.id, seg.id, { status: "translated" });
    toast.warning("Подтверждение снято", "Сегмент #" + seg.id + " возвращён в «Переведён».");
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
      const label = (p ? ((p.exact ? "" : "≈ ") + providerLabel(p, gptModels)) : "ещё не переведён")
        + (confirmed ? " — подтверждён человеком" : "");
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
    key === "none" ? "ещё не проверялся"
      : key === "stale" ? "перевод изменился после проверки"
      : key === "self" ? "проверял тот, кто переводил — это не проверка"
      : key === "nojudge" ? "проверено без судьи"
      : key === "unknown" ? "проверено (модель неизвестна)"
      : "проверено: " + (providerLabel({ id: key, exact: true }, gptModels) || key);

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
    if (!targets.length) { toast.warning("Нет подходящих сегментов", "Все сегменты уже переведены или не подходят под фильтр."); return; }
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
      "Все подходящие сегменты уже переведены.",
      estimateRun("translate", targets, gptModelInfo));
  };

  // ── Прогоны ─────────────────────────────────────────────────────
  // Порции крутит сервер (см. фоновые прогоны в main.py). Браузер ставит задачу
  // и опрашивает статус: закрытая вкладка больше не обрывает работу, а вернувшись
  // на страницу, пользователь видит прогресс с того места, где тот сейчас есть.
  // Возвращает поставленную задачу (или null): по её id составной прогон
  // запоминает состав шагов — без него полосе прогресса неоткуда взять остаток.
  const startJob = async (kind, targets, params, emptyMsg, est) => {
    if (batchRun) { toast.warning("Прогон уже идёт", "Дождитесь окончания или остановите текущий."); return null; }
    if (!targets.length) { toast.warning("Нечего запускать", emptyMsg); return null; }
    if (!window.API) return null;
    // Смету отдаём серверу вместе с задачей. Не ради сервера: он её не читает
    // и работу по ней не меняет. Ради того, чтобы рядом с фактическим расходом
    // лежало то самое число, которое человек видел под кнопкой, — врозь они
    // не сравниваются, а без сравнения смету не на чем поправить.
    const withEst = (est == null || est.cost == null) ? params
      : Object.assign({}, params, { est_cost: est.cost });
    const res = await window.API.safeCall(() => window.API.createJob(project.id, kind, targets.map(s => s.id), withEst));
    if (!res || !res.ok) { toast.error("Не удалось запустить", "Сервер не принял задачу."); return null; }
    setJob(res.job);
    toast.info(JOB_LABELS[kind] + ": запущено", targets.length + " сегментов. Можно закрыть вкладку — прогон идёт на сервере.");
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
      : ratio >= 1.15 ? " — смета выше факта в " + ratio.toFixed(1) + " раза"
      : ratio <= 0.87 ? " — смета НИЖЕ факта в " + (1 / ratio).toFixed(1) + " раза"
      : "";
    const costMsg = !sp ? ""
      : " · потрачено " + fmtCost(sp.cost)
        + (sp.est != null ? " при смете " + fmtCost(sp.est) + ratioMsg : "")
        + (sp.unpriced ? " · вызовов по неизвестной цене: " + sp.unpriced : "");
    const errMsg = c.errors ? " · ошибок: " + c.errors : "";
    // Работа, ушедшая в никуда. Ноль — норма и в отчёте не появляется;
    // не ноль человек должен увидеть там же, где итог, а не в журнале сервера.
    const lossMsg = (c.desync ? " · у " + c.desync + " сегментов текст разошёлся с записью о ремонте" : "")
      + (c.terms_dropped ? " · кандидатов в глоссарий выброшено (очередь полна): " + c.terms_dropped : "");
    const dupMsg = c.duplicates ? " · повторов зачтено без вызова: " + c.duplicates : "";
    if (j.status === "error") {
      // У «Одобрить и применить» глоссарий меняется ДО сегментов. Оборвался
      // ремонт — термины уже записаны, и молчать об этом нельзя: человек должен
      // знать, что откатывать, если результат его не устроил.
      const glossNote = (j.kind === "apply_terms" && c.termsApproved)
        ? " Термины (" + c.termsApproved + ") уже в глоссарии — пачку можно откатить в «Глоссарии»." : "";
      toast.error(name + ": прогон прерван",
        j.done + " из " + j.total + " обработано и сохранено. " + (j.error || "") + glossNote + costMsg);
      return;
    }
    if (j.status === "stopped") {
      toast.warning(name + ": остановлено", j.done + " из " + j.total + " обработано и сохранено." + errMsg + costMsg);
      return;
    }
    if (j.kind === "apply_terms") {
      const t = c.termsApproved || 0;
      toast.success("Одобрено и применено",
        t + " терминов в глоссарий (приказом: " + (c.termsVerified || 0) + ")"
        + (c.termsRejected ? " · отклонено по смыслу: " + c.termsRejected : "")
        + " · сегментов исправлено: " + (c.applied || 0)
        + (c.reverted ? " · откачено: " + c.reverted : "")
        + (c.skipped_confirmed ? " · подтверждённых не тронуто: " + c.skipped_confirmed : "")
        + errMsg + lossMsg + costMsg + " · откатить пачку можно в «Глоссарии»");
      return;
    }
    if (j.kind === "full") {
      // Отчитываемся по шагам: «обработано 2670» ничего не говорит о том,
      // что именно произошло, а прогон стоил денег на каждом шаге.
      const part = [
        c.translate ? "переведено " + c.translate : null,
        c.backcheck ? "back-check " + c.backcheck : null,
        c.termcheck ? "термины " + c.termcheck : null,
        // Сверка терминов: показываем не «сколько сегментов прошло», а что
        // она ОТВЕТИЛА — снятые претензии и найденные неверные передачи.
        // Число пройденных сегментов тут ни о чём не говорит: в большинстве
        // из них сверять нечего.
        (c.settled || c.wrong)
          ? "сверка терминов: снято " + (c.settled || 0) + ", неверных " + (c.wrong || 0)
          : (c.termaudit ? "сверка терминов " + c.termaudit : null),
        c.medical_qa ? "Medical QA " + c.medical_qa : null,
        c.applied ? "исправлено " + c.applied : null,
      ].filter(Boolean).join(" · ") || "нового ничего не потребовалось";
      const blockedMsg = c.step_skips ? " · шаги пропускались (нет ключа или модуля)" : "";
      const skipConfMsg = c.skipped_confirmed ? " · подтверждённых не тронуто: " + c.skipped_confirmed : "";
      toast.success("Перевод и проверка завершены",
        j.done + " сегментов пройдено · " + part + dupMsg + skipConfMsg + blockedMsg + errMsg
        + (c.flagged ? " · замечания в " + c.flagged : "") + lossMsg + costMsg);
      return;
    }
    if (j.kind === "translate") {
      const tmMsg = c.tm_hits ? " · из TM без вызова: " + c.tm_hits : "";
      // Пропущенные подтверждённые называем вслух: иначе «переведено 0» выглядит
      // как поломка, хотя сервер просто не тронул заверенное человеком.
      const skipMsg = c.skipped_confirmed ? " · пропущено подтверждённых: " + c.skipped_confirmed : "";
      toast.success("Перевод завершён", j.done + " сегментов переведено" + tmMsg + dupMsg + skipMsg + errMsg + costMsg);
    } else if (j.kind === "termcheck") {
      const skipMsg = c.skipped_trivial ? " · без вызова модели: " + c.skipped_trivial : "";
      if (c.flagged) toast.warning("Проверка терминологии завершена",
        "Замечания в " + c.flagged + " из " + j.done + " сегментов" + dupMsg + skipMsg + errMsg + costMsg
        + " · предложения замены — в «Глоссарий → Кандидаты»");
      else toast.success("Проверка терминологии завершена", j.done + " сегментов без замечаний" + dupMsg + skipMsg + errMsg + costMsg);
    } else if (j.kind === "repair") {
      const revMsg = c.reverted ? " · откачено (не стало лучше): " + c.reverted : "";
      if (c.applied) toast.success("Ремонт завершён",
        "Исправлено " + c.applied + " сегментов" + revMsg + errMsg + lossMsg + costMsg + " · статус «Требует проверки», подтвердите вручную");
      else toast.warning("Ничего не исправлено", "Ни один вариант не улучшил оценку — все откачены." + errMsg + costMsg);
    } else if (j.kind === "backcheck") {
      toast.success("Back-check завершён", j.done + " сегментов проверено" + dupMsg + errMsg + costMsg + " · разбивка в Анализе");
    } else {
      toast.success(name + " завершён", j.done + " сегментов обработано" + errMsg);
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
      "Все переводы уже соответствуют одобренным терминам.");
  };

  const stopJob = async () => {
    if (!job || !window.API || job.stopping) return;
    setJob(j => (j ? { ...j, stopping: true } : j));   // отклик сразу, не дожидаясь опроса
    const res = await window.API.safeCall(() => window.API.stopJob(job.id));
    if (!res || !res.ok) {
      setJob(j => (j ? { ...j, stopping: false } : j));
      toast.error("Не удалось остановить", "Сервер не ответил — попробуйте ещё раз.");
      return;
    }
    toast.info("Останавливаем", "Текущий сегмент досчитается и сохранится, дальше прогон не пойдёт.");
  };

  const runBackcheckBatch = () => {
    // skip_cached выключен: состав уже отобран галочками «Что проверять»,
    // иначе сервер вырезал бы из порции ровно то, что попросили перепроверить.
    const targets = project.segments.filter(s => backcheckable(s, currentIdSet));
    startJob("backcheck", targets,
      { model: bcModel || null, use_judge: bcJudge, judge_model: judgeModel || null, skip_cached: false },
      bcSkipConfirmed
        ? "В выборке нет непроверенных сегментов, кроме подтверждённых, а их вы просили пропускать."
        : "В выборке нет непроверенных сегментов. Отметьте нужные группы в «Что проверять».",
      estimateRun("backcheck", targets, bcModelInfo, { judge: bcJudge, judgeModel: judgeModelInfo }));
  };

  const runTermcheckBatch = () => {
    const targets = project.segments.filter(s => termcheckable(s, currentIdSet));
    startJob("termcheck", targets,
      { model: tcModel || null, skip_cached: false },
      "Всё в выборке уже проверено этой моделью. Отметьте нужные группы в «Что проверять», чтобы прогнать заново.",
      estimateRun("termcheck", targets, tcModelInfo));
  };

  const runTermAudit = () => {
    // Список берём из серверного разбора, а не считаем сами: приказные термины
    // сегмента считает `_verified_hits`, и повторить его в браузере нечем.
    const plan = stepPlan("termaudit");
    const ids = new Set((plan && plan.ids) || []);
    const targets = project.segments.filter(s => ids.has(s.id));
    startJob("termaudit", targets,
      { model: tcxModel || null },
      "Сверять нечего: в выборке нет сегментов с утверждёнными терминами, "
      + "либо все уже сверены этим переводом.",
      estimateRun("termaudit", targets, tcxModelInfo));
  };

  const runRepairBatch = () => {
    const targets = project.segments.filter(s => repairable(s, currentIdSet));
    startJob("repair", targets,
      { model: rpModel || null, bc_model: bcModel || null, tc_model: tcModel || null,
        use_judge: bcJudge, judge_model: judgeModel || null, retry: repairRetry(),
        include_confirmed: rpFixConfirmed },
      rpGroups.length
        ? "Все сегменты с находками уже проходили ремонт. Отметьте нужные группы в «Что чинить»."
        : "Нет сегментов с проверяемыми находками. Сначала прогоните back-check или проверку терминологии.",
      estimateRun("repair", targets, rpModelInfo, { recheckModel: bcModelInfo }));
  };

  const runMedicalQABatch = () => {
    const idSet = currentIdSet;
    const targets = project.segments.filter(s =>
      s.target && s.target.trim() &&
      ["translated", "qa", "review", "confirmed"].includes(s.status) &&
      (!idSet || idSet.has(s.id)));
    startJob("medical_qa", targets,
      // Модель обратного перевода — та же, что у back-check. Своей у Medical QA
      // нет: правила детерминированные, вызов нужен только там, где готового
      // обратного перевода не осталось.
      { bc_model: bcModel }, "Нет переведённых сегментов для пакетной проверки.",
      // Платит она только за те сегменты, у которых своего обратного перевода
      // нет: остальным его отдал back-check. Тот же фильтр, что и в soloEst.
      estimateRun("medical_qa",
        targets.filter(s => !(s.backcheck && !s.backcheck.stale && s.backcheck.back)), bcModelInfo));
  };

  // Подписи с реальными языками проекта: "Оригинал (RU)" / "Перевод (EN)"
  const scopeOpts = [
    ["all", "Везде"],
    ["src", "Оригинал (" + project.src + ")"],
    ["tgt", "Перевод (" + project.tgt + ")"],
  ];
  const searchPlaceholder = scope === "src" ? "Поиск по оригиналу (" + project.src + ")…"
    : scope === "tgt" ? "Поиск по переводу (" + project.tgt + ")…"
    : "Поиск по оригиналу и переводу…";

  // ── Проверка терминологии: группы «что уже прогонялось» ──────────
  // Ключ разделяет не только «проверено/нет», но и «с замечаниями/без»:
  // после правок обычно нужно перепрогнать именно те, где замечания были.
  const tcCandidate = (s, idSet) => !!(s.target && s.target.trim()) && (!idSet || idSet.has(s.id));

  const tcGroupLabel = (key) => {
    if (key === "none") return "ещё не проверялся";
    if (key === "stale") return "перевод изменился после проверки";
    if (key === "skip") return "нечего проверять (без вызова модели)";
    const [kind, mdl] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
    const name = mdl === "unknown" ? "модель неизвестна" : (providerLabel({ id: mdl, exact: true }, gptModels) || mdl);
    return (kind === "hit" ? "проверено, есть замечания: " : "проверено, замечаний нет: ") + name;
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
    key === "none" ? "ремонт не запускался"
      : key === "changed" ? "текст менялся после прошлого ремонта"
      : key === "failed" ? "заход не состоялся — сбой перепроверки"
      : key === "rules" ? "правило отмены изменилось — прежний вердикт устарел"
      : key === "applied" ? "уже чинилось, замечания остались"
      : "правка была откачена (не стало лучше)";

  const rpGroups = (() => {
    const order = { none: 0, changed: 1, failed: 2, rules: 3, applied: 4, rejected: 5 };
    const by = new Map();
    project.segments.forEach(s => {
      if (!rpCandidate(s, currentIdSet)) return;
      const key = rpGroupKey(s);
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
    const key = rpGroupKey(s);
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
      pickedFull.has("translate") && estimateRun("translate", fullStepTargets.translate, gptModelInfo),
      pickedFull.has("backcheck") && estimateRun("backcheck", fullStepTargets.backcheck, bcModelInfo,
        { judge: bcJudge, judgeModel: judgeModelInfo }),
      pickedFull.has("termcheck") && estimateRun("termcheck", fullStepTargets.termcheck,
        gptModels.find(m => m.id === tcModel) || null),
      // Сверка терминов моделью. Без неё смета главной кнопки была занижена
      // на четверть: шаг по умолчанию включён, работу делает, а цены не имел —
      // ровно то молчание, от которого этот блок и заведён. Заодно это число
      // уходит в историю расхода как est_cost, по которому калибруется смета.
      pickedFull.has("termaudit") && estimateRun("termaudit", fullStepTargets.termaudit,
        tcxModelInfo),
      // Medical QA платит только там, где готового обратного перевода нет:
      // остальным его отдаёт back-check. И платит она по цене back-check —
      // модель обратного перевода у них теперь общая.
      pickedFull.has("medical_qa") && estimateRun("medical_qa",
        fullStepTargets.medical_qa.filter(s => !(s.backcheck && !s.backcheck.stale && s.backcheck.back)),
        bcModelInfo),
      pickedFull.has("repair") && estimateRun("repair", fullStepTargets.repair,
        gptModels.find(m => m.id === rpModel) || null, { recheckModel: bcModelInfo }),
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
  const tcModelInfo = gptModels.find(m => m.id === tcModel) || null;
  const rpModelInfo = gptModels.find(m => m.id === rpModel) || null;
  const stepPlan = (k) => planByStep[k] || null;
  const planEstOf = (k, model, opts) => estimateRun(k, fullStepTargets[k] || [], model, opts);

  const fullRunRows = [
    {
      key: "translate", label: FULL_STEP_LABELS.translate, hint: "только те, что ещё не переведены",
      modelId: gptModel, onModel: pickGptModel, plan: stepPlan("translate"),
      planEst: planEstOf("translate", gptModelInfo),
      soloEst: estimateRun("translate", transSolo.targets, gptModelInfo),
      onSolo: askRunBatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "translate"
        && !(job && job.params && job.params.via === "impact") ? batchRun : null,
      soloNote: !retranslate
        ? "Берёт только сегменты со статусом «Новый». Включите «Переводить заново», чтобы перегнать уже переведённое."
        : rtFixConfirmed
          ? "Перегоняет выбранные заново, включая подтверждённые человеком — с них снимется отметка «подтвердил человек». Точное совпадение с памятью переводов не подставляется, прежний перевод перезаписывается."
          : "Перегоняет выбранные заново. Подтверждённые не трогаются, точное совпадение с памятью переводов не подставляется, прежний перевод перезаписывается.",
      options: React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
        React.createElement("div", { className: "row between", style: { gap: 12, flexWrap: "wrap" } },
          React.createElement("div", null,
            React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600 } }, "Переводить заново уже переведённые"),
            React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
              (currentIdSet ? "Применится к текущей выборке"
                            : "Применится ко всему проекту — сузить можно галочками в таблице или фильтром из Анализа"))),
          React.createElement(Switch, { on: retranslate, label: "Переводить заново",
            onClick: () => setRetranslate(v => !v) })),
        // Подтверждённые — отдельная, более дорогая по последствиям галочка:
        // без неё их вообще не видно в разбивке ниже, и это не баг, а тот же
        // предохранитель, что и у ремонта («чинить подтверждённые»).
        retranslate && React.createElement("div", { className: "row between", style: { gap: 12 } },
          React.createElement("div", { style: { fontSize: 12.5 } }, "Переводить и подтверждённые человеком",
            React.createElement("span", { className: "dim", style: { fontSize: 11.5, display: "block" } },
              confirmedInScope + " в выборке; со снятых будет снята отметка «подтвердил человек»")),
          React.createElement(Switch, { on: rtFixConfirmed, label: "Переводить подтверждённые",
            onClick: () => setRtFixConfirmed(v => !v) })),
        retranslate && groupTable("Сейчас переведено через — отметьте, что перевести заново:",
          providerGroups.map(g => ({ key: g.key, count: g.count,
            label: g.label + (g.exact ? "" : " (определено по маршруту)") })),
          pickedProviders, toggleProvider,
          rtFixConfirmed ? "В выборке нет ни одного переведённого сегмента."
                         : "В выборке нет сегментов для повторного перевода (все подтверждены).")),
    },
    {
      key: "backcheck", label: FULL_STEP_LABELS.backcheck, hint: "обратный перевод другой моделью",
      modelId: bcModel, onModel: pickBcModel, plan: stepPlan("backcheck"),
      planEst: planEstOf("backcheck", bcModelInfo, { judge: bcJudge, judgeModel: judgeModelInfo }),
      soloEst: estimateRun("backcheck", project.segments.filter(s => backcheckable(s, currentIdSet)),
        bcModelInfo, { judge: bcJudge, judgeModel: judgeModelInfo }),
      onSolo: runBackcheckBatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "backcheck" ? batchRun : null,
      options: React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
        React.createElement("div", { className: "row between", style: { gap: 12, flexWrap: "wrap" } },
          React.createElement("div", null,
            React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, display: "flex", alignItems: "center" } },
              "Судья для средней зоны",
              React.createElement(InfoTip, { title: "Когда зовут судью",
                body: "Балл " + judgeZone[0] + "–" + judgeZone[1] + "% — зона, где лексика уже не отвечает, а смысл ещё под вопросом. Наверху и внизу шкалы решение принято детерминированными проверками, и платить за подтверждение очевидного незачем. При жёсткой находке (числа, единицы, отрицание) судья тоже не вызывается: отменить её он не может."
                  + "\n\nИсключение — короткий оригинал (меньше " + bcMinStems + " содержательных слов). Мера, по которой считается балл, на таком отрезке даёт только 0 или 100%, и любой синоним в обратном переводе роняет его в ноль при верном переводе: «Фтизиатрия → Phthisiology → Фтизиология». Ноль здесь значит «нечем измерить», поэтому низ зоны для таких сегментов открыт до нуля. Обратный перевод при этом берётся готовый — платим только за судью." })),
            React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
              "балл " + judgeZone[0] + "–" + judgeZone[1] + "%, а на оригиналах короче " + bcMinStems + " слов — от 0")),
          React.createElement("div", { className: "row", style: { gap: 8 } },
            bcJudge && React.createElement(Select, { value: judgeModel || "", disabled: !!job,
              onChange: (e) => pickJudgeModel(e.target.value), style: { fontSize: 12.5, maxWidth: 170 } },
              gptModels.map(m => React.createElement("option", { key: m.id, value: m.id }, m.label))),
            React.createElement(Switch, { on: bcJudge, label: "Судья", onClick: () => setBcJudge(v => !v) }))),
        React.createElement("div", { className: "row between", style: { gap: 12 } },
          React.createElement("div", { style: { fontSize: 12.5 } }, "Пропускать подтверждённые человеком",
            React.createElement("span", { className: "dim", style: { fontSize: 11.5, display: "block" } },
              confirmedInScope + " в выборке")),
          React.createElement(Switch, { on: bcSkipConfirmed, label: "Пропускать подтверждённые",
            onClick: toggleBcSkipConfirmed })),
        groupTable("Что проверять отдельным прогоном:", bcGroups, pickedBcGroups, toggleBcGroup,
          "В выборке нечего проверять.")),
    },
    {
      key: "termcheck", label: FULL_STEP_LABELS.termcheck, hint: "третья модель смотрит только на результат",
      modelId: tcModel, onModel: pickTcModel, plan: stepPlan("termcheck"),
      planEst: planEstOf("termcheck", tcModelInfo),
      soloEst: estimateRun("termcheck", project.segments.filter(s => termcheckable(s, currentIdSet)), tcModelInfo),
      onSolo: runTermcheckBatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "termcheck" ? batchRun : null,
      options: groupTable("Что проверять отдельным прогоном:", tcGroups, pickedTcGroups, toggleTcGroup,
        "В выборке нечего проверять."),
    },
    {
      key: "termaudit", label: FULL_STEP_LABELS.termaudit,
      hint: "модель смотрит термин В РЯДУ соседей — то, чего морфология не умеет",
      modelId: tcxModel, onModel: pickTcxModel, plan: stepPlan("termaudit"),
      planEst: planEstOf("termaudit", tcxModelInfo),
      // Состав ОБЕИХ кнопок берём у сервера: приказные термины сегмента
      // браузер не считает и считать не должен — повтори мы этот расчёт,
      // под соседними кнопками встали бы разные числа (замер на боевом
      // проекте: 713 против 2711, разница в 3.8 раза).
      soloEst: planEstOf("termaudit", tcxModelInfo),
      onSolo: runTermAudit, onStop: stopJob,
      running: batchRun && batchRun.engine === "termaudit" ? batchRun : null,
      soloNote: "Один вызов на сегмент, сколько бы утверждённых терминов в нём "
        + "ни было. Вердикт «передан верно» СНИМАЕТ претензию: ремонт по ней "
        + "больше не пойдёт. «Передан неверно» уходит человеку на экран «Анализ» "
        + "— это вопрос к записи глоссария, а не к строке.",
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
        ? "правит по всем находкам · ещё " + rpWaiting
          + " с находками ждут второго захода — раскройте строку"
        : "правит по всем находкам, включая глоссарий",
      modelId: rpModel, onModel: pickRpModel, plan: stepPlan("repair"),
      planEst: planEstOf("repair", rpModelInfo, { recheckModel: bcModelInfo,
        judge: bcJudge, judgeModel: judgeModelInfo || bcModelInfo }),
      soloEst: estimateRun("repair", project.segments.filter(s => repairable(s, currentIdSet)),
        rpModelInfo, { recheckModel: bcModelInfo,
          judge: bcJudge, judgeModel: judgeModelInfo || bcModelInfo }),
      onSolo: runRepairBatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "repair" ? batchRun : null,
      soloNote: "Правка плюс перепроверка теми же проверками: если оценка упадёт, текст откатится. Один заход на один текст — второй даст то же самое за те же деньги.",
      options: React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
        React.createElement("div", { className: "row between", style: { gap: 12, flexWrap: "wrap" } },
          React.createElement("div", { style: { minWidth: 0 } },
            React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, display: "flex", alignItems: "center" } },
              "Чинить подтверждённые человеком",
              React.createElement(InfoTip, { title: "Что произойдёт", body: "Ремонт правит только по конкретным находкам и меняет минимум слов — сегмент не переводится заново, и полной цены прогона тут нет. Но прежний текст уйдёт в «прошлый перевод», статус станет «требует проверки», а отметка «подтвердил человек» снимется: она относилась к тексту, которого больше нет.\n\nЕсли после правки оценка УПАЛА, текст откатывается вместе с прежними проверками — ровные оценки правку не отменяют.\n\nУ захода, где кроме мелких замечаний по терминам ничего не было, правило строже: он принимается, только если снял хотя бы одно из тех замечаний, ради которых заходили. Иначе это размен одной придирки на другую — работа за деньги без движения к концу.\n\nГалочка действует только на этот шаг. Перевод по ней ничего не перегоняет." })),
            React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
              rpConfirmedWaiting
                ? rpConfirmedWaiting + " заверенных сегментов с находками ждут решения"
                : "в выборке нет заверенных сегментов с находками")),
          React.createElement(Switch, { on: rpFixConfirmed, label: "Чинить подтверждённые",
            onClick: toggleRpFixConfirmed })),
        rpFixConfirmed && React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
          "С этих сегментов снимется отметка «подтвердил человек» — их придётся заверить заново."),
        groupTable("Что чинить — отметьте, если нужен второй заход:",
          rpGroups, pickedRpGroups, toggleRpGroup,
          "Нет сегментов с находками. Сначала прогоните back-check или проверку терминов.")),
    },
    {
      key: "medical_qa", label: FULL_STEP_LABELS.medical_qa, hint: "числа и отрицания; обратный перевод берёт у back-check",
      modelId: null, onModel: null, plan: stepPlan("medical_qa"),
      modelNote: (bcModelInfo ? bcModelInfo.label : "—") + " · от back-check",
      planEst: planEstOf("medical_qa", bcModelInfo),
      // Своей модели у неё нет: правила детерминированные. Платный вызов —
      // только обратный перевод и только там, где готового от back-check нет.
      soloEst: estimateRun("medical_qa",
        qaSolo.filter(s => !(s.backcheck && !s.backcheck.stale && s.backcheck.back)), bcModelInfo),
      onSolo: runMedicalQABatch, onStop: stopJob,
      running: batchRun && batchRun.engine === "medical_qa" ? batchRun : null,
      soloNote: "Считает заново по всей выборке. Сегментам со свежим back-check это бесплатно — обратный перевод у них уже есть.",
    },
  ];

  // Проверка, которую делает та же модель, что переводила, — не независимая,
  // а на независимости стоит автоодобрение терминов. Молчать об этом нельзя.
  // Ремонт тоже: он переписывает перевод, и если это делает та же модель,
  // что переводила, она правит по собственному пониманию текста.
  const sameModelWarn = [bcModel, tcModel, rpModel].filter(m => m && m === gptModel).length > 0;

  const runFullJob = async () => {
    const steps = FULL_STEP_KEYS.filter(k => pickedFull.has(k));
    if (!steps.length) { toast.warning("Не выбрано ни одного шага", "Отметьте хотя бы один."); return; }
    // Состав, посчитанный сервером, запоминаем ДО запуска: через секунду
    // разбор уже не пересчитается (см. readRunSnap), а полоса прогресса
    // должна говорить не только «сделано», но и «осталось».
    const planned = {};
    steps.forEach(k => { planned[k] = (fullStepTargets[k] || []).length; });
    const started = await startJob("full", fullRunIds, {
      steps,
      model: gptModel, bc_model: bcModel, tc_model: tcModel, tcx_model: tcxModel,
      rp_model: rpModel, use_judge: bcJudge, judge_model: judgeModel || null,
      // Тот же retry, что и у карточки ремонта: карточка выше посчитала
      // и оценила сегменты по этому же правилу, и разойтись они не должны.
      retry: repairRetry(),
      // Разрешение сервер отдаёт только шагу ремонта (см. _job_chunk_full):
      // перевод по этой галочке не перегоняет ничего.
      include_confirmed: rpFixConfirmed,
    }, "В выбранных сегментах нечего делать.", fullEst);
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
    if (batchRun) { toast.warning("Прогон уже идёт", "Дождитесь окончания."); return; }
    if (!window.API) return;
    const res = await window.API.safeCall(() => window.API.createJob(project.id, "apply_terms", [], {
      max_tier: null, term_limit: 2000,
      allow_verified: termOrders,
      rp_model: rpModel, bc_model: bcModel, tc_model: tcModel,
      use_judge: bcJudge, judge_model: judgeModel || null,
      include_confirmed: !!impactConfirmed,
    }));
    if (!res || !res.ok) { toast.error("Не удалось запустить", "Сервер не принял задачу."); return; }
    setJob(res.job);
    toast.info("Одобряем и применяем",
      "Термины уходят в глоссарий, затем сегменты чинятся по ним. Вкладку можно закрыть.");
  };

  const filterDefs = [
    ["all", "Все", counts.all], ["new", "Новые", counts.new], ["translated", "Переведено", counts.translated],
    ["qa", "QA", counts.qa], ["confirmed", "Подтверждено", counts.confirmed], ["failed", "Ошибки", counts.failed],
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
          React.createElement("span", { className: "dim", style: { fontSize: 13 } }, "Высота таблицы"),
          React.createElement("input", { type: "range", min: 320, max: 720, step: 20, value: height,
            onChange: (e) => setHeight(Number(e.target.value)), style: { width: 130 }, "aria-label": "Высота таблицы" }),
          React.createElement(IconBtn, { icon: "filter", label: "Доп. фильтры", sm: true, active: showFilters, onClick: () => setShowFilters(s => !s) })
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
              "Снять выбор (" + checkedSegs.size + ")")
          : filtered.length > 0 && React.createElement(Btn, { variant: "ghost", size: "sm",
              onClick: () => setCheckedSegs(new Set(filtered.map(s => s.id))) },
              "Выбрать все " + filtered.length + (inZone ? " в зоне"
                : (filter !== "all" || query || activeFilter ? " по фильтру" : "")))
        // Поиска здесь больше нет: он один и стоит над таблицей, рядом
        // с переходом по номеру. Два поля на одно состояние — это два места,
        // где его ищут, и лишняя высота у залипающей панели, из-за которой
        // таблицу видно хуже.
      ),
      showFilters && React.createElement("div", { className: "row row-wrap", style: { gap: 14, padding: "4px 2px" } },
        React.createElement(Select, { value: riskFilter, onChange: (e) => setRiskFilter(e.target.value), style: { width: 200 } },
          [["all", "Любой риск"], ["low", "Низкий риск"], ["medium", "Средний риск"], ["high", "Высокий риск"], ["critical", "Критический риск"]]
            .map(([v, l]) => React.createElement("option", { key: v, value: v }, l))),
        React.createElement(Select, { value: originFilter, onChange: (e) => setOriginFilter(e.target.value), style: { width: 220 } },
          [["all", "Любой источник"], ["para", "Из абзацев документа"], ["image", "Из надписей на картинках"]]
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
          React.createElement("span", { style: { fontSize: 13, fontWeight: 600 } }, "Фильтр: " + activeFilter.size + " сегментов из анализа")),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "x", onClick: () => { window._mcat_sf = null; store.setSegmentFilter(null); } }, "К основному файлу")
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
            est: fullEst, sameModelWarn: sameModelWarn,
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
          // Состав ремонта — тот же список, что показывает соседняя карточка,
          // МИНУС застрявшие: сервер их не возьмёт, и обещать по ним работу
          // значит показать под кнопкой число, которого не будет.
          pendingSegs: impact
            ? (impactConfirmed ? impact.segments : impact.pending)
                .filter(i => (impact.futile || []).indexOf(i) === -1).length : 0,
          futileSegs: impact ? (impact.futile || []).length : 0 }),
        // Карточка живёт и при нуле расхождений. Пряча её, мы уносили вместе
        // с ней «Пересчитать» — единственный способ убедиться, что ноль
        // настоящий, а не остался с прошлого расчёта. Ровно та же беда, от
        // которой защищены исчерпывающие корзины «Анализа»: пропавшее
        // с экрана выглядит благополучнее, чем есть.
        impact && React.createElement(GlossaryImpactCard, {
          impact, busy: impactBusy, onRefresh: () => loadImpact(true),
          includeConfirmed: impactConfirmed, onIncludeConfirmed: () => setImpactConfirmed(v => !v),
          onRun: runImpactRetranslate,
          onDrill: (ids) => { store.setSegmentFilter(ids); setPage(1); },
          est: estimateRun("translate", project.segments.filter(s =>
            new Set(impactConfirmed ? impact.segments : impact.pending).has(s.id)), gptModelInfo),
          running: batchRun && batchRun.engine === "translate" && job && job.params && job.params.via === "impact" ? batchRun : null }))),

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
                "aria-label": "Перейти к сегменту по номеру",
                title: "Номер сегмента: покажу его и по " + ZONE_HALF + " соседей до и после",
                onChange: (e) => setJump(e.target.value),
                onKeyDown: (e) => { if (e.key === "Enter") goToZone(jump); } })),
            React.createElement(IconBtn, { icon: "arrowR", label: "Перейти к сегменту", sm: true,
              onClick: () => goToZone(jump) }),
            React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value),
              placeholder: searchPlaceholder }),
            React.createElement(Select, { value: scope, onChange: (e) => pickScope(e.target.value),
              style: { width: "auto", flex: "0 0 auto" }, "aria-label": "Где искать" },
              scopeOpts.map(([v, l]) => React.createElement("option", { key: v, value: v }, l))),
            query && React.createElement(IconBtn, { icon: "close", label: "Очистить поиск", sm: true, onClick: () => setQuery("") }),
            query && React.createElement("span", { className: "dim", style: { fontSize: 12, whiteSpace: "nowrap" } },
              filtered.length ? "найдено: " + filtered.length : "ничего не найдено")
          ),
          // Пока открыта зона, в таблице не весь файл. Сказать об этом обязаны
          // мы: иначе «куда делись сегменты» человек ищет в фильтрах, которых
          // мы же и не оставили.
          inZone && React.createElement("div", { className: "zone-strip" },
            React.createElement(Icon, { name: "target", size: 14, style: { color: "var(--c-primary)" } }),
            React.createElement("span", null,
              "Зона сегмента #" + zone + ": " + (zoneIdx - zoneFrom) + " до и " + (zoneTo - zoneIdx - 1) + " после"
              + " — строки " + (zoneFrom + 1) + "–" + zoneTo + " из " + project.segments.length),
            // Выход из зоны оставляет человека НА ТОМ ЖЕ месте файла: страница
            // берётся по сегменту-центру. Иначе «Весь файл» телепортирует
            // на первую страницу, и найденное место приходится искать заново.
            React.createElement(Btn, { variant: "secondary", size: "sm", icon: "close",
              onClick: () => {
                jumpRef.current = true;                 // страницу сменили мы — выбор не сбрасывать
                setPage(Math.floor(zoneIdx / PAGE_SIZE) + 1);
                setZone(null); setJump("");
              } }, "Весь файл")
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
                React.createElement("th", null, "🇷🇺 Оригинал"),
                React.createElement("th", null, "🇬🇧 Перевод"),
                React.createElement("th", { style: { width: 132 } }, "Статус"),
                React.createElement("th", { style: { width: 76 },
                  title: "Ремонт, находки по терминам, back-check" }, "Проверки"),
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
          React.createElement(EmptyState, { icon: "filter", title: "Нет сегментов по фильтру",
            sub: query ? "«" + query + "» не найдено — " + scopeOpts.find(o => o[0] === scope)[1].toLowerCase() + ". Смените область поиска или очистите запрос."
                       : "Измените фильтр статуса или поиск." })),
        React.createElement("div", { className: "row", style: { gap: 16, marginTop: 12, fontSize: 12, color: "var(--text-3)", flexWrap: "wrap" } },
          React.createElement(LegendDot, { color: "var(--st-new-fg)", label: "Новый" }),
          React.createElement(LegendDot, { color: "var(--c-primary)", label: "Переведён" }),
          React.createElement(LegendDot, { color: "var(--c-warning)", label: "QA" }),
          React.createElement(LegendDot, { color: "var(--c-success)", label: "Подтверждён" }),
          React.createElement(LegendDot, { color: "var(--c-error)", label: "Ошибка" })
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
              onTranslate: () => doTranslate(selected, true), onQA: () => doQA(selected), onMedicalQA: () => doMedicalQA(selected), onConfirm: (draftTarget) => doConfirm(selected, draftTarget),
              bcModels: gptModels, bcModel: bcModel, onBcModel: pickBcModel,
              bcJudge: bcJudge, judgeModel: judgeModel,
              tcModel: tcModel, rpModel: rpModel, tcActionable: tcActionable })
          : React.createElement(EmptyState, { icon: "edit", title: "Сегмент не выбран", sub: "Выберите строку в таблице." })
      )
    ),

    batchPlan && (() => {
      const est = estimateBatch(batchPlan.targets, gptModelInfo);
      return React.createElement(Modal, {
        title: "Запустить GPT-пакет?", icon: "zap", onClose: () => setBatchPlan(null),
        footer: React.createElement(React.Fragment, null,
          React.createElement(Btn, { variant: "ghost", onClick: () => setBatchPlan(null) }, "Отмена"),
          React.createElement(Btn, { variant: "primary", icon: "zap",
            onClick: () => runBatch(batchPlan.targets, batchPlan.hasExplicitCheck) }, "Запустить")) },
        React.createElement("div", { style: { display: "grid", gap: 10, fontSize: 14 } },
          React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, "Сегментов"),
            React.createElement("b", null, batchPlan.targets.length)),
          React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, "Модель"),
            React.createElement("b", null, gptModelInfo ? gptModelInfo.label : "по умолчанию")),
          React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, "Примерное время"),
            React.createElement("b", null, "≈ " + fmtDuration(est.seconds))),
          est.cost != null && React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, "Примерная стоимость"),
            React.createElement("b", null, "≈ " + fmtCost(est.cost))),

          // Последний экран перед запуском — здесь и должно быть видно
          // последствие, а не только в свёрнутой строке шага, где галочку
          // включили несколько кликов назад.
          (() => {
            const n = batchPlan.targets.filter(s => s.status === "confirmed").length;
            return n > 0 && React.createElement("div", {
              style: { fontSize: 12.5, lineHeight: 1.5, padding: "7px 9px", borderRadius: "var(--r-md)",
                       background: "var(--bg-sunken)", border: "1px solid var(--c-warning)", color: "var(--text-2)" } },
              React.createElement("b", { style: { color: "var(--c-warning)" } }, "Среди них подтверждённых: " + n),
              " — с них снимется отметка «подтвердил человек».");
          })(),

          // Чем эти сегменты переведены сейчас — чтобы было видно, что именно
          // перегоняется и не уходит ли на повтор уже сделанное нужной моделью
          (() => {
            const by = {};
            batchPlan.targets.forEach(s => {
              const l = providerLabel(providerOf(s), gptModels) || "ещё не переведён";
              by[l] = (by[l] || 0) + 1;
            });
            const rows = Object.keys(by).sort((a, b) => by[b] - by[a]);
            if (rows.length === 1 && rows[0] === "ещё не переведён") return null;
            return React.createElement("div", { style: { borderTop: "1px solid var(--border)", paddingTop: 10 } },
              React.createElement("div", { className: "muted", style: { marginBottom: 6 } }, "Сейчас переведено через"),
              rows.map(l => React.createElement("div", { key: l, className: "row between", style: { fontSize: 13, padding: "2px 0" } },
                React.createElement("span", null, l),
                React.createElement("b", null, by[l]))));
          })(),
          React.createElement("p", { className: "muted", style: { margin: 0, fontSize: 12.5, lineHeight: 1.6 } },
            "Оценка ориентировочная: считается по объёму текста, фактический расход зависит от ответа модели. " +
            "Прогон идёт на сервере порциями по " + BATCH_CHUNK + " сегментов, переводы сохраняются после каждой — " +
            "вкладку можно закрыть, а остановка не откатывает уже сделанное.")
        )
      );
    })(),

    propagateAsk && React.createElement(Modal, {
      title: "Такой же исходник есть ещё в проекте", icon: "repeat", onClose: () => setPropagateAsk(null),
      footer: React.createElement(React.Fragment, null,
        React.createElement(Btn, { variant: "ghost", onClick: () => setPropagateAsk(null) }, "Не сейчас"),
        propagateAsk.prop.confirmed.length > 0 && React.createElement(Btn, { variant: "secondary", icon: "alert", onClick: () => doPropagate(true) },
          "Перезаписать и подтверждённые (" + (propagateAsk.prop.pending.length + propagateAsk.prop.confirmed.length) + ")"),
        propagateAsk.prop.pending.length > 0 && React.createElement(Btn, { variant: "primary", icon: "repeat", onClick: () => doPropagate(false) },
          "Применить к " + propagateAsk.prop.pending.length)) },
      React.createElement("div", { className: "col", style: { gap: 12 } },
        React.createElement("p", { className: "muted", style: { margin: 0, lineHeight: 1.6 } },
          "Подтверждённый перевод сегмента ",
          React.createElement("b", { style: { color: "var(--text)" } }, "#" + propagateAsk.seg.id),
          " отличается от перевода других сегментов с тем же исходным текстом."),
        React.createElement("div", { className: "card", style: { padding: "10px 14px", background: "var(--bg-sunken)", fontSize: 13, lineHeight: 1.7 } },
          propagateAsk.prop.pending.length > 0 && React.createElement("div", null,
            "Не подтверждено — можно обновить сразу: ",
            React.createElement("b", null, propagateAsk.prop.pending.map(id => "#" + id).join(", "))),
          propagateAsk.prop.confirmed.length > 0 && React.createElement("div", { style: { marginTop: 6, color: "var(--c-warning)" } },
            "Уже подтверждено кем-то — перезапись только по явной команде: ",
            React.createElement("b", null, propagateAsk.prop.confirmed.map(id => "#" + id).join(", ")))),
        React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 12.5, lineHeight: 1.6 } },
          "Обновлённые сегменты получат статус «Переведён», а не «Подтверждён»: заверить перевод должен человек. Прежний текст сохраняется и виден в карточке сегмента."))
    ),

    revertTarget && React.createElement(Modal, {
      title: "Снять подтверждение?", icon: "warn", onClose: () => setRevertTarget(null),
      footer: React.createElement(React.Fragment, null,
        React.createElement(Btn, { variant: "ghost", onClick: () => setRevertTarget(null) }, "Отмена"),
        React.createElement(Btn, { variant: "primary", icon: "repeat", onClick: confirmRevert }, "Снять подтверждение")) },
      React.createElement("p", { className: "muted", style: { margin: 0, lineHeight: 1.6 } },
        "Сегмент ", React.createElement("b", { style: { color: "var(--text)" } }, "#" + revertTarget.id),
        " будет возвращён из статуса «Подтверждён» в «Переведён». Запись в памяти переводов сохранится.")
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
    React.createElement("button", { className: "page-num", disabled: page <= 1, onClick: () => onGo(page - 1), "aria-label": "Назад" },
      React.createElement(Icon, { name: "chevL", size: 15 })),
    nums.map((n, i) => n === "…"
      ? React.createElement("span", { key: "e" + i, className: "page-ellipsis" }, "…")
      : React.createElement("button", { key: n, className: "page-num" + (n === page ? " on" : ""), onClick: () => onGo(n), "aria-current": n === page ? "page" : null }, n)),
    React.createElement("button", { className: "page-num", disabled: page >= totalPages, onClick: () => onGo(page + 1), "aria-label": "Вперёд" },
      React.createElement(Icon, { name: "chevR", size: 15 })),
    React.createElement("span", { className: "dim", style: { marginLeft: 6, fontSize: 13 } }, "Перейти:"),
    React.createElement("input", { className: "input page-goto", value: goto, onChange: (e) => setGoto(e.target.value.replace(/\D/g, "")),
      onKeyDown: submitGoto, placeholder: String(page), "aria-label": "Перейти к странице" })
  );
}

function StatusBar({ segShown, segTotal, wordsShown, wordsTotal, charsShown, charsTotal }) {
  const fmt = (n) => n.toLocaleString("ru-RU");
  return React.createElement("div", { className: "statusbar" },
    React.createElement("div", { className: "row", style: { gap: 10, flexWrap: "wrap" } },
      React.createElement("span", { className: "sb-group" }, React.createElement(Icon, { name: "list", size: 14 }), " Сегментов: ", React.createElement("b", null, segShown + "/" + segTotal)),
      React.createElement("span", { className: "sb-sep" }, "·"),
      React.createElement("span", { className: "sb-group" }, "Слов: ", React.createElement("b", null, fmt(wordsShown) + "/" + fmt(wordsTotal))),
      React.createElement("span", { className: "sb-sep" }, "·"),
      React.createElement("span", { className: "sb-group" }, "Знаков: ", React.createElement("b", null, fmt(charsShown) + "/" + fmt(charsTotal)))
    ),
    React.createElement("span", { className: "sb-save" }, React.createElement("span", { className: "sb-dot" }), "Автосохранение", React.createElement(Icon, { name: "check", size: 13, stroke: 2.6, style: { color: "var(--c-success)" } }))
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
  return "Считано с ответов моделей: " + u.calls + " вызовов, "
    + Math.round(u.in / 1000) + "К входных токенов"
    + (u.cached_in ? " (из них " + Math.round(u.cached_in / 1000) + "К кэшированных — скидка на них тут не учтена, цифра завышена на неё)" : "")
    + ", " + Math.round(u.out / 1000) + "К выходных"
    + (u.reasoning ? ", включая " + Math.round(u.reasoning / 1000) + "К на рассуждения" : "")
    + ".\n\nЦена — по каталогу моделей. Смета до запуска считается по объёму текста и точной быть не может; это число — то, за что выставят счёт."
    + (sp.unpriced ? "\n\nВызовов по модели без цены: " + sp.unpriced + ". Они в сумму НЕ входят." : "");
}

function RunStrip({ job, steps, onStop }) {
  const spend = spendOf(job);
  const pct = Math.round(job.done / Math.max(1, job.total) * 100);
  const phase = job.stopping ? "останавливается"
    : job.status === "queued" ? "в очереди" : "идёт на сервере";
  const unknown = steps.length > 0 && steps.every(st => st.total == null);
  return React.createElement("div", { className: "run-strip" },
    React.createElement(Spinner, null),
    React.createElement("div", { className: "rs-main" },
      React.createElement("div", { className: "rs-title" },
        React.createElement("span", null, (JOB_LABELS[job.kind] || job.kind) + " — " + phase),
        React.createElement("span", { className: "rs-num" }, job.done + " из " + job.total),
        spend && React.createElement("span", { className: "rs-num", title: spendTitle(spend) },
          "потрачено " + fmtCost(spend.cost)
          + (spend.est != null ? " из ≈ " + fmtCost(spend.est) : "")),
        React.createElement("span", { className: "dim", style: { fontWeight: 500, fontSize: 11.5 } },
          "вкладку можно закрыть — прогон продолжится")),
      React.createElement(ProgressBar, { value: pct })),
    React.createElement(Btn, { variant: "ghost", size: "sm", onClick: onStop, disabled: !!job.stopping },
      job.stopping ? "Останавливаем…" : "Остановить"),

    steps.length > 0 && React.createElement("div", { className: "run-steps" },
      steps.map(st => React.createElement("span", {
        key: st.key,
        className: "run-step " + (st.complete ? "ok" : "on"),
        title: st.label + ": " + (
          // Состава нет — говорим только о сделанном. Сравнивать с total здесь
          // нельзя: в JS `4 > null` — правда, и подпись соврала бы про разбор.
          st.total == null ? "сделано " + st.done
            + " — сколько всего, неизвестно: прогон запущен не из этой вкладки"
          : st.total === 0 ? "разбор не отвёл ему ни одного сегмента"
          // Ремонт умеет выйти за план: находки рождают проверки этого же
          // прогона, а разбор считал по прежним. Так и говорим.
          : st.done > st.total ? "сделано " + st.done + " — больше, чем было в разборе ("
              + st.total + "): находки добавили проверки этого же прогона"
          : st.complete ? "взял все " + st.total + " сегм., которые ему отвёл разбор"
          : "сделано " + st.done + " из " + st.total + ", осталось " + st.left) },
        st.complete
          ? React.createElement(Icon, { name: "check", size: 12, stroke: 3 })
          : React.createElement("span", { className: "rs-dot" }),
        st.label,
        React.createElement("b", null, st.done),
        !st.complete && st.left != null
          ? React.createElement("span", { className: "dim" }, "· осталось " + st.left) : null)),
      unknown && React.createElement("span", { className: "dim", style: { fontSize: 11.5, alignSelf: "center" } },
        "остаток по шагам не показываем: прогон запущен не из этой вкладки")));
}

const FULL_RUN_TIP = "Один прогон вместо пяти: перевод → back-check → проверка терминов → ремонт → Medical QA. Порядок фиксирован и важен: терминологию в глоссарий собирает та из двух проверок, что отработала второй; ремонт чинит по находкам обеих; Medical QA идёт последней, чтобы описывать окончательный текст, а не тот, который через шаг перепишут.\n\nПереводит одна модель, проверяют другие — в этом весь смысл: проверка, сделанная той же моделью, что и перевод, независимой не является.\n\nСостав считает сервер и показывает целиком: разверните строку шага, чтобы увидеть, кого он возьмёт и почему пропустит остальных. Готовую проверку он второй раз не оплачивает, а вердикт более сильной модели не даёт перезаписать более слабой — подбирать это галочками вручную больше не нужно. Проверки посчитаны и по тем сегментам, которые будут переведены в этом же прогоне.\n\nВ той же строке любой шаг запускается отдельно и по своим галочкам: это способ намеренно перепроверить то, что общий прогон считает сделанным.\n\nЧтобы сузить прогон, отметьте сегменты галочками или включите фильтр. Прогон идёт на сервере — вкладку можно закрыть.";

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
        label: open ? "Свернуть" : "Подробнее и запуск по отдельности",
        onClick: () => onOpen(open ? null : row.key) })),

    // ── раскрытая строка: причины, опции шага, запуск только его ──
    open && React.createElement("div", { key: row.key + "-d",
      style: { gridColumn: "1 / -1", background: "var(--bg-sunken)", borderRadius: 9,
               padding: "10px 13px", margin: "2px 0 8px", display: "flex",
               flexDirection: "column", gap: 9 } },
      p && React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 2 } },
        reasons(p.runs, "в общий прогон: ", "var(--text-2)"),
        reasons(p.skips, "пропустит: ", "var(--text-3)"),
        p.note && React.createElement("div", { style: { fontSize: 11.5, lineHeight: 1.5, color: "var(--text-3)" } }, p.note)),
      row.options,
      React.createElement("div", { style: { borderTop: "1px solid var(--border)", paddingTop: 9,
        display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 10, flexWrap: "wrap" } },
        React.createElement("div", null,
          React.createElement("div", { style: { fontSize: 12, fontWeight: 600 } }, "Запустить только этот шаг"),
          React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5, maxWidth: 460 } },
            row.soloNote || "По отмеченному выше, а не по решению сервера: так перепроверяют то, что общий прогон считает уже сделанным."),
          React.createElement(EstLine, { est: row.soloEst })),
        row.running
          ? React.createElement(Btn, { variant: "ghost", size: "sm", onClick: row.onStop }, "Остановить")
          : React.createElement(Btn, { variant: "secondary", size: "sm", icon: "zap",
              onClick: row.onSolo, disabled: disabled || !(row.soloEst && row.soloEst.count) },
              row.soloEst && row.soloEst.count ? "Запустить: " + row.soloEst.count + " сегм." : "нечего запускать")))
  ];
}

function FullRunCard({ running, onRun, onStop, rows, picked, onToggle, scopeSize,
                       checked, filtered, est, sameModelWarn, models, disabled,
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
          React.createElement("div", { style: { fontWeight: 650, fontSize: 14, display: "flex", alignItems: "center" } }, "Перевести и проверить",
            React.createElement(InfoTip, { title: "Что делает эта кнопка", body: FULL_RUN_TIP })),
          React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
            "шаги идут по порядку, у каждого своя модель"))),
      React.createElement("span", { className: "dim", style: { fontSize: 11.5 } },
        "в работу пойдут " + scopeSize + " сегм."
        + (checked > 0 ? " · по галочкам" : filtered ? " · по фильтру" : ""))),

    sameModelWarn && React.createElement("div", { style: { fontSize: 12.5, lineHeight: 1.5, color: "var(--c-warning)", background: "var(--bg-sunken)", padding: "8px 11px", borderRadius: 8 } },
      "Перевод и проверку делает одна модель. Она не найдёт собственную ошибку — "
      + "выберите другую модель для back-check, терминов или ремонта."),

    React.createElement("div", { style: { display: "grid", gridTemplateColumns: "minmax(170px,1fr) auto auto auto auto", columnGap: 12, alignItems: "center" } },
      head("Шаг"), head("Модель"), head("Сегм.", true), head("≈ цена", true), head(" "),
      rows.map(r => StepRow({
        row: r, on: picked.has(r.key), onToggle, models, disabled,
        open: openStep === r.key, onOpen: onOpenStep }))),

    React.createElement(EstLine, { est }),
    React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: -6 } },
      planBusy ? "Считаем состав…"
        : !planReady ? "Состав прогона не получен от сервера — запуск вслепую не даём."
        // Полностью это объяснено в подсказке у названия. Здесь коротко:
        // блок стоит в колонке, и абзац мелким текстом занимал в ней пять строк.
        : "Состав и смету посчитал сервер тем же кодом, который потом и работает."),

    // Взведённое разрешение трогать заверенное человеком видно У КНОПКИ, а не
    // только в раскрытой строке ремонта. Иначе последствие — снятые отметки
    // «подтвердил человек» — наступало бы от нажатия, за которым на экране
    // ничего об этом не сказано.
    fixConfirmed && React.createElement("div", {
      style: { fontSize: 11.5, lineHeight: 1.5, padding: "7px 9px", borderRadius: "var(--r-md)",
               background: "var(--bg-sunken)", border: "1px solid var(--c-warning)",
               color: "var(--text-2)" } },
      React.createElement("b", { style: { color: "var(--c-warning)" } }, "Ремонт возьмёт и подтверждённые"),
      fixConfirmedCount ? " — " + fixConfirmedCount + " заверенных сегментов с находками; "
                        : " — в выборке таких сейчас нет; ",
      "с исправленных снимется отметка «подтвердил человек». Выключается в строке «Ремонт»."),

    // Во время прогона цифры показывает полоса наверху — она залипающая и
    // видна всегда. Второй прогресс-бар здесь только повторял бы её и уезжал
    // за край экрана вместе с карточкой.
    running
      ? React.createElement("div", { className: "row between", style: { gap: 8, flexWrap: "wrap" } },
          React.createElement("span", { className: "muted", style: { fontSize: 12 } },
            "Идёт полный прогон — счёт по шагам на полосе наверху"),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: onStop }, "Остановить"))
      : React.createElement(Btn, { variant: "primary", icon: "zap", onClick: onRun,
          disabled: disabled || !anyWork || !planReady },
          // «Всё уже сделано» и «ни один шаг не отмечен» — разные причины нулевой
          // работы, и молчать о разнице нельзя: сняли все галочки шагов — кнопка
          // выглядела бы как «весь проект готов», хотя работа просто не выбрана.
          !planReady ? "Считаем состав…"
            : picked.size === 0 ? "Отметьте хотя бы один шаг"
            : anyWork ? "Перевести и проверить" : "Всё уже сделано"));
}

/* Второй клик конвейера. Одобряет однозначные термины пачкой и тут же чинит
   ими сегменты. Состав сегментов не выбирается намеренно: пока термины не
   одобрены, неизвестно, какие сегменты с ними разойдутся — список считает
   сервер сразу после одобрения. */
function ApplyTermsCard({ running, onRun, onStop, disabled, preview, sources,
                          includeConfirmed, onIncludeConfirmed, confirmedCount,
                          orders, onOrders, pendingSegs, futileSegs }) {
  const c = preview && preview.counts;
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
          React.createElement("div", { style: { fontWeight: 650, fontSize: 14, display: "flex", alignItems: "center" } }, "Одобрить и применить",
            React.createElement(InfoTip, { title: "Что делает эта кнопка",
              body: "Однозначные термины уходят в глоссарий пачкой, а затем сегменты чинятся по ним: расхождение с утверждённым термином — такая же находка ремонта, как потерянный термин или расхождение чисел.\n\nЧто считается однозначным: у термина ровно один вариант перевода; пара пришла из нескольких независимых сегментов, прошедших back-check и проверку терминов чисто; перевод встречается в текстах целевого языка.\n\nПриказом («use these exact translations») запись становится от человека, от трёх независимых чистых сегментов или от совпадения с ВЫВЕРЕННЫМ отраслевым справочником. У справочника есть уровень: краудсорсный (например выгрузка Wikidata) приказа в одиночку не даёт — он идёт подтверждающим голосом рядом с согласием сегментов и корпусом целевого языка. В медицине, фармацевтике и юриспруденции ни согласия сегментов, ни краудсорсного справочника для приказа НЕ хватает: там приказ даёт человек или выверенный справочник.\n\nЛюбую пачку можно откатить целиком в «Глоссарии»." })),
          React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
            "термины в глоссарий → ремонт по ним → перепроверка"))),
      React.createElement("span", { style: { fontVariantNumeric: "tabular-nums", fontWeight: 700, fontSize: 17, color: ready ? "var(--c-success)" : "var(--text-3)" } },
        ready)),

    // Чем проверялись термины. Покрытие по парам языков очень разное, и разницу
    // честнее назвать, чем дать пользователю обнаружить её на своих текстах.
    React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.55 } },
      "Проверяют: ",
      dicts.length
        ? dicts.map(d => d.label + " (" + d.terms
            + (d.tier === "verified" ? ", приказ" : ", голос") + ")").join(" · ")
        : "справочников для этой пары языков нет",
      corpus ? " · корпус " + corpus.label : " · корпус недоступен",
      preview && preview.corpusSkipped
        ? " · сверх потолка не проверено: " + preview.corpusSkipped : ""),

    // Цифра выше посчитана ДО обращения к корпусу: спрашивать его при каждом
    // открытии проекта — это минута ожидания на лимитах источника. При нажатии
    // он отработает, и часть кандидатов может отсеяться как отсутствующие
    // в целевом языке. Обещать больше, чем сделаем, нельзя.
    preview && (preview.corpusPending || preview.meaningPending) && React.createElement("div",
      { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
      "Это верхняя оценка: при нажатии термины пройдут "
      + [preview.corpusPending && corpus ? "проверку по " + corpus.label : null,
         preview.meaningPending ? "смысловую сверку судьёй (то же ли понятие)" : null]
        .filter(Boolean).join(" и ")
      + " — кальки и ложные друзья будут отклонены, а не записаны."),

    c && c.skipped > 0 && React.createElement("div", { className: "dim", style: { fontSize: 12.5 } },
      "останется человеку: ", React.createElement("b", null, c.skipped),
      " — разобрать в «Глоссарии»"),

    confirmedCount > 0 && React.createElement(Checkbox, {
      checked: !!includeConfirmed, onChange: onIncludeConfirmed },
      "Чинить и подтверждённые (" + confirmedCount + ")"),

    // Разрешение на приказы — только там, где область их запрещает, и только
    // на этот запуск (см. панель в «Знаниях»: то же правило, тот же откат).
    banned && React.createElement("div", { className: "col", style: { gap: 3 } },
      React.createElement(Checkbox, { checked: !!orders, onChange: onOrders },
        "Приказы по согласию сегментов"),
      React.createElement("div", { className: "dim", style: { fontSize: 11, lineHeight: 1.5 } },
        orders
          ? "Запрет области снят на этот запуск: согласие независимых чистых "
            + "сегментов даст приказ. Каждый такой термин пройдёт смысловую "
            + "сверку судьёй; пачка откатывается целиком в «Глоссарии»."
          : "Сейчас приказ в этой области даёт только человек или выверенный "
            + "справочник — однозначные уходят подсказкой, которую модель "
            + "вправе игнорировать.")),

    // Счёт — на полосе наверху, здесь только название текущей половины работы:
    // пока список сегментов не посчитан, идёт запись терминов в глоссарий.
    running
      ? React.createElement("div", { className: "row between", style: { gap: 8, flexWrap: "wrap" } },
          React.createElement("span", { className: "muted", style: { fontSize: 12 } },
            running.total ? "Применяем к сегментам…" : "Одобряем термины…"),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: onStop }, "Остановить"))
      : React.createElement(Btn, { variant: "primary", icon: "check", onClick: onRun,
          // Одобрять нечего — это НЕ значит «работы нет»: расхождения с уже
          // утверждёнными терминами чинит та же задача, и это единственный
          // дешёвый путь. Запирая кнопку на нуле терминов, интерфейс оставлял
          // человеку только переперевод — вдвое дороже и без проверок.
          disabled: disabled || (!ready && !pendingSegs) },
          ready ? "Одобрить " + ready + " и применить"
            : pendingSegs ? "Применить к " + pendingSegs + " сегм."
              : "Нечего применять"),
    !ready && pendingSegs > 0 && !running && React.createElement("div",
      { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
      "Новых однозначных терминов нет, но " + pendingSegs + " сегм. расходятся "
      + "с уже утверждёнными — их починит ремонт."),
    // Молчаливого отсева не бывает: если часть работы не пойдёт, сказать
    // почему — иначе человек жмёт кнопку по кругу и не понимает, отчего
    // список не пустеет.
    futileSegs > 0 && !running && React.createElement("div",
      { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
      "Ещё " + futileSegs + " сегм. расходятся, но ремонт их не возьмёт: тот же "
      + "текст с теми же претензиями он уже проходил, и заход вернёт то же "
      + "самое. Их правит человек — либо смените модель ремонта."));
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

// Одобрили термин — старые переводы сами не изменились. Здесь видно, сколько
// сегментов разошлось с глоссарием, и отсюда же их можно переперевести пакетом.
function GlossaryImpactCard({ impact, busy, onRefresh, onRun, onDrill, includeConfirmed, onIncludeConfirmed, est, running }) {
  const targets = includeConfirmed ? impact.segments : impact.pending;
  return React.createElement("div", { className: "card card-pad-sm", style: { display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-warning)" } },
        React.createElement(Icon, { name: "book", size: 19 })),
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, "Соответствие глоссарию",
          React.createElement(InfoTip, { title: "Расхождения с одобренными терминами",
            body: "Одобренный термин влияет только на будущие переводы — уже готовые сегменты сами не меняются. Здесь собраны все сегменты проекта, где термин есть в оригинале, а утверждённого варианта в переводе нет.\n\nСчитается только по проверенным записям глоссария: автоимпорт модель вправе игнорировать, требовать соответствия ему нельзя.\n\nКнопка переводит эти сегменты заново — уже с новым термином в промпте. Подтверждённые по умолчанию не трогаются; с галочкой они тоже переводятся заново, прежний текст сохраняется для отката, а статус становится «Требует проверки» — заверить перевод снова может только человек." })),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, "После правок глоссария"))
    ),
    React.createElement("div", { className: "row between", style: { fontSize: 13, cursor: "pointer" },
      onClick: () => onDrill(impact.segments) },
      React.createElement("span", { style: { fontWeight: 600, color: "var(--c-warning)" } }, "Расходятся с глоссарием"),
      React.createElement("b", null, impact.segments.length)),
    impact.confirmed.length > 0 && React.createElement("div", { className: "row between", style: { fontSize: 12.5, cursor: "pointer" },
      onClick: () => onDrill(impact.confirmed) },
      React.createElement("span", { className: "dim" }, "из них подтверждено"),
      React.createElement("b", { className: "dim" }, impact.confirmed.length)),
    // Застрявшие. Их видно ОТДЕЛЬНО, а не спрятано: расходиться с глоссарием
    // они не перестали, но ремонт по ним даст тот же результат за те же
    // деньги — работа тут человеческая, и об этом надо сказать прямо.
    (impact.futile || []).length > 0 && React.createElement("div", { className: "row between", style: { fontSize: 12.5, cursor: "pointer" },
      onClick: () => onDrill(impact.futile) },
      React.createElement("span", { className: "dim" }, "ремонт уже не берёт"),
      React.createElement("b", { className: "dim" }, impact.futile.length)),

    impact.terms.length === 0 && React.createElement("div",
      { className: "dim", style: { fontSize: 12.5, lineHeight: 1.55 } },
      "Все переводы соответствуют утверждённым терминам. Ноль бывает и после "
      + "понижения записей сверкой смысла: требовать соответствия подсказке "
      + "нельзя, поэтому она из расчёта уходит."),

    impact.terms.length > 0 && React.createElement("div", { className: "card", style: { padding: "8px 11px", background: "var(--bg-sunken)" } },
      impact.terms.slice(0, 4).map((t, i) => React.createElement("div", {
        key: i, className: "row between", style: { fontSize: 12.5, padding: "2px 0", cursor: "pointer" },
        onClick: () => onDrill(t.segments), title: "Показать сегменты с этим термином" },
        React.createElement("span", { style: { minWidth: 0 } },
          t.src, " → ", React.createElement("b", { style: { color: "var(--c-success)" } }, t.tgt)),
        React.createElement("b", null, t.segments.length))),
      impact.terms.length > 4 && React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: 4 } },
        "и ещё " + (impact.terms.length - 4) + " терминов")),

    impact.confirmed.length > 0 && React.createElement(Checkbox, {
      checked: !!includeConfirmed, onChange: onIncludeConfirmed },
      "Включая подтверждённые (" + impact.confirmed.length + ")"),

    targets.length > 0 && React.createElement(EstLine, { est }),
    running
      ? React.createElement("div", { className: "dim", style: { fontSize: 12 } }, "Идёт перевод…")
      : React.createElement("div", { className: "row between" },
          React.createElement("button", { className: "linklike", style: { fontSize: 12 }, onClick: onRefresh, disabled: busy },
            busy ? "Считаем…" : "Пересчитать"),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat", onClick: onRun, disabled: !targets.length },
            "Перевести заново (" + targets.length + ")"))
  );
}

function SegRow({ seg, selected, busy, checked, onCheck, onSelect, onTranslate, onConfirm, onRevert, models, hlSrc, hlTgt }) {
  const prov = providerOf(seg);
  const provText = providerLabel(prov, models);
  const revertable = seg.status === "confirmed" || seg.status === "failed";
  const actionCell = busy
    ? React.createElement("div", { style: { display: "grid", placeItems: "center" } }, React.createElement(Spinner, null))
    : seg.status === "new"
      ? React.createElement(IconBtn, { icon: "globe", label: "Перевести", sm: true, onClick: onTranslate })
      : seg.status === "confirmed"
        ? React.createElement("button", { className: "status-cell-btn revertable", title: "Нажмите, чтобы снять подтверждение", "aria-label": "Снять подтверждение", onClick: onRevert },
            React.createElement(Icon, { name: "checkCircle", size: 18, style: { color: "var(--c-success)" } }))
        : seg.status === "failed"
          ? React.createElement("button", { className: "status-cell-btn revertable", title: "Нажмите, чтобы сбросить в «Новый»", "aria-label": "Сбросить статус", onClick: onRevert },
              React.createElement(Icon, { name: "close", size: 18, style: { color: "var(--c-error)" } }))
          : React.createElement(IconBtn, { icon: "check", label: "Подтвердить", sm: true, onClick: onConfirm });
  // data-seg — якорь для прокрутки к сегменту зоны: искать строку по номеру
  // проще, чем тянуть ref через таблицу.
  return React.createElement("tr", { "data-seg": seg.id, className: "row-status-" + seg.status + (selected ? " selected" : "") + (checked ? " row-checked" : ""), onClick: onSelect },
    React.createElement("td", { style: { width: 36, textAlign: "center" }, onClick: (e) => e.stopPropagation() },
      React.createElement("input", { type: "checkbox", checked: !!checked, onChange: onCheck })),
    React.createElement("td", { className: "col-id" }, seg.id),
    React.createElement("td", { className: "src-cell" }, markHits(seg.source, hlSrc)),
    React.createElement("td", { className: seg.target ? "tgt-cell" : "tgt-cell tgt-empty" },
      seg.target ? markHits(seg.target, hlTgt) : "— не переведено —"),
    React.createElement("td", null,
      React.createElement(StatusBadge, { status: seg.status }),
      provText && React.createElement("div", {
        className: "dim",
        style: { fontSize: 10.5, marginTop: 3, whiteSpace: "nowrap", opacity: prov.exact ? 0.85 : 0.55 },
        title: prov.exact
          ? "Переведено: " + provText
          : "Переведено предположительно через " + provText + " — сегмент переведён до того, как система начала записывать движок точно",
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
        title: "Автоматически исправлено " + (seg.repair.at || "")
          + "\nБыло: " + (seg.repair.from || "")
          + "\nПричины: " + (seg.repair.issues || []).join("; "),
      }, "✓ ремонт"),
      seg.termcheck && (seg.termcheck.findings || []).length > 0 && React.createElement("div", {
        style: { fontSize: 11, fontWeight: 700, marginTop: 4, whiteSpace: "nowrap",
                 color: seg.termcheck.severity === "critical" ? "var(--c-error)"
                   : seg.termcheck.severity === "major" ? "var(--c-warning)" : "var(--text-3)" },
        title: "Терминология: " + seg.termcheck.findings.map(f =>
          f.tgt_term + (f.suggestion ? " → " + f.suggestion : "") + (f.why ? " (" + f.why + ")" : "")).join("\n")
          + (seg.termcheck.stale ? "\n\nПеревод менялся после проверки — данные устарели." : ""),
      }, (seg.termcheck.stale ? "≈ " : "") + "термин: " + seg.termcheck.findings.length),
      seg.backcheck && seg.backcheck.score != null && React.createElement("div", {
        style: { fontSize: 11, fontWeight: 700, marginTop: 4, whiteSpace: "nowrap",
                 color: window.bcScoreColor(seg.backcheck.score) },
        title: "Соответствие обратного перевода: " + seg.backcheck.score + "%"
          + ((seg.backcheck.reasons || []).length ? "\n" + seg.backcheck.reasons.join("; ") : "")
          + "\nОбратный перевод: " + (seg.backcheck.back || ""),
      }, "↩ " + seg.backcheck.score + "%")),
    React.createElement("td", { onClick: (e) => e.stopPropagation() }, actionCell)
  );
}

function NoProject({ store }) {
  return React.createElement("div", { className: "page" },
    React.createElement(EmptyState, { icon: "folder", title: "Проект не выбран",
      sub: "Импортируйте документ или откройте существующий проект.",
      action: React.createElement(Btn, { variant: "primary", icon: "upload", onClick: () => store.go("import") }, "К импорту") }));
}
window.TabEditor = TabEditor;
