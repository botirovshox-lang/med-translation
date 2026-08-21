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
const RP_MODEL_LS_KEY = "mcat_repair_model";
const JOB_LABELS = { translate: "Перевод", backcheck: "Back-check", termcheck: "Проверка терминологии",
                     repair: "Автоматический ремонт", medical_qa: "Medical QA",
                     full: "Перевод и проверка", apply_terms: "Одобрение и применение" };

// Цвет полосы соответствия обратного перевода
function bandColor(color) {
  return color === "green" ? "var(--c-success)"
    : color === "yellow" ? "var(--c-warning)"
    : color === "orange" ? "var(--c-warning)"
    : "var(--c-error)";
}

// ── Смета прогонов ───────────────────────────────────────────────────
// Кириллица ≈ 2.2 симв./токен, латиница ≈ 3.5. У моделей GPT-5.x в оплачиваемый
// вывод входят ещё и reasoning-токены — отсюда надбавка ×1.8.
// Считается по объёму текста: точную цену знает только ответ модели, поэтому
// везде подписано «ориентировочно». Лучше показать порядок суммы, чем ничего:
// прогон на 2600 сегментов и прогон на 30 отличаются в сто раз.
const REASONING_MULT = 1.8;
const JUDGE_SHARE = 0.3;      // доля сегментов, попадающих в зону судьи (замер на проде)
const EMBED_PRICE = 0.02;     // $/1M токенов, text-embedding-3-small

function reasoning(model) { return model && model.api === "modern" ? REASONING_MULT : 1; }

function priceOf(model, tokIn, tokOut) {
  if (!model) return null;
  return (tokIn / 1e6) * model.in + (tokOut / 1e6) * model.out;
}

// kind: translate | backcheck | termcheck | repair | medical_qa
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
    tokIn = n * 200 + tgtChars / 3.5;          // короткий промпт буквального перевода
    tokOut = (tgtChars / 2.2) * mult;          // обратный перевод на язык оригинала
    cost = priceOf(model, tokIn, tokOut);
    // Судья вызывается только в своей зоне и не вызывается при жёсткой находке
    if (o.judge && o.judgeModel) {
      const jn = n * JUDGE_SHARE;
      cost += priceOf(o.judgeModel, jn * 400 + (srcChars * JUDGE_SHARE) / 1.1,
                      jn * 250 * reasoning(o.judgeModel));
    }
    cost += ((srcChars + tgtChars) / 3 / 1e6) * EMBED_PRICE;   // эмбеддинги
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
    sec = n * EST_SEC_PER_SEG * 2;             // правка + перепроверка
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

// Отмечено по умолчанию: непроверенное, устаревшее и проверенное ДРУГОЙ моделью
// (второе мнение имеет смысл). Проверенное текущей моделью и пропущенные — нет.
function tcGroupDefault(key, model) {
  if (key === "none" || key === "stale") return true;
  const i = key.indexOf(":");
  return i !== -1 && key.slice(i + 1) !== model;
}

// tried приходит с бэкенда: этот же текст уже проходил через ремонт
function rpGroupKey(s) {
  const r = s.repair;
  if (!r) return "none";
  if (!r.tried) return "changed";
  return r.applied ? "applied" : "rejected";
}

function rpGroupDefault(key) { return key === "none" || key === "changed"; }

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
  const [height, setHeight] = useState(440);
  const [selId, setSelId] = useState(project ? (project.segments[0] && project.segments[0].id) : null);
  const [busy, setBusy] = useState({});       // {segId: 'translate'|'qa'}
  const [batchRun, setBatchRun] = useState(null); // {engine, done, total} — производное от job
  const [job, setJob] = useState(null);           // активный серверный прогон
  const lastJobId = useRef(null);                 // чтобы отчитаться о завершении один раз
  const [checkedSegs, setCheckedSegs] = useState(new Set()); // ручной выбор
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(1);
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
  const [rpModel, setRpModel] = useState(() => {
    try { return localStorage.getItem(RP_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [impact, setImpact] = useState(null);     // сегменты, не соответствующие одобренным терминам
  const [impactBusy, setImpactBusy] = useState(false);
  const [impactConfirmed, setImpactConfirmed] = useState(false);  // трогать ли подтверждённые
  const [defModel, setDefModel] = useState("");   // модель перевода по умолчанию (Medical QA берёт её)
  const [bcBands, setBcBands] = useState([]);
  const [bcJudge, setBcJudge] = useState(false);          // LLM-судья для средней зоны
  const [judgeModel, setJudgeModel] = useState(() => {
    try { return localStorage.getItem(JUDGE_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [judgeZone, setJudgeZone] = useState([50, 97]);
  // По умолчанию выключено: back-check ничего не портит, а проверить подтверждённое
  // даже полезнее — если ошибка прошла ревью, узнать об этом важнее всего.
  const [bcSkipConfirmed, setBcSkipConfirmed] = useState(() => {
    try { return localStorage.getItem(BC_SKIP_CONFIRMED_LS_KEY) === "1"; } catch (e) { return false; }
  });
  const [bcGroupPick, setBcGroupPick] = useState(null);   // Set<ключ группы> | null = по умолчанию
  const [tcGroupPick, setTcGroupPick] = useState(null);   // то же для проверки терминологии
  const [rpGroupPick, setRpGroupPick] = useState(null);   // то же для ремонта
  // Составной прогон: какие шаги входят и чем переводить короткие сегменты.
  // null = все шаги; экономия на Google по умолчанию выключена — качество важнее.
  const [fullSteps, setFullSteps] = useState(null);
  const [fullLowGoogle, setFullLowGoogle] = useState(false);
  // Разбор автоодобрения (dry_run): что попадёт в глоссарий и чем это
  // подтверждено. Считает сервер, вызовов модели внутри нет.
  const [autoPreview, setAutoPreview] = useState(null);
  const PAGE_SIZE = 10;

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
      setDefModel(d.default || "");
      if (d.backcheckBands) setBcBands(d.backcheckBands);
      if (d.judgeZone) setJudgeZone(d.judgeZone);
    });
  }, []);

  // Сменились модель, выборка или сам режим — возвращаем выбор групп к умолчанию
  useEffect(() => { setProviderPick(null); },
    [retranslate, gptModel, store.segmentFilter, checkedSegs.size]);
  useEffect(() => { setBcGroupPick(null); },
    [bcModel, bcJudge, bcSkipConfirmed, store.segmentFilter, checkedSegs.size]);
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
        lastJobId.current = null;
        reportJobResult(finished);
        loadImpact();
        loadAutoPreview();      // прогон мог родить новых кандидатов
        const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
        if (!dead && fresh && fresh.segments) store.replaceProjectSegments(project.id, fresh.segments);
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
  const loadImpact = async () => {
    if (!window.API || !window.API.glossaryImpact || !project) return;
    setImpactBusy(true);
    const res = await window.API.safeCall(() => window.API.glossaryImpact(project.id));
    setImpactBusy(false);
    if (res && res.ok) setImpact(res);
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
      project: pid, dry_run: true }));
    if (res && res.ok && store.activeProject && store.activeProject.id === pid) {
      setAutoPreview(res);
    }
  };
  useEffect(() => { setImpact(null); setAutoPreview(null); loadImpact(); loadAutoPreview(); },
    [project && project.id]);

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
  const pickJudgeModel = (id) => {
    setJudgeModel(id);
    try { localStorage.setItem(JUDGE_MODEL_LS_KEY, id); } catch (e) { /* приватный режим — не страшно */ }
  };

  useEffect(() => { setPage(1); }, [filter, query, scope, riskFilter, project && project.id, store.segmentFilter]);
  useEffect(() => { setCheckedSegs(new Set()); }, [project && project.id, store.segmentFilter]);
  useEffect(() => { setSelId(null); }, [page]);

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

  if (!project) return React.createElement(NoProject, { store });

  const counts = store.statusCounts(project);
  const activeFilter = store.segmentFilter || window._mcat_sf || null;
  const filtered = project.segments.filter(s => {
    if (activeFilter && !activeFilter.has(s.id)) return false;
    if (filter !== "all" && s.status !== filter) return false;
    if (riskFilter !== "all" && s.risk !== riskFilter) return false;
    if (query && !segMatches(s, query, scope)) return false;
    return true;
  });
  const selected = project.segments.find(s => s.id === selId);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const curPage = Math.min(page, totalPages);
  const paged = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);
  const wordCount = (arr) => arr.reduce((a, s) => a + (s.source.trim() ? s.source.trim().split(/\s+/).length : 0), 0);
  const charCount = (arr) => arr.reduce((a, s) => a + s.source.length, 0);

  const setSegBusy = (id, kind) => setBusy(b => ({ ...b, [id]: kind }));
  const clearBusy = (id) => setBusy(b => { const n = { ...b }; delete n[id]; return n; });

  const doTranslate = async (seg, engine, force = false) => {
    if (busy[seg.id]) return;
    setSegBusy(seg.id, "translate");
    let result = null;
    if (window.API) {
      result = await window.API.safeCall(() => window.API.translate(project.id, seg.id, engine, force, gptModel));
    }
    if (result && result.segment) {
      store.updateSegment(project.id, seg.id, {
        target: result.segment.target,
        status: result.segment.status,
        route: result.segment.route,
      });
      const label = engine === "gpt" ? (gptModelInfo ? gptModelInfo.label : "GPT") : "Google Translate";
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

  // Приоритет выборки: чекбоксы > активный фильтр анализа > весь проект.
  const hasExplicitCheck = checkedSegs.size > 0;
  const currentIdSet = hasExplicitCheck ? checkedSegs : (store.segmentFilter || window._mcat_sf || null);

  // Ключ группировки «чем переведено». У сегментов, переведённых до появления поля
  // provider, движок известен лишь приблизительно — такие группы идут отдельно (с «≈»),
  // чтобы неточные данные не смешивались с точными.
  const providerKey = (seg) => {
    const p = providerOf(seg);
    return p ? (p.exact ? p.id : "~" + p.id) : "none";
  };

  // Сколько сегментов выборки переведено каким движком — для выбора галочками.
  const providerGroups = (() => {
    if (!retranslate || !currentIdSet) return [];
    const by = new Map();
    project.segments.forEach(s => {
      if (!currentIdSet.has(s.id) || s.status === "confirmed") return;
      const p = providerOf(s);
      const key = providerKey(s);
      const label = p ? ((p.exact ? "" : "≈ ") + providerLabel(p, gptModels)) : "ещё не переведён";
      const g = by.get(key) || { key, label, count: 0, exact: !!(p && p.exact) };
      g.count++;
      by.set(key, g);
    });
    return Array.from(by.values()).sort((a, b) => b.count - a.count);
  })();

  // По умолчанию отмечено всё, кроме уже переведённого выбранной моделью:
  // повторно платить за тот же результат смысла нет, но галочку можно вернуть.
  const pickedProviders = providerPick
    || new Set(providerGroups.filter(g => g.key !== gptModel).map(g => g.key));

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
    if (bcJudge && !bc.judged && bc.score >= judgeZone[0] && bc.score <= judgeZone[1]) return "nojudge";
    return bc.model || "unknown";
  };

  const bcGroupLabel = (key) =>
    key === "none" ? "ещё не проверялся"
      : key === "stale" ? "перевод изменился после проверки"
      : key === "nojudge" ? "проверено без судьи"
      : key === "unknown" ? "проверено (модель неизвестна)"
      : "проверено: " + (providerLabel({ id: key, exact: true }, gptModels) || key);

  // Сколько сегментов выборки в каком состоянии проверки — для выбора галочками.
  // Непроверенное и устаревшее идут первыми: ради них back-check и запускают.
  const bcGroups = (() => {
    const order = { none: 0, stale: 1, nojudge: 2 };
    const rank = (k) => (order[k] === undefined ? 3 : order[k]);
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
  const pickedBcGroups = bcGroupPick
    || new Set(bcGroups.filter(g => g.key !== bcModel).map(g => g.key));

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
    return bcGroupPick ? bcGroupPick.has(key) : key !== bcModel;
  };

  // Один и тот же отбор для счётчика на карточке и для самого пакета — иначе цифры расходятся.
  const pickTargets = (engine, segs) => {
    const idSet = currentIdSet;
    // Галочки и режим «заново» — это явный выбор пользователя, фильтры статуса и риска
    // к нему не применяем. Без выделения «заново» не срабатывает: иначе один клик
    // перегнал бы весь проект целиком.
    const explicit = hasExplicitCheck || (retranslate && !!idSet);
    let targets;
    if (explicit) {
      targets = segs.filter(s => idSet.has(s.id) && s.status !== "confirmed");
      // В режиме «заново» берём только отмеченные группы «чем переведено»
      if (retranslate) targets = targets.filter(s => pickedProviders.has(providerKey(s)));
    } else {
      targets = segs.filter(s =>
        s.status === "new" &&
        (engine === "google" ? s.risk === "low" : s.risk !== "low") &&
        (!idSet || idSet.has(s.id))
      );
    }
    return { targets, explicit, selectionSize: idSet ? idSet.size : 0 };
  };

  // Собрать список целей пакета по свежим данным с бэкенда.
  const collectBatchTargets = async (engine) => {
    let currentSegs = project.segments;
    if (window.API) {
      const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
      if (fresh && fresh.segments) {
        store.replaceProjectSegments(project.id, fresh.segments); // только локальный state
        currentSegs = fresh.segments;
      }
    }
    const { targets, explicit } = pickTargets(engine, currentSegs);
    return { targets, hasExplicitCheck: explicit };
  };

  // Клик по кнопке пакета: Google — сразу, GPT — сначала смета (это платно).
  const askRunBatch = async (engine) => {
    if (batchRun) return;  // не запускать второй пакет поверх незавершённого
    // explicitSel, а не hasExplicitCheck: не путать с одноимённой константой выше
    const { targets, hasExplicitCheck: explicitSel } = await collectBatchTargets(engine);
    if (!targets.length) { toast.warning("Нет подходящих сегментов", "Все сегменты уже переведены или не подходят под фильтр."); return; }
    if (engine === "gpt") setBatchPlan({ engine, targets, hasExplicitCheck: explicitSel });
    else runBatch(engine, targets, explicitSel);
  };

  const runBatch = (engine, targets, hasExplicitCheck) => {
    setBatchPlan(null);
    setCheckedSegs(new Set());
    startJob("translate", targets,
      { engine, force: !!hasExplicitCheck, model: engine === "gpt" ? gptModel : null },
      "Все подходящие сегменты уже переведены.");
  };

  // ── Прогоны ─────────────────────────────────────────────────────
  // Порции крутит сервер (см. фоновые прогоны в main.py). Браузер ставит задачу
  // и опрашивает статус: закрытая вкладка больше не обрывает работу, а вернувшись
  // на страницу, пользователь видит прогресс с того места, где тот сейчас есть.
  const startJob = async (kind, targets, params, emptyMsg) => {
    if (batchRun) { toast.warning("Прогон уже идёт", "Дождитесь окончания или остановите текущий."); return; }
    if (!targets.length) { toast.warning("Нечего запускать", emptyMsg); return; }
    if (!window.API) return;
    const res = await window.API.safeCall(() => window.API.createJob(project.id, kind, targets.map(s => s.id), params));
    if (!res || !res.ok) { toast.error("Не удалось запустить", "Сервер не принял задачу."); return; }
    setJob(res.job);
    toast.info(JOB_LABELS[kind] + ": запущено", targets.length + " сегментов. Можно закрыть вкладку — прогон идёт на сервере.");
  };

  // Итог завершившегося прогона. Отчитываемся по счётчикам, которые вернул сервер:
  // они те же, что раньше собирал браузер, только считать их теперь некому кроме него.
  const reportJobResult = (j) => {
    const c = j.counters || {};
    const name = JOB_LABELS[j.kind] || j.kind;
    const errMsg = c.errors ? " · ошибок: " + c.errors : "";
    const dupMsg = c.duplicates ? " · повторов зачтено без вызова: " + c.duplicates : "";
    if (j.status === "error") {
      // У «Одобрить и применить» глоссарий меняется ДО сегментов. Оборвался
      // ремонт — термины уже записаны, и молчать об этом нельзя: человек должен
      // знать, что откатывать, если результат его не устроил.
      const glossNote = (j.kind === "apply_terms" && c.termsApproved)
        ? " Термины (" + c.termsApproved + ") уже в глоссарии — пачку можно откатить в «Глоссарии»." : "";
      toast.error(name + ": прогон прерван",
        j.done + " из " + j.total + " обработано и сохранено. " + (j.error || "") + glossNote);
      return;
    }
    if (j.status === "stopped") {
      toast.warning(name + ": остановлено", j.done + " из " + j.total + " обработано и сохранено." + errMsg);
      return;
    }
    if (j.kind === "apply_terms") {
      const t = c.termsApproved || 0;
      toast.success("Одобрено и применено",
        t + " терминов в глоссарий (приказом: " + (c.termsVerified || 0) + ")"
        + " · сегментов исправлено: " + (c.applied || 0)
        + (c.reverted ? " · откачено: " + c.reverted : "")
        + (c.skipped_confirmed ? " · подтверждённых не тронуто: " + c.skipped_confirmed : "")
        + errMsg + " · откатить пачку можно в «Глоссарии»");
      return;
    }
    if (j.kind === "full") {
      // Отчитываемся по шагам: «обработано 2670» ничего не говорит о том,
      // что именно произошло, а прогон стоил денег на каждом шаге.
      const part = [
        c.translate ? "переведено " + c.translate : null,
        c.backcheck ? "back-check " + c.backcheck : null,
        c.termcheck ? "термины " + c.termcheck : null,
        c.medical_qa ? "Medical QA " + c.medical_qa : null,
        c.applied ? "исправлено " + c.applied : null,
      ].filter(Boolean).join(" · ") || "нового ничего не потребовалось";
      const blockedMsg = c.step_skips ? " · шаги пропускались (нет ключа или модуля)" : "";
      const skipConfMsg = c.skipped_confirmed ? " · подтверждённых не тронуто: " + c.skipped_confirmed : "";
      toast.success("Перевод и проверка завершены",
        j.done + " сегментов пройдено · " + part + dupMsg + skipConfMsg + blockedMsg + errMsg
        + (c.flagged ? " · замечания в " + c.flagged : ""));
      return;
    }
    if (j.kind === "translate") {
      const tmMsg = c.tm_hits ? " · из TM без вызова: " + c.tm_hits : "";
      // Пропущенные подтверждённые называем вслух: иначе «переведено 0» выглядит
      // как поломка, хотя сервер просто не тронул заверенное человеком.
      const skipMsg = c.skipped_confirmed ? " · пропущено подтверждённых: " + c.skipped_confirmed : "";
      toast.success("Перевод завершён", j.done + " сегментов переведено" + tmMsg + dupMsg + skipMsg + errMsg);
    } else if (j.kind === "termcheck") {
      const skipMsg = c.skipped_trivial ? " · без вызова модели: " + c.skipped_trivial : "";
      if (c.flagged) toast.warning("Проверка терминологии завершена",
        "Замечания в " + c.flagged + " из " + j.done + " сегментов" + dupMsg + skipMsg + errMsg
        + " · предложения замены — в «Глоссарий → Кандидаты»");
      else toast.success("Проверка терминологии завершена", j.done + " сегментов без замечаний" + dupMsg + skipMsg + errMsg);
    } else if (j.kind === "repair") {
      const revMsg = c.reverted ? " · откачено (не стало лучше): " + c.reverted : "";
      if (c.applied) toast.success("Ремонт завершён",
        "Исправлено " + c.applied + " сегментов" + revMsg + errMsg + " · статус «Требует проверки», подтвердите вручную");
      else toast.warning("Ничего не исправлено", "Ни один вариант не улучшил оценку — все откачены." + errMsg);
    } else if (j.kind === "backcheck") {
      toast.success("Back-check завершён", j.done + " сегментов проверено" + dupMsg + errMsg + " · разбивка в Анализе");
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
      { engine: "gpt", force: true, model: gptModel, include_confirmed: !!impactConfirmed },
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
    startJob("backcheck", project.segments.filter(s => backcheckable(s, currentIdSet)),
      { model: bcModel || null, use_judge: bcJudge, judge_model: judgeModel || null, skip_cached: false },
      bcSkipConfirmed
        ? "В выборке нет непроверенных сегментов, кроме подтверждённых, а их вы просили пропускать."
        : "В выборке нет непроверенных сегментов. Отметьте нужные группы в «Что проверять».");
  };

  const runTermcheckBatch = () => {
    startJob("termcheck", project.segments.filter(s => termcheckable(s, currentIdSet)),
      { model: tcModel || null, skip_cached: false },
      "Всё в выборке уже проверено этой моделью. Отметьте нужные группы в «Что проверять», чтобы прогнать заново.");
  };

  const runRepairBatch = () => {
    startJob("repair", project.segments.filter(s => repairable(s, currentIdSet)),
      { model: rpModel || null, bc_model: bcModel || null, tc_model: tcModel || null,
        use_judge: bcJudge, judge_model: judgeModel || null, retry: repairRetry() },
      rpGroups.length
        ? "Все сегменты с находками уже проходили ремонт. Отметьте нужные группы в «Что чинить»."
        : "Нет сегментов с проверяемыми находками. Сначала прогоните back-check или проверку терминологии.");
  };

  const runMedicalQABatch = () => {
    const idSet = currentIdSet;
    startJob("medical_qa", project.segments.filter(s =>
      s.target && s.target.trim() &&
      ["translated", "qa", "review", "confirmed"].includes(s.status) &&
      (!idSet || idSet.has(s.id))),
      {}, "Нет переведённых сегментов для пакетной проверки.");
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
  const tcDefaultPicked = (key) => tcGroupDefault(key, tcModel);
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
  const impactRepairIds = new Set((impact && impact.pending) || []);
  const rpCandidate = (s, idSet) => {
    if (!(s.target && s.target.trim())) return false;
    if (idSet && !idSet.has(s.id)) return false;
    const bc = s.backcheck && !s.backcheck.stale ? s.backcheck : null;
    const tc = s.termcheck && !s.termcheck.stale ? s.termcheck : null;
    const bcHit = bc && ((bc.terms_lost || []).length > 0
      || (bc.reasons || []).some(r => REPAIR_REASONS.some(h => r.indexOf(h) !== -1))
      || (bc.judge && ["major", "critical"].indexOf(bc.judge.severity) !== -1));
    const tcHit = tc && (tc.findings || []).some(f => f.severity === "critical" || f.severity === "major");
    return !!(bcHit || tcHit || impactRepairIds.has(s.id));
  };

  // tried приходит с бэкенда: этот же текст уже проходил через ремонт
  const rpGroupLabel = (key) =>
    key === "none" ? "ремонт не запускался"
      : key === "changed" ? "текст менялся после прошлого ремонта"
      : key === "applied" ? "уже чинилось, замечания остались"
      : "правка была откачена (не стало лучше)";

  const rpGroups = (() => {
    const order = { none: 0, changed: 1, applied: 2, rejected: 3 };
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

  /* ── Составной прогон: весь конвейер одной кнопкой ────────────────────
     Список сегментов у прогона ОДИН, а отбирает под себя каждый шаг сам —
     теми же предикатами, что и отдельные карточки. Поэтому счётчики здесь
     и там не разойдутся, а состав по-прежнему выбирается галочками
     и фильтром: за экономию отвечает отбор, а не отказ от проверок. */
  const FULL_STEPS = [
    ["translate", "Перевод", "только те, что ещё не переведены"],
    ["backcheck", "Back-check", "обратный перевод другой моделью"],
    ["termcheck", "Термины", "третья модель смотрит только на результат"],
    ["medical_qa", "Medical QA", "числа, единицы, отрицания — без вызова модели"],
    ["repair", "Ремонт", "правит по всем находкам, включая глоссарий"],
  ];
  const fullScope = project.segments.filter(s => !currentIdSet || currentIdSet.has(s.id));
  const fullStepTargets = {
    translate: fullScope.filter(s => s.status === "new"),
    backcheck: fullScope.filter(s => backcheckable(s, currentIdSet)),
    termcheck: fullScope.filter(s => termcheckable(s, currentIdSet)),
    medical_qa: fullScope.filter(s => s.target && s.target.trim()
      && ["translated", "qa", "review", "confirmed"].includes(s.status)),
    repair: fullScope.filter(s => repairable(s, currentIdSet)),
  };
  const pickedFull = fullSteps || new Set(FULL_STEPS.map(s => s[0]));
  // Серверу отдаём ОБЪЕДИНЕНИЕ сегментов выбранных шагов, а не всё подряд:
  // счётчики и смета выше посчитаны по этим же спискам, а они учитывают
  // галочки «что проверять» и «что чинить». Отправив весь проект, мы бы
  // молча выбросили этот выбор — и прогон стоил бы кратно дороже сметы.
  const fullRunIds = (() => {
    const ids = new Set();
    FULL_STEPS.forEach(([k]) => {
      if (pickedFull.has(k)) (fullStepTargets[k] || []).forEach(s => ids.add(s.id));
    });
    return project.segments.filter(s => ids.has(s.id));
  })();
  const toggleFullStep = (key) => setFullSteps(prev => {
    const next = new Set(prev || pickedFull);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  // Смета — сумма смет по шагам, каждая своей моделью. Показываем до запуска:
  // составной прогон дороже одиночного, и узнавать об этом постфактум нельзя.
  const fullEst = (() => {
    // Сегменты, которые прогон переведёт, в ТОЙ ЖЕ порции пойдут в проверки —
    // а сейчас они пустые и ни в один список проверок не попадают. Без этой
    // добавки непереведённый проект показывал бы цену одного перевода, хотя
    // платить придётся ещё и за все проверки поверх него.
    const willTranslate = pickedFull.has("translate") ? fullStepTargets.translate : [];
    const plus = (list) => {
      const has = new Set(list.map(s => s.id));
      return list.concat(willTranslate.filter(s => !has.has(s.id)));
    };
    const parts = [
      pickedFull.has("translate") && estimateRun("translate", fullStepTargets.translate, gptModelInfo),
      pickedFull.has("backcheck") && estimateRun("backcheck", plus(fullStepTargets.backcheck), bcModelInfo,
        { judge: bcJudge, judgeModel: judgeModelInfo }),
      pickedFull.has("termcheck") && estimateRun("termcheck", plus(fullStepTargets.termcheck),
        gptModels.find(m => m.id === tcModel) || null),
      pickedFull.has("medical_qa") && estimateRun("medical_qa",
        plus(fullStepTargets.medical_qa.filter(s => !(s.backcheck && !s.backcheck.stale && s.backcheck.back))),
        gptModels.find(m => m.id === defModel) || null),
      pickedFull.has("repair") && estimateRun("repair", plus(fullStepTargets.repair),
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

  // Проверка, которую делает та же модель, что переводила, — не независимая,
  // а на независимости стоит автоодобрение терминов. Молчать об этом нельзя.
  const sameModelWarn = [bcModel, tcModel].filter(m => m && m === gptModel).length > 0;

  const runFullJob = () => {
    const steps = FULL_STEPS.map(s => s[0]).filter(k => pickedFull.has(k));
    if (!steps.length) { toast.warning("Не выбрано ни одного шага", "Отметьте хотя бы один."); return; }
    startJob("full", fullRunIds, {
      steps,
      // auto: движок выбирается по длине сегмента. low_engine=gpt — «всё модели»,
      // то есть качество; google экономит на коротких строках.
      engine: "auto", low_engine: fullLowGoogle ? "google" : "gpt",
      model: gptModel, bc_model: bcModel, tc_model: tcModel,
      rp_model: rpModel, use_judge: bcJudge, judge_model: judgeModel || null,
      // Тот же retry, что и у карточки ремонта: карточка выше посчитала
      // и оценила сегменты по этому же правилу, и разойтись они не должны.
      retry: repairRetry(),
    }, "В выбранных сегментах нечего делать.");
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
        // Поиск: отдельно по оригиналу и отдельно по переводу — искать
        // английский термин по русскому тексту бессмысленно и наоборот.
        React.createElement("div", { className: "row", style: { gap: 8, flex: "1 1 380px", justifyContent: "flex-end" } },
          React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value),
            placeholder: searchPlaceholder }),
          React.createElement(Select, { value: scope, onChange: (e) => pickScope(e.target.value), style: { width: "auto", flex: "0 0 auto" }, "aria-label": "Где искать" },
            scopeOpts.map(([v, l]) => React.createElement("option", { key: v, value: v }, l))),
          query && React.createElement(IconBtn, { icon: "close", label: "Очистить поиск", sm: true, onClick: () => setQuery("") }),
          query && React.createElement("span", { className: "dim", style: { fontSize: 12, whiteSpace: "nowrap" } },
            filtered.length ? "найдено: " + filtered.length : "ничего не найдено")
        )
      ),
      showFilters && React.createElement("div", { className: "row row-wrap", style: { gap: 14, padding: "4px 2px" } },
        React.createElement(Select, { value: riskFilter, onChange: (e) => setRiskFilter(e.target.value), style: { width: 200 } },
          [["all", "Любой риск"], ["low", "Низкий риск"], ["medium", "Средний риск"], ["high", "Высокий риск"], ["critical", "Критический риск"]]
            .map(([v, l]) => React.createElement("option", { key: v, value: v }, l)))
      )
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

    // ---- Идущий серверный прогон: виден и после перезагрузки страницы ----
    job && React.createElement("div", { className: "editor-main", style: { paddingBottom: 0 } },
      React.createElement("div", { className: "card", style: { padding: "10px 14px", background: "var(--bg-sunken)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" } },
        React.createElement("div", { className: "row", style: { gap: 10, flex: "1 1 320px" } },
          React.createElement(Spinner, null),
          React.createElement("div", { style: { flex: 1 } },
            React.createElement("div", { style: { fontSize: 13, fontWeight: 600 } },
              (JOB_LABELS[job.kind] || job.kind) + " — "
              + (job.stopping ? "останавливается" : job.status === "queued" ? "в очереди" : "идёт на сервере")
              + ": " + job.done + " из " + job.total),
            React.createElement(ProgressBar, { value: Math.round(job.done / Math.max(1, job.total) * 100) }),
            React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: 4 } },
              "Вкладку можно закрыть — прогон продолжится, прогресс подхватится при возвращении"))),
        React.createElement(Btn, { variant: "ghost", size: "sm", onClick: stopJob, disabled: !!job.stopping },
          job.stopping ? "Останавливаем…" : "Остановить"))
    ),

    // ---- Составной прогон: одна кнопка на весь конвейер ----
    React.createElement("div", { className: "editor-main", style: { paddingBottom: 0 } },
      React.createElement(FullRunCard, {
        running: job && job.kind === "full" ? job : null,
        onRun: runFullJob, onStop: stopJob,
        steps: FULL_STEPS, picked: pickedFull, onToggle: toggleFullStep,
        targets: fullStepTargets, scopeSize: fullRunIds.length,
        checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf),
        est: fullEst, sameModelWarn: sameModelWarn,
        transModel: (gptModelInfo || {}).label || gptModel,
        checkModels: [bcModelInfo, gptModels.find(m => m.id === tcModel)]
          .filter(Boolean).map(m => m.label),
        lowGoogle: fullLowGoogle, onLowGoogle: () => setFullLowGoogle(v => !v),
        disabled: !!job }),
      React.createElement(ApplyTermsCard, {
        running: job && job.kind === "apply_terms" ? job : null,
        onRun: runApplyTerms, onStop: stopJob, disabled: !!job,
        preview: autoPreview, sources: autoPreview && autoPreview.sources,
        includeConfirmed: impactConfirmed,
        onIncludeConfirmed: () => setImpactConfirmed(v => !v),
        confirmedCount: impact ? impact.confirmed.length : 0 }),
      React.createElement(Expander, { title: "Отдельные прогоны", icon: "zap", right: "по одному шагу — для точечной работы", defaultOpen: false },
        React.createElement("div", { className: "grid grid-3" },
          React.createElement(BatchCard, { kind: "google", est: estimateRun("translate", pickTargets("google", project.segments).targets, null), running: batchRun && batchRun.engine === "google" ? batchRun : null, onRun: () => askRunBatch("google"), onStop: stopJob,
            available: pickTargets("google", project.segments).targets.length,
            selectionSize: pickTargets("google", project.segments).selectionSize,
            checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf) }),
          React.createElement(BatchCard, { kind: "gpt", est: estimateRun("translate", pickTargets("gpt", project.segments).targets, gptModelInfo), running: batchRun && batchRun.engine === "gpt" ? batchRun : null, onRun: () => askRunBatch("gpt"), onStop: stopJob,
            models: gptModels, model: gptModel, modelInfo: gptModelInfo, onModel: pickGptModel,
            available: pickTargets("gpt", project.segments).targets.length,
            selectionSize: pickTargets("gpt", project.segments).selectionSize,
            checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf) }),
          React.createElement(MedicalQACard, { running: batchRun && batchRun.engine === "medical_qa" ? batchRun : null, onRun: runMedicalQABatch,
            // Свежий back-check переиспользуется, такие сегменты в смету не идут
            est: estimateRun("medical_qa", project.segments.filter(s => s.target && s.target.trim()
              && ["translated", "qa", "review", "confirmed"].includes(s.status)
              && (checkedSegs.size > 0 ? checkedSegs.has(s.id) : (!store.segmentFilter || store.segmentFilter.has(s.id)))
              && !(s.backcheck && !s.backcheck.stale && s.backcheck.back)),
              gptModels.find(m => m.id === defModel) || null),
            available: project.segments.filter(s => s.target && s.target.trim() && ["translated", "qa", "review", "confirmed"].includes(s.status) && (checkedSegs.size > 0 ? checkedSegs.has(s.id) : (!store.segmentFilter || store.segmentFilter.has(s.id)))).length,
            checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf) }),
          impact && impact.terms.length > 0 && React.createElement(GlossaryImpactCard, {
            impact, busy: impactBusy, onRefresh: loadImpact,
            includeConfirmed: impactConfirmed, onIncludeConfirmed: () => setImpactConfirmed(v => !v),
            onRun: runImpactRetranslate,
            onDrill: (ids) => { store.setSegmentFilter(ids); setPage(1); },
            est: estimateRun("translate", project.segments.filter(s =>
              new Set(impactConfirmed ? impact.segments : impact.pending).has(s.id)), gptModelInfo),
            running: batchRun && batchRun.engine === "translate" ? batchRun : null }),
          React.createElement(TermCheckCard, {
            running: batchRun && batchRun.engine === "termcheck" ? batchRun : null,
            onRun: runTermcheckBatch, onStop: stopJob,
            models: gptModels, model: tcModel, modelInfo: gptModels.find(m => m.id === tcModel) || null,
            onModel: pickTcModel,
            available: project.segments.filter(s => termcheckable(s, currentIdSet)).length,
            flagged: project.segments.filter(s => s.termcheck && !s.termcheck.stale
              && (s.termcheck.findings || []).length).length,
            groups: tcGroups, pickedGroups: pickedTcGroups, onToggleGroup: toggleTcGroup,
            est: estimateRun("termcheck", project.segments.filter(s => termcheckable(s, currentIdSet)), gptModels.find(m => m.id === tcModel) || null),
            checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf) }),
          React.createElement(RepairCard, {
            running: batchRun && batchRun.engine === "repair" ? batchRun : null,
            onRun: runRepairBatch, onStop: stopJob,
            models: gptModels, model: rpModel, modelInfo: gptModels.find(m => m.id === rpModel) || null,
            onModel: pickRpModel,
            available: project.segments.filter(s => repairable(s, currentIdSet)).length,
            repaired: project.segments.filter(s => s.repair && s.repair.applied).length,
            groups: rpGroups, pickedGroups: pickedRpGroups, onToggleGroup: toggleRpGroup,
            est: estimateRun("repair", project.segments.filter(s => repairable(s, currentIdSet)),
              gptModels.find(m => m.id === rpModel) || null, { recheckModel: bcModelInfo }),
            checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf) }),
          React.createElement(BackcheckCard, {
            running: batchRun && batchRun.engine === "backcheck" ? batchRun : null,
            onRun: runBackcheckBatch, onStop: stopJob,
            models: gptModels, model: bcModel, modelInfo: bcModelInfo, onModel: pickBcModel,
            judge: bcJudge, onJudge: () => setBcJudge(v => !v),
            judgeModel: judgeModel, judgeModelInfo: judgeModelInfo, onJudgeModel: pickJudgeModel,
            judgeZone: judgeZone,
            est: estimateRun("backcheck", project.segments.filter(s => backcheckable(s, currentIdSet)), bcModelInfo,
              { judge: bcJudge, judgeModel: judgeModelInfo }),
            available: project.segments.filter(s => backcheckable(s, currentIdSet)).length,
            done: project.segments.filter(s => bcCandidate(s, currentIdSet) && s.backcheck
              && s.backcheck.score != null && !s.backcheck.stale).length,
            groups: bcGroups, pickedGroups: pickedBcGroups, onToggleGroup: toggleBcGroup,
            skipConfirmed: bcSkipConfirmed, onSkipConfirmed: toggleBcSkipConfirmed,
            confirmedCount: project.segments.filter(s => s.status === "confirmed" &&
              (s.target || "").trim() && (!currentIdSet || currentIdSet.has(s.id))).length,
            filtered: !!(store.segmentFilter || window._mcat_sf) })
        ),
        // Переводить заново уже переведённые. Работает только по явной выборке —
        // галочки или фильтр из Анализа, — чтобы одним кликом не перегнать весь проект.
        React.createElement("div", { className: "row between", style: { marginTop: 12, gap: 12, flexWrap: "wrap" } },
          React.createElement("div", null,
            React.createElement("div", { style: { fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center" } },
              "Переводить заново уже переведённые",
              React.createElement(InfoTip, { title: "Повторный перевод",
                body: "По умолчанию пакет берёт только сегменты со статусом «Новый». Включите, чтобы перегнать выбранные заново — например, чтобы перевести моделью получше то, что уже переведено. Подтверждённые сегменты не трогаются никогда, точное совпадение с памятью переводов при этом не подставляется. Старый перевод перезаписывается." })),
            React.createElement("div", { className: "dim", style: { fontSize: 12 } },
              (store.segmentFilter || window._mcat_sf || checkedSegs.size > 0)
                ? "Применится к текущей выборке"
                : "Нужна выборка: галочки или фильтр из Анализа")),
          React.createElement(Switch, { on: retranslate, label: "Переводить заново",
            onClick: () => setRetranslate(v => !v) })
        ),

        // Что именно перегонять: группы «чем переведено сейчас» с количеством.
        // По умолчанию снята галочка с того, что уже переведено выбранной моделью.
        retranslate && currentIdSet && React.createElement("div", {
          className: "card", style: { padding: "10px 14px", marginTop: 10, background: "var(--bg-sunken)" } },
          React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, marginBottom: 8 } },
            "Сейчас переведено через — отметьте, что перевести заново:"),
          providerGroups.length === 0
            ? React.createElement("div", { className: "dim", style: { fontSize: 12 } },
                "В выборке нет сегментов для повторного перевода (все подтверждены).")
            : providerGroups.map(g => React.createElement("div", {
                key: g.key, className: "row between", style: { padding: "3px 0" } },
                React.createElement(Checkbox, {
                  checked: pickedProviders.has(g.key),
                  onChange: () => toggleProvider(g.key),
                }, g.label + (g.exact ? "" : " (определено по маршруту)")),
                React.createElement("b", { style: { fontSize: 13 } }, g.count))),
          providerGroups.length > 0 && React.createElement("div", {
            className: "dim", style: { fontSize: 11.5, marginTop: 8, borderTop: "1px solid var(--border)", paddingTop: 8 } },
            "Отмечено к переводу: " + providerGroups.filter(g => pickedProviders.has(g.key))
              .reduce((a, g) => a + g.count, 0) + " из " +
              providerGroups.reduce((a, g) => a + g.count, 0))
        )
      )
    ),

    // ---- Body: table + detail ----
    React.createElement("div", { className: "editor-body" },
      React.createElement("div", { className: "editor-main" },
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
                React.createElement("th", { style: { width: 60 }, title: "TM match %" }, "TM%"),
                React.createElement("th", { style: { width: 56 } }, "")
              )),
              React.createElement("tbody", null,
                paged.map(s => React.createElement(SegRow, {
                  key: s.id, seg: s, selected: s.id === selId, busy: busy[s.id],
                  checked: checkedSegs.has(s.id), models: gptModels,
                  hlSrc: scope !== "tgt" ? query : "", hlTgt: scope !== "src" ? query : "",
                  onCheck: (e) => { e.stopPropagation(); setCheckedSegs(prev => { const n = new Set(prev); n.has(s.id) ? n.delete(s.id) : n.add(s.id); return n; }); },
                  onSelect: () => setSelId(s.id),
                  onTranslate: () => doTranslate(s, s.risk === "low" ? "google" : "gpt"),
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
              onTranslate: (eng) => doTranslate(selected, eng, true), onQA: () => doQA(selected), onMedicalQA: () => doMedicalQA(selected), onConfirm: (draftTarget) => doConfirm(selected, draftTarget),
              bcModels: gptModels, bcModel: bcModel, onBcModel: pickBcModel,
              bcJudge: bcJudge, judgeModel: judgeModel,
              tcModel: tcModel, rpModel: rpModel })
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
            onClick: () => runBatch(batchPlan.engine, batchPlan.targets, batchPlan.hasExplicitCheck) }, "Запустить")) },
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
function FullRunCard({ running, onRun, onStop, steps, picked, onToggle, targets, scopeSize,
                       checked, filtered, est, sameModelWarn, transModel, checkModels,
                       lowGoogle, onLowGoogle, disabled }) {
  const anyWork = steps.some(([k]) => picked.has(k) && (targets[k] || []).length > 0);
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 13, marginBottom: 14, borderLeft: "3px solid var(--c-primary)" } },

    React.createElement("div", { className: "row between row-wrap", style: { gap: 10 } },
      React.createElement("div", { className: "row", style: { gap: 10 } },
        React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-primary)" } },
          React.createElement(Icon, { name: "zap", size: 19 })),
        React.createElement("div", null,
          React.createElement("div", { style: { fontWeight: 650, fontSize: 15, display: "flex", alignItems: "center" } }, "Перевести и проверить",
            React.createElement(InfoTip, { title: "Что делает эта кнопка",
              body: "Один прогон вместо пяти: перевод → back-check → проверка терминов → Medical QA → ремонт. Порядок фиксирован и важен: Medical QA берёт готовый обратный перевод из back-check и не платит за него второй раз, терминологию в глоссарий собирает та из двух проверок, что отработала второй, а ремонту нужны находки всех предыдущих шагов.\n\nПереводит одна модель, проверяют другие — в этом весь смысл: проверка, сделанная той же моделью, что и перевод, независимой не является.\n\nКаждый шаг отбирает сегменты сам, теми же правилами, что и отдельные карточки: уже переведённое не переводится заново, свежая проверка не оплачивается второй раз. Чтобы сузить прогон, отметьте сегменты галочками или включите фильтр.\n\nПрогон идёт на сервере — вкладку можно закрыть." })),
          React.createElement("div", { className: "dim", style: { fontSize: 12 } },
            "переводит " + (transModel || "—")
            + (checkModels.length ? " · проверяют " + checkModels.join(" и ") : "")))),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } },
        "в работу пойдут " + scopeSize + " сегм."
        + (checked > 0 ? " · по галочкам" : filtered ? " · по фильтру" : ""))),

    sameModelWarn && React.createElement("div", { style: { fontSize: 12.5, lineHeight: 1.5, color: "var(--c-warning)", background: "var(--bg-sunken)", padding: "8px 11px", borderRadius: 8 } },
      "Перевод и проверку делает одна модель. Она не найдёт собственную ошибку — "
      + "выберите для back-check или терминов другую модель в «Отдельных прогонах»."),

    React.createElement("div", { className: "col", style: { gap: 6 } },
      steps.map(([key, label, hint]) => {
        const n = (targets[key] || []).length;
        const on = picked.has(key);
        return React.createElement("div", { key: key, className: "row between", style: { gap: 10, fontSize: 13, opacity: on ? 1 : 0.5 } },
          React.createElement(Checkbox, { checked: on, onChange: () => onToggle(key) },
            React.createElement("span", null,
              React.createElement("b", { style: { fontWeight: 600 } }, label),
              React.createElement("span", { className: "dim", style: { fontSize: 12 } }, " — " + hint))),
          React.createElement("span", { style: { fontVariantNumeric: "tabular-nums", fontWeight: 600, color: n ? "var(--text-1)" : "var(--text-3)" } },
            n ? n + " сегм." : "нечего"));
      })),

    React.createElement("div", { className: "row", style: { gap: 8, alignItems: "center" } },
      React.createElement(Switch, { on: lowGoogle, label: "Короткие через Google", onClick: onLowGoogle }),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } },
        lowGoogle ? "дешевле, но короткие строки переводит не модель" : "всё переводит модель")),

    React.createElement(EstLine, { est }),
    React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: -6 } },
      "Смета сверху: проверки посчитаны и по тем сегментам, что будут переведены в этом же прогоне."),

    running
      ? React.createElement("div", null,
          React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
            React.createElement("span", { className: "muted" }, "Идёт полный прогон…"),
            React.createElement("span", { style: { fontWeight: 700 } }, Math.round(running.done) + "/" + running.total)),
          React.createElement(ProgressBar, { value: Math.round(running.done / Math.max(1, running.total) * 100) }),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: onStop, style: { marginTop: 8 } }, "Остановить"))
      : React.createElement(Btn, { variant: "primary", icon: "zap", onClick: onRun, disabled: disabled || !anyWork },
          anyWork ? "Перевести и проверить" : "Всё уже сделано"));
}

/* Второй клик конвейера. Одобряет однозначные термины пачкой и тут же чинит
   ими сегменты. Состав сегментов не выбирается намеренно: пока термины не
   одобрены, неизвестно, какие сегменты с ними разойдутся — список считает
   сервер сразу после одобрения. */
function ApplyTermsCard({ running, onRun, onStop, disabled, preview, sources,
                          includeConfirmed, onIncludeConfirmed, confirmedCount }) {
  const c = preview && preview.counts;
  const ready = c ? (c.auto || 0) + (c.verified || 0) : 0;
  const dicts = (sources && sources.dictionaries) || [];
  const corpus = sources && sources.corpus;
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12, marginBottom: 14, borderLeft: "3px solid var(--c-success)" } },

    React.createElement("div", { className: "row between row-wrap", style: { gap: 10 } },
      React.createElement("div", { className: "row", style: { gap: 10 } },
        React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-success)" } },
          React.createElement(Icon, { name: "check", size: 19 })),
        React.createElement("div", null,
          React.createElement("div", { style: { fontWeight: 650, fontSize: 15, display: "flex", alignItems: "center" } }, "Одобрить и применить",
            React.createElement(InfoTip, { title: "Что делает эта кнопка",
              body: "Однозначные термины уходят в глоссарий пачкой, а затем сегменты чинятся по ним: расхождение с утверждённым термином — такая же находка ремонта, как потерянный термин или расхождение чисел.\n\nЧто считается однозначным: у термина ровно один вариант перевода; пара пришла из нескольких независимых сегментов, прошедших back-check и проверку терминов чисто; перевод встречается в текстах целевого языка.\n\nПриказом («use these exact translations») запись становится от человека, от трёх независимых чистых сегментов или от совпадения с отраслевым справочником. В медицине, фармацевтике и юриспруденции согласия сегментов для приказа НЕ хватает — там приказ даёт только человек или справочник.\n\nЛюбую пачку можно откатить целиком в «Глоссарии»." })),
          React.createElement("div", { className: "dim", style: { fontSize: 12 } },
            "термины в глоссарий → ремонт по ним → перепроверка"))),
      React.createElement("span", { style: { fontVariantNumeric: "tabular-nums", fontWeight: 700, fontSize: 18, color: ready ? "var(--c-success)" : "var(--text-3)" } },
        ready)),

    // Чем проверялись термины. Покрытие по парам языков очень разное, и разницу
    // честнее назвать, чем дать пользователю обнаружить её на своих текстах.
    React.createElement("div", { className: "dim", style: { fontSize: 12, lineHeight: 1.6 } },
      "Проверяют: ",
      dicts.length
        ? dicts.map(d => d.label + " (" + d.terms + ")").join(" · ")
        : "справочников для этой пары языков нет",
      corpus ? " · корпус " + corpus.label : " · корпус недоступен",
      preview && preview.corpusSkipped
        ? " · сверх потолка не проверено: " + preview.corpusSkipped : ""),

    // Цифра выше посчитана ДО обращения к корпусу: спрашивать его при каждом
    // открытии проекта — это минута ожидания на лимитах источника. При нажатии
    // он отработает, и часть кандидатов может отсеяться как отсутствующие
    // в целевом языке. Обещать больше, чем сделаем, нельзя.
    preview && preview.corpusPending && corpus && React.createElement("div",
      { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
      "Это верхняя оценка: проверку по " + corpus.label
      + " прогон сделает при нажатии, и калек в списке станет меньше."),

    c && c.skipped > 0 && React.createElement("div", { className: "dim", style: { fontSize: 12.5 } },
      "останется человеку: ", React.createElement("b", null, c.skipped),
      " — разобрать в «Глоссарии»"),

    confirmedCount > 0 && React.createElement(Checkbox, {
      checked: !!includeConfirmed, onChange: onIncludeConfirmed },
      "Чинить и подтверждённые (" + confirmedCount + ")"),

    running
      ? React.createElement("div", null,
          React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
            React.createElement("span", { className: "muted" },
              running.total ? "Применяем к сегментам…" : "Одобряем термины…"),
            React.createElement("span", { style: { fontWeight: 700 } },
              Math.round(running.done) + "/" + Math.max(1, running.total))),
          React.createElement(ProgressBar, { value: Math.round(running.done / Math.max(1, running.total) * 100) }),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: onStop, style: { marginTop: 8 } }, "Остановить"))
      : React.createElement(Btn, { variant: "primary", icon: "check", onClick: onRun, disabled: disabled || !ready },
          ready ? "Одобрить " + ready + " и применить" : "Однозначных терминов нет"));
}

function BatchCard({ kind, running, onRun, onStop, available, selectionSize, filtered, checked, models, model, modelInfo, onModel, est }) {
  const meta = kind === "google"
    ? { icon: "globe", title: "Google Batch", sub: "Низкорисковые сегменты", note: "Для простых, шаблонных формулировок.", color: "var(--c-warning)", btn: "Запустить Google",
        tipTitle: "Запустить Google batch", tip: "Перевести все GOOGLE_SAFE сегменты через Google Translate. Результат сохраняется как 'google_draft' (не подтверждён)." }
    : { icon: "cpu", title: "GPT Batch", sub: "Сложный контент", note: "Для клинических и неоднозначных формулировок.", color: "var(--c-purple)", btn: "Запустить GPT",
        tipTitle: "Запустить GPT batch", tip: "Перевод через OpenAI GPT с QA и применением глоссария. Результат: status='translated', provider='openai'." };
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: meta.color } },
        React.createElement(Icon, { name: meta.icon, size: 19 })),
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, meta.title, React.createElement(InfoTip, { title: meta.tipTitle, body: meta.tip })),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, meta.sub))
    ),
    React.createElement("p", { className: "muted", style: { fontSize: 13, margin: 0 } }, meta.note),

    // Выбор модели — только у GPT-карточки и только если бэкенд отдал каталог
    kind === "gpt" && models && models.length > 0 && React.createElement("div", null,
      React.createElement(Select, {
        value: model || "", disabled: !!running, style: { width: "100%" },
        onChange: (e) => onModel && onModel(e.target.value),
      }, models.map(m => React.createElement("option", { key: m.id, value: m.id },
        m.label + (m.note ? " — " + m.note : "")))),
      modelInfo && React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: 5 } },
        "Цена за 1M токенов: вход " + fmtCost(modelInfo.in) + " · выход " + fmtCost(modelInfo.out))
    ),

    React.createElement(EstLine, { est }),
    running
      ? React.createElement("div", null,
          React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
            React.createElement("span", { className: "muted" }, "Перевод…"),
            React.createElement("span", { style: { fontWeight: 700 } }, Math.floor(running.done) + "/" + running.total)),
          React.createElement(ProgressBar, { value: Math.round(running.done / running.total * 100) }),
          React.createElement("div", { className: "row", style: { justifyContent: "flex-end", marginTop: 8 } },
            React.createElement(Btn, { variant: "ghost", size: "sm", icon: "x", onClick: onStop }, "Остановить")))
      : React.createElement("div", { className: "row between" },
          React.createElement("span", { className: "dim", style: { fontSize: 12 } },
            // При нуле объясняем причину: «0 доступно (фильтр)» не говорит, почему именно ноль
            available === 0 && selectionSize > 0
              ? "0 новых из " + selectionSize + " в выборке"
              : available + " доступно" + (checked > 0 ? " (" + checked + " выбрано)" : filtered ? " (фильтр)" : "")),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "zap", onClick: onRun, disabled: !available }, meta.btn))
  );
}

function BackcheckCard({ running, onRun, onStop, available, done, filtered, models, model, modelInfo, onModel,
                        judge, onJudge, judgeModel, judgeModelInfo, onJudgeModel, judgeZone,
                        skipConfirmed, onSkipConfirmed, confirmedCount,
                        groups, pickedGroups, onToggleGroup, est }) {
  const zone = judgeZone || [50, 97];
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-info)" } },
        React.createElement(Icon, { name: "repeat", size: 19 })),
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, "Back-check",
          React.createElement(InfoTip, { title: "Обратный перевод и оценка соответствия",
            body: "Переводит готовый перевод обратно на язык оригинала и сравнивает с исходным текстом: числа, единицы, отрицания, лево-право, сохранность терминов. Выдаёт процент соответствия, разбивка по полосам — во вкладке «Анализ». Для обратного перевода нужна самая буквальная модель: умная незаметно чинит ошибки и прячет их от проверки. Повторный запуск считает только то, где перевод менялся." })),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, "Контроль качества перевода"))
    ),
    React.createElement("p", { className: "muted", style: { fontSize: 13, margin: 0 } },
      "Проверяет, что смысл пережил перевод."),
    models && models.length > 0 && React.createElement("div", null,
      React.createElement(Select, {
        value: model || "", disabled: !!running, style: { width: "100%" },
        onChange: (e) => onModel && onModel(e.target.value),
      }, models.map(m => React.createElement("option", { key: m.id, value: m.id },
        m.label + (m.note ? " — " + m.note : "")))),
      modelInfo && React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: 5 } },
        "Цена за 1M токенов: вход " + fmtCost(modelInfo.in) + " · выход " + fmtCost(modelInfo.out))),

    React.createElement("div", { className: "row between", style: { gap: 10 } },
      React.createElement("div", null,
        React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, display: "flex", alignItems: "center" } },
          "Пропускать подтверждённые",
          React.createElement(InfoTip, { title: "Подтверждённые сегменты",
            body: "По умолчанию back-check проверяет всё, у чего есть перевод, включая подтверждённые: он ничего не перезаписывает, только дописывает оценку рядом. Проверить подтверждённое даже полезнее — если ошибка прошла ревью, узнать об этом важнее всего.\n\nВключите, если подтверждённым переводам доверяете и не хотите тратить на них вызовы модели. На пакетный перевод это не влияет: там подтверждённые не трогаются никогда." })),
        React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
          confirmedCount
            ? (skipConfirmed ? "Исключено из проверки: " + confirmedCount : "Проверяются вместе со всеми: " + confirmedCount)
            : "В выборке нет подтверждённых")),
      React.createElement(Switch, { on: !!skipConfirmed, label: "Пропускать подтверждённые",
        onClick: onSkipConfirmed })),

    React.createElement("div", { className: "row between", style: { gap: 10 } },
      React.createElement("div", null,
        React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, display: "flex", alignItems: "center" } },
          "Судья для спорных",
          React.createElement(InfoTip, { title: "LLM-судья средней зоны",
            body: "Для сегментов, попавших в середину шкалы (" + zone[0] + "-" + zone[1] + "%), модель отдельно сравнивает оригинал с обратным переводом и решает, подмена это понятия или просто другая формулировка. Подмена роняет балл, подтверждённая эквивалентность — поднимает. Наверху и внизу шкалы судья не вызывается: там вопрос уже решён проверками, платить за подтверждение очевидного незачем.\n\nУ судьи СВОЯ модель, отдельная от модели обратного перевода, и это намеренно: задачи противоположные. Обратному переводу нужна буквальная модель, которая не чинит ошибки; судье — сильная, способная отличить подмену понятия от синонима." })),
        React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
          judge ? "Разбирает сегменты в зоне " + zone[0] + "-" + zone[1] + "%" : "Только детерминированные проверки")),
      React.createElement(Switch, { on: !!judge, label: "Судья", onClick: onJudge })),

    // Своя модель судьи: показываем только когда он включён, чтобы не загромождать
    judge && models && models.length > 0 && React.createElement("div", null,
      React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginBottom: 4 } }, "Модель судьи"),
      React.createElement(Select, {
        value: judgeModel || "", disabled: !!running, style: { width: "100%" },
        onChange: (e) => onJudgeModel && onJudgeModel(e.target.value),
      }, models.map(m => React.createElement("option", { key: m.id, value: m.id },
        m.label + (m.note ? " — " + m.note : "")))),
      judgeModelInfo && React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: 5 } },
        "Цена за 1M токенов: вход " + fmtCost(judgeModelInfo.in) + " · выход " + fmtCost(judgeModelInfo.out))),

    React.createElement(EstLine, { est }),

    // Что именно проверять: группы «чем уже проверено» с количеством. Одна группа —
    // выбирать не из чего, не загромождаем карточку.
    groups && groups.length > 1 && React.createElement("div", {
      className: "card", style: { padding: "9px 11px", background: "var(--bg-sunken)" } },
      React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, marginBottom: 6, display: "flex", alignItems: "center" } },
        "Что проверять",
        React.createElement(InfoTip, { title: "Повторная проверка",
          body: "Сегмент, уже проверенный этой же моделью и с тем же переводом, по умолчанию снят с прогона: результат будет тот же, а вызов модели платный. Снимите или верните галочку, чтобы решить самому.\n\nОтдельными группами идут те, у кого проверки ещё не было, и те, чей перевод изменился после проверки, — там старая оценка уже не про этот текст. Если включён судья, сегменты его зоны, проверенные без него, тоже вынесены отдельно." })),
      groups.map(g => React.createElement("div", {
        key: g.key, className: "row between", style: { padding: "2px 0" } },
        React.createElement(Checkbox, {
          checked: pickedGroups.has(g.key),
          onChange: () => onToggleGroup(g.key),
        }, g.label),
        React.createElement("b", { style: { fontSize: 12.5 } }, g.count)))),

    running
      ? React.createElement("div", null,
          React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
            React.createElement("span", { className: "muted" }, "Обратный перевод…"),
            React.createElement("span", { style: { fontWeight: 700 } }, Math.floor(running.done) + "/" + running.total)),
          React.createElement(ProgressBar, { value: Math.round(running.done / running.total * 100) }),
          React.createElement("div", { className: "row", style: { justifyContent: "flex-end", marginTop: 8 } },
            React.createElement(Btn, { variant: "ghost", size: "sm", icon: "x", onClick: onStop }, "Остановить")))
      : React.createElement("div", { className: "row between" },
          React.createElement("span", { className: "dim", style: { fontSize: 12 } },
            "к проверке: " + available + " · уже проверено: " + done + (filtered ? " (фильтр)" : "")),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat", onClick: onRun, disabled: !available }, "Запустить"))
  );
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

function RepairCard({ running, onRun, onStop, available, repaired, filtered, checked, models, model, modelInfo, onModel,
                     groups, pickedGroups, onToggleGroup, est }) {
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-success)" } },
        React.createElement(Icon, { name: "repeat", size: 19 })),
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, "Автоматический ремонт",
          React.createElement(InfoTip, { title: "Автоматический ремонт",
            body: "Переписывает перевод по КОНКРЕТНЫМ находкам: потерянные термины, расхождения чисел и единиц, инверсия отрицания, вердикт судьи, кальки с предложенной заменой, а также утверждённые термины глоссария, которых в переводе нет. Не «переведи получше» — модель получает список претензий и правило менять как можно меньше.\n\nВсе проверенные записи глоссария для этого сегмента уходят в промпт целиком, даже если нарушений по ним нет: чиня одно, модель не должна выбить утверждённый термин в другом месте.\n\nПосле правки сегмент перепроверяется теми же проверками, которые ругались. Новый текст остаётся, ТОЛЬКО если оценка не упала, замечаний по терминам не прибавилось и утверждённых терминов не нарушено больше прежнего; иначе — откат, а вариант модели сохраняется для разбора.\n\nСтатус после ремонта — «Требует проверки», не «Подтверждён»: автоправка не заверяет сама себя. Прежний текст хранится и виден в карточке сегмента.\n\nОдин заход на один текст: пока перевод не изменится, повторно чинить нечего." })),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, "После проверок"))
    ),
    React.createElement(Select, { value: model || "", onChange: (e) => onModel(e.target.value), style: { fontSize: 13 } },
      (models || []).map(m => React.createElement("option", { key: m.id, value: m.id }, m.label))),
    modelInfo && React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: -4 } },
      "$" + modelInfo.in + " / $" + modelInfo.out + " за 1M токенов" + (modelInfo.note ? " · " + modelInfo.note : "")),
    repaired > 0 && React.createElement("div", { style: { fontSize: 12.5, color: "var(--c-success)", fontWeight: 600 } },
      "Исправлено: " + repaired),
    React.createElement(EstLine, { est }),
    React.createElement(RunGroups, { title: "Что чинить", groups, pickedGroups, onToggleGroup,
      tip: "Сегменты, которые уже проходили ремонт на этом же тексте, по умолчанию сняты: те же претензии дадут тот же результат, а вызов модели платный.\n\nОтметьте группу, чтобы зайти второй раз — например, другой моделью или после того, как одобрили термин в глоссарии.\n\n«Текст менялся после прошлого ремонта» — там прошлая попытка уже не про этот текст, такие сегменты отмечены сразу." }),
    running
      ? React.createElement("div", null,
          React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
            React.createElement("span", { className: "muted" }, "Чиним и перепроверяем…"),
            React.createElement("span", { style: { fontWeight: 700 } }, Math.round(running.done) + "/" + running.total)),
          React.createElement(ProgressBar, { value: Math.round(running.done / running.total * 100) }),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: onStop, style: { marginTop: 8 } }, "Остановить"))
      : React.createElement("div", { className: "row between" },
          React.createElement("span", { className: "dim", style: { fontSize: 12 } },
            available + " с находками" + (checked > 0 ? " (отмечено " + checked + ")" : filtered ? " (фильтр)" : "")),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat", onClick: onRun, disabled: !available }, "Починить"))
  );
}

// Одобрили термин — старые переводы сами не изменились. Здесь видно, сколько
// сегментов разошлось с глоссарием, и отсюда же их можно переперевести пакетом.
function GlossaryImpactCard({ impact, busy, onRefresh, onRun, onDrill, includeConfirmed, onIncludeConfirmed, est, running }) {
  const targets = includeConfirmed ? impact.segments : impact.pending;
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
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

    React.createElement("div", { className: "card", style: { padding: "8px 11px", background: "var(--bg-sunken)" } },
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

    React.createElement(EstLine, { est }),
    running
      ? React.createElement("div", { className: "dim", style: { fontSize: 12 } }, "Идёт перевод…")
      : React.createElement("div", { className: "row between" },
          React.createElement("button", { className: "linklike", style: { fontSize: 12 }, onClick: onRefresh, disabled: busy },
            busy ? "Считаем…" : "Пересчитать"),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat", onClick: onRun, disabled: !targets.length },
            "Перевести заново (" + targets.length + ")"))
  );
}

function TermCheckCard({ running, onRun, onStop, available, flagged, filtered, checked, models, model, modelInfo, onModel,
                        groups, pickedGroups, onToggleGroup, est }) {
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-purple)" } },
        React.createElement(Icon, { name: "book", size: 19 })),
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, "Проверка терминологии",
          React.createElement(InfoTip, { title: "Проверка терминологии",
            body: "Модель смотрит ТОЛЬКО на перевод и отвечает на вопрос «нормальный ли это термин целевого языка»: кальки, транслитерации, подмены понятия, склеенные обрывки.\n\nЭто не back-check. Back-check спрашивает, пережил ли смысл обратный перевод, и на кальке всегда отвечает «да»: «rear cyclitis» дословно возвращается как «задний циклит» и даёт высокий процент. Такие ошибки видны только прямой проверкой.\n\nТерминология берётся по предметной области проекта, а не по медицине.\n\nНайденные замены попадают в «Глоссарий → Кандидаты»: одобренная пара чинит термин во всех будущих переводах. Повторная проверка считает только то, где перевод менялся." })),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, "После перевода"))
    ),
    React.createElement(Select, { value: model || "", onChange: (e) => onModel(e.target.value), style: { fontSize: 13 } },
      (models || []).map(m => React.createElement("option", { key: m.id, value: m.id }, m.label))),
    modelInfo && React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: -4 } },
      "$" + modelInfo.in + " / $" + modelInfo.out + " за 1M токенов" + (modelInfo.note ? " · " + modelInfo.note : "")),
    flagged > 0 && React.createElement("div", { style: { fontSize: 12.5, color: "var(--c-warning)", fontWeight: 600 } },
      "С замечаниями: " + flagged),
    React.createElement(EstLine, { est }),
    React.createElement(RunGroups, { title: "Что проверять", groups, pickedGroups, onToggleGroup,
      tip: "Сегмент, уже проверенный этой же моделью с тем же переводом, по умолчанию снят с прогона: результат будет тот же, а вызов платный. Проверенное ДРУГОЙ моделью отмечено — второе мнение имеет смысл.\n\nОтдельно вынесены те, где замечания были, и те, где их не было: после правок обычно перепроверяют именно первые.\n\n«Нечего проверять» — сегменты без слов или с переводом, совпадающим с оригиналом; они и при повторном прогоне уйдут без вызова модели." }),
    running
      ? React.createElement("div", null,
          React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
            React.createElement("span", { className: "muted" }, "Проверяем термины…"),
            React.createElement("span", { style: { fontWeight: 700 } }, Math.round(running.done) + "/" + running.total)),
          React.createElement(ProgressBar, { value: Math.round(running.done / running.total * 100) }),
          React.createElement(Btn, { variant: "ghost", size: "sm", icon: "x", onClick: onStop, style: { marginTop: 8 } }, "Остановить"))
      : React.createElement("div", { className: "row between" },
          React.createElement("span", { className: "dim", style: { fontSize: 12 } },
            available + " к проверке" + (checked > 0 ? " (отмечено " + checked + ")" : filtered ? " (фильтр)" : "")),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "book", onClick: onRun, disabled: !available }, "Проверить"))
  );
}

function MedicalQACard({ running, onRun, available, filtered, checked, est }) {
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-info)" } },
        React.createElement(Icon, { name: "shield", size: 19 })),
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, "Детерминированные проверки",
          React.createElement(InfoTip, { title: "Детерминированные проверки (Medical QA)",
            body: "Проверки правилами, без вопросов к модели: совпадение чисел и дозировок, наличие единиц измерения, сохранность отрицания, пары лево/право, внутренний/наружный, верхний/нижний, использование утверждённых терминов глоссария. Даёт risk score.\n\nЧем отличается от back-check: тот сравнивает оригинал с ОБРАТНЫМ переводом и судит о смысле, стоит вызова модели на каждый сегмент и слеп к калькам. Здесь оригинал сравнивается с переводом напрямую по формальным признакам — быстро и без оплаты.\n\nЗапускайте ПОСЛЕ back-check: готовый обратный перевод переиспользуется, и тогда прогон бесплатен целиком. До back-check придётся заказать обратный перевод, и это единственная его платная часть." })),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, "Правилами, без вызова модели"))
    ),
    React.createElement("p", { className: "muted", style: { fontSize: 13, margin: 0 } },
      "Числа и дозировки, единицы, отрицание, лево/право, соответствие глоссарию."),
    React.createElement(EstLine, { est }),
    running
      ? React.createElement("div", null,
          React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
            React.createElement("span", { className: "muted" }, "Проверяем правилами…"),
            React.createElement("span", { style: { fontWeight: 700 } }, running.done + "/" + running.total)),
          React.createElement(ProgressBar, { value: Math.round(running.done / running.total * 100) }))
      : React.createElement("div", { className: "row between" },
          React.createElement("span", { className: "dim", style: { fontSize: 12 } },
            available + " к проверке" + (checked > 0 ? " (отмечено " + checked + ")" : filtered ? " (фильтр)" : "")),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "shield", onClick: onRun, disabled: !available }, "Проверить"))
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
  return React.createElement("tr", { className: "row-status-" + seg.status + (selected ? " selected" : "") + (checked ? " row-checked" : ""), onClick: onSelect },
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
    React.createElement("td", null,
      React.createElement(TMChip, { score: seg.tmScore }),
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
                 color: seg.backcheck.score >= 95 ? "var(--c-success)"
                   : seg.backcheck.score >= 80 ? "var(--c-warning)" : "var(--c-error)" },
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
