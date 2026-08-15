/* ============================================================
   Tab: Segment Editor — the core translation workspace
   ============================================================ */

// Размер порции пакетного перевода. Один запрос ≈ BATCH_CHUNK * EST_SEC_PER_SEG секунд —
// держим его коротким, чтобы не упираться в proxy_read_timeout и чаще двигать прогресс.
const BATCH_CHUNK = 10;
const EST_SEC_PER_SEG = 5;          // замер на проде: 5-6 с на сегмент через GPT
const CHUNK_RETRIES = 2;            // повторов порции при сбое
const RETRY_PAUSE_MS = 6000;        // пауза перед повтором — хватает пережить рестарт сервиса

// Порция с повторами: одна неудача не должна убивать двухчасовой прогон.
// Ровно так пакет и обрывался, когда сервис перезапускали во время работы.
async function callChunkWithRetry(fn, onRetry) {
  for (let attempt = 0; attempt <= CHUNK_RETRIES; attempt++) {
    const r = await window.API.safeCall(fn);
    if (r && r.ok) return r;
    if (attempt < CHUNK_RETRIES) {
      if (onRetry) onRetry(attempt + 1);
      await new Promise(res => setTimeout(res, RETRY_PAUSE_MS));
    }
  }
  return null;
}
const GPT_MODEL_LS_KEY = "mcat_gpt_model";
const BC_MODEL_LS_KEY = "mcat_backcheck_model";
const JUDGE_MODEL_LS_KEY = "mcat_judge_model";

// Цвет полосы соответствия обратного перевода
function bandColor(color) {
  return color === "green" ? "var(--c-success)"
    : color === "yellow" ? "var(--c-warning)"
    : color === "orange" ? "var(--c-warning)"
    : "var(--c-error)";
}

// Ориентировочная смета пакета. Кириллица ≈ 2.2 симв./токен, английский вывод ≈ 3.5,
// плюс ~500 токенов системного промпта с глоссарием на каждый сегмент. У моделей GPT-5.x
// в оплачиваемый вывод входят ещё и reasoning-токены — отсюда надбавка.
function estimateBatch(targets, model) {
  const chars = targets.reduce((a, s) => a + (s.source || "").length, 0);
  const tokIn = targets.length * 500 + chars / 2.2;
  const tokOut = (chars / 3.5) * (model && model.api === "modern" ? 1.8 : 1);
  const cost = model ? (tokIn / 1e6) * model.in + (tokOut / 1e6) * model.out : null;
  return { chars, cost, seconds: targets.length * EST_SEC_PER_SEG };
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
  const [riskFilter, setRiskFilter] = useState("all");
  const [height, setHeight] = useState(440);
  const [selId, setSelId] = useState(project ? (project.segments[0] && project.segments[0].id) : null);
  const [busy, setBusy] = useState({});       // {segId: 'translate'|'qa'}
  const [batchRun, setBatchRun] = useState(null); // {engine, done, total}
  const [checkedSegs, setCheckedSegs] = useState(new Set()); // ручной выбор
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(1);
  const [revertTarget, setRevertTarget] = useState(null);
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
  const [bcBands, setBcBands] = useState([]);
  const [bcJudge, setBcJudge] = useState(false);          // LLM-судья для средней зоны
  const [judgeModel, setJudgeModel] = useState(() => {
    try { return localStorage.getItem(JUDGE_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [judgeZone, setJudgeZone] = useState([50, 97]);
  const stopRef = useRef(false);
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
      if (d.backcheckBands) setBcBands(d.backcheckBands);
      if (d.judgeZone) setJudgeZone(d.judgeZone);
    });
  }, []);

  // Сменились модель, выборка или сам режим — возвращаем выбор групп к умолчанию
  useEffect(() => { setProviderPick(null); },
    [retranslate, gptModel, store.segmentFilter, checkedSegs.size]);

  const gptModelInfo = gptModels.find(m => m.id === gptModel) || null;
  const pickGptModel = (id) => {
    setGptModel(id);
    try { localStorage.setItem(GPT_MODEL_LS_KEY, id); } catch (e) { /* приватный режим — не страшно */ }
  };
  const bcModelInfo = gptModels.find(m => m.id === bcModel) || null;
  const pickBcModel = (id) => {
    setBcModel(id);
    try { localStorage.setItem(BC_MODEL_LS_KEY, id); } catch (e) { /* приватный режим — не страшно */ }
  };
  const judgeModelInfo = gptModels.find(m => m.id === judgeModel) || null;
  const pickJudgeModel = (id) => {
    setJudgeModel(id);
    try { localStorage.setItem(JUDGE_MODEL_LS_KEY, id); } catch (e) { /* приватный режим — не страшно */ }
  };

  useEffect(() => { setPage(1); }, [filter, query, riskFilter, project && project.id, store.segmentFilter]);
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
    if (query) { const q = query.toLowerCase(); if (!s.source.toLowerCase().includes(q) && !(s.target || "").toLowerCase().includes(q)) return false; }
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
    if (window.API) await window.API.safeCall(() => window.API.confirm(project.id, seg.id));
    store.updateSegment(project.id, seg.id, { status: "confirmed" });
    toast.success("Подтверждено", "Сегмент #" + seg.id + " добавлен в память переводов.");
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

  // Пакет идёт порциями по BATCH_CHUNK: один HTTP-запрос живёт минуту-две и не упирается
  // в таймаут прокси, прогресс двигается по ходу дела, а прерванный пакет не откатывает
  // уже переведённое — всё сохранено на сервере по завершении каждой порции.
  const runBatch = async (engine, targets, hasExplicitCheck) => {
    setBatchPlan(null);
    stopRef.current = false;
    const total = targets.length;
    const ids = targets.map(s => s.id);
    const engineName = engine === "gpt" ? "GPT" : "Google";
    let done = 0, errCount = 0, tmCount = 0, failed = false, landed = 0;
    const translatedIds = [];
    setBatchRun({ engine, done: 0, total });

    for (let i = 0; i < ids.length; i += BATCH_CHUNK) {
      if (stopRef.current) break;
      const chunk = ids.slice(i, i + BATCH_CHUNK);
      // Ориентировочный прогресс внутри порции: сервер отвечает только по её завершении,
      // поэтому между ответами двигаем полосу по оценке времени на сегмент.
      const base = done, t0 = Date.now();
      const tick = setInterval(() => {
        const est = Math.min(chunk.length - 0.5, (Date.now() - t0) / 1000 / EST_SEC_PER_SEG);
        setBatchRun(b => (b ? { ...b, done: base + est } : b));
      }, 500);
      let r = null;
      if (window.API) r = await callChunkWithRetry(
        () => window.API.batch(project.id, engine, chunk, hasExplicitCheck, BATCH_CHUNK, gptModel),
        (n) => toast.warning("Сбой связи", "Порция не прошла, повтор " + n + " из " + CHUNK_RETRIES + "…"));
      clearInterval(tick);
      if (!r || !r.ok) { failed = true; break; }
      done += r.count;
      errCount += (r.errors || []).length;
      tmCount += r.tm_hits || 0;
      translatedIds.push(...(r.translated || []));
      setBatchRun({ engine, done, total });
      // Подтягиваем переводы в таблицу после каждой порции — строки наливаются по ходу
      const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
      if (fresh && fresh.segments) {
        store.replaceProjectSegments(project.id, fresh.segments);
        // Сверяем: сервер отчитался о переводе — реально ли он приехал в данные?
        // Расхождение честно показываем вместо зелёного тоста.
        const byId = new Map(fresh.segments.map(s => [s.id, s]));
        landed += (r.translated || []).filter(id => {
          const s = byId.get(id);
          return s && (s.target || "").trim();
        }).length;
      }
    }

    const stopped = stopRef.current;
    stopRef.current = false;
    setBatchRun(null);

    // Переведённые сегменты перестают подходить под фильтр «Новые» и молча уходят из
    // выборки — страница дозаполняется следующими пустыми строками, и выглядит это так,
    // будто перевод не применился. Поэтому после пакета показываем результат: goToSegment
    // сбрасывает фильтры и перематывает на страницу с первым переведённым сегментом.
    const jumped = done > 0 && translatedIds.length > 0 && filter !== "all";
    if (done > 0) {
      setCheckedSegs(new Set());
      if (jumped) store.goToSegment(translatedIds[0]);
    }

    const errMsg = errCount ? " · ошибок: " + errCount : "";
    const tmMsg = tmCount ? " · из TM без " + engineName + ": " + tmCount : "";
    const jumpMsg = jumped ? " · фильтр сброшен на «Все», чтобы показать переводы" : "";
    if (failed) {
      toast.error("Пакет прерван ошибкой",
        done + " из " + total + " успело перевестись и сохранено. Проверьте связь и запустите ещё раз." + errMsg);
    } else if (stopped) {
      toast.warning("Пакет остановлен", done + " из " + total + " переведено и сохранено." + tmMsg + errMsg);
    } else if (done > 0 && landed < done) {
      toast.warning("Переводы могли не отобразиться",
        done + " сохранено на сервере, но в таблицу подтянулось " + landed + ". Обновите страницу (F5).");
    } else if (done > 0) {
      const modelMsg = engine === "gpt" && gptModelInfo ? " (" + gptModelInfo.label + ")" : "";
      toast.success("Пакет завершён",
        done + " сегментов переведено через " + engineName + modelMsg + tmMsg + errMsg + jumpMsg);
    } else {
      toast.warning("Нет новых переводов", "Все подходящие сегменты уже переведены" + errMsg);
    }
  };

  // Пакетный back-check. Та же порционная механика, что и у перевода: короткие
  // запросы, прогресс по ходу, остановка не откатывает уже посчитанное.
  const runBackcheckBatch = async () => {
    if (batchRun) return;
    let currentSegs = project.segments;
    if (window.API) {
      const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
      if (fresh && fresh.segments) {
        store.replaceProjectSegments(project.id, fresh.segments);
        currentSegs = fresh.segments;
      }
    }
    const idSet = currentIdSet;
    const targets = currentSegs.filter(s =>
      (s.target || "").trim() && (!idSet || idSet.has(s.id)));
    if (!targets.length) {
      toast.warning("Нечего проверять", "В выборке нет переведённых сегментов.");
      return;
    }
    stopRef.current = false;
    const ids = targets.map(s => s.id);
    const total = ids.length;
    let done = 0, cached = 0, errCount = 0, failed = false;
    setBatchRun({ engine: "backcheck", done: 0, total });

    for (let i = 0; i < ids.length; i += BATCH_CHUNK) {
      if (stopRef.current) break;
      const chunk = ids.slice(i, i + BATCH_CHUNK);
      const base = done, t0 = Date.now();
      const tick = setInterval(() => {
        const est = Math.min(chunk.length - 0.5, (Date.now() - t0) / 1000 / EST_SEC_PER_SEG);
        setBatchRun(b => (b ? { ...b, done: base + est } : b));
      }, 500);
      let r = null;
      if (window.API) r = await callChunkWithRetry(
        () => window.API.backcheckBatch(project.id, chunk, BATCH_CHUNK, bcModel, bcJudge, judgeModel),
        (n) => toast.warning("Сбой связи", "Порция не прошла, повтор " + n + " из " + CHUNK_RETRIES + "…"));
      clearInterval(tick);
      if (!r || !r.ok) { failed = true; break; }
      // Сегменты из кэша тоже двигают прогресс — иначе полоса стоит на месте
      done += r.count + (r.skipped_cached || 0);
      cached += r.skipped_cached || 0;
      errCount += (r.errors || []).length;
      setBatchRun({ engine: "backcheck", done, total });
      const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
      if (fresh && fresh.segments) store.replaceProjectSegments(project.id, fresh.segments);
    }

    const stopped = stopRef.current;
    stopRef.current = false;
    setBatchRun(null);
    const cachedMsg = cached ? " · из кэша: " + cached : "";
    const errMsg = errCount ? " · ошибок: " + errCount : "";
    if (failed) {
      toast.error("Back-check прерван", done + " из " + total + " проверено и сохранено." + errMsg);
    } else if (stopped) {
      toast.warning("Back-check остановлен", done + " из " + total + " проверено и сохранено." + cachedMsg);
    } else {
      toast.success("Back-check завершён",
        done + " сегментов проверено" + cachedMsg + errMsg + " · разбивка в Анализе");
    }
  };

  const runMedicalQABatch = async () => {
    let currentSegs = project.segments;
    if (window.API) {
      const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
      if (fresh && fresh.segments) {
        store.replaceProjectSegments(project.id, fresh.segments);
        currentSegs = fresh.segments;
      }
    }
    const idSet = checkedSegs.size > 0 ? checkedSegs
      : (store.segmentFilter || window._mcat_sf || null);
    const targets = currentSegs.filter(s =>
      s.target && s.target.trim() &&
      ["translated", "qa", "review", "confirmed"].includes(s.status) &&
      (!idSet || idSet.has(s.id))
    );
    if (!targets.length) {
      toast.warning("Medical QA", "Нет переведённых сегментов для пакетной проверки.");
      return;
    }
    setBatchRun({ engine: "medical_qa", done: 0, total: targets.length });
    const segIds = idSet ? targets.map(s => s.id) : null;
    let result = null;
    if (window.API) result = await window.API.safeCall(() => window.API.medicalQABatch(project.id, segIds));
    if (result && result.ok) {
      const fresh2 = await window.API.safeCall(() => window.API.getProject(project.id));
      if (fresh2 && fresh2.segments) store.replaceProjectSegments(project.id, fresh2.segments);
      setBatchRun({ engine: "medical_qa", done: result.count, total: targets.length });
      setTimeout(() => {
        setBatchRun(null);
        const errMsg = result.errors && result.errors.length ? " · ошибок: " + result.errors.length : "";
        toast.success("Medical QA batch завершён", result.count + " сегментов проверено" + errMsg);
      }, 400);
    } else {
      setBatchRun(null);
      toast.error("Medical QA batch", "Не удалось выполнить пакетную проверку.");
    }
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
        )
      ),
      showFilters && React.createElement("div", { className: "row row-wrap", style: { gap: 14, padding: "4px 2px" } },
        React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Поиск по тексту…" }),
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

    // ---- Batch actions ----
    React.createElement("div", { className: "editor-main", style: { paddingBottom: 0 } },
      React.createElement(Expander, { title: "Пакетный перевод", icon: "zap", right: "2 движка", defaultOpen: false },
        React.createElement("div", { className: "grid grid-3" },
          React.createElement(BatchCard, { kind: "google", running: batchRun && batchRun.engine === "google" ? batchRun : null, onRun: () => askRunBatch("google"), onStop: () => { stopRef.current = true; },
            available: pickTargets("google", project.segments).targets.length,
            selectionSize: pickTargets("google", project.segments).selectionSize,
            checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf) }),
          React.createElement(BatchCard, { kind: "gpt", running: batchRun && batchRun.engine === "gpt" ? batchRun : null, onRun: () => askRunBatch("gpt"), onStop: () => { stopRef.current = true; },
            models: gptModels, model: gptModel, modelInfo: gptModelInfo, onModel: pickGptModel,
            available: pickTargets("gpt", project.segments).targets.length,
            selectionSize: pickTargets("gpt", project.segments).selectionSize,
            checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf) }),
          React.createElement(MedicalQACard, { running: batchRun && batchRun.engine === "medical_qa" ? batchRun : null, onRun: runMedicalQABatch,
            available: project.segments.filter(s => s.target && s.target.trim() && ["translated", "qa", "review", "confirmed"].includes(s.status) && (checkedSegs.size > 0 ? checkedSegs.has(s.id) : (!store.segmentFilter || store.segmentFilter.has(s.id)))).length,
            checked: checkedSegs.size, filtered: !!(store.segmentFilter || window._mcat_sf) }),
          React.createElement(BackcheckCard, {
            running: batchRun && batchRun.engine === "backcheck" ? batchRun : null,
            onRun: runBackcheckBatch, onStop: () => { stopRef.current = true; },
            models: gptModels, model: bcModel, modelInfo: bcModelInfo, onModel: pickBcModel,
            judge: bcJudge, onJudge: () => setBcJudge(v => !v),
            judgeModel: judgeModel, judgeModelInfo: judgeModelInfo, onJudgeModel: pickJudgeModel,
            judgeZone: judgeZone,
            available: project.segments.filter(s => (s.target || "").trim() &&
              (!currentIdSet || currentIdSet.has(s.id))).length,
            done: project.segments.filter(s => s.backcheck && s.backcheck.score != null &&
              (!currentIdSet || currentIdSet.has(s.id))).length,
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
          React.createElement(EmptyState, { icon: "filter", title: "Нет сегментов по фильтру", sub: "Измените фильтр статуса или поиск." })),
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
              bcJudge: bcJudge, judgeModel: judgeModel })
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
            "Пакет идёт порциями по " + BATCH_CHUNK + " сегментов, переводы сохраняются после каждой порции — " +
            "остановка не откатывает уже сделанное.")
        )
      );
    })(),

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

function BatchCard({ kind, running, onRun, onStop, available, selectionSize, filtered, checked, models, model, modelInfo, onModel }) {
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
                        judge, onJudge, judgeModel, judgeModelInfo, onJudgeModel, judgeZone }) {
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
            "проверено " + done + " из " + available + (filtered ? " (фильтр)" : "")),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat", onClick: onRun, disabled: !available }, "Запустить"))
  );
}

function MedicalQACard({ running, onRun, available, filtered, checked }) {
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: "var(--c-info)" } },
        React.createElement(Icon, { name: "shield", size: 19 })),
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, "Medical QA",
          React.createElement(InfoTip, { title: "Structured Medical QA", body: "Back-check + semantic comparator + medical style QA + deterministic validators. Result: risk score, issues, suggested correction, term candidates." })),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, "After translation"))
    ),
    React.createElement("p", { className: "muted", style: { fontSize: 13, margin: 0 } }, "Runs the full QA chain for translated segments: numbers, negation, inner/outer, forbidden terms, and literal calques."),
    running
      ? React.createElement("div", null,
          React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
            React.createElement("span", { className: "muted" }, "Medical QA..."),
            React.createElement("span", { style: { fontWeight: 700 } }, running.done + "/" + running.total)),
          React.createElement(ProgressBar, { value: Math.round(running.done / running.total * 100) }))
      : React.createElement("div", { className: "row between" },
          React.createElement("span", { className: "dim", style: { fontSize: 12 } },
            available + " available" + (checked > 0 ? " (" + checked + " selected)" : filtered ? " (filter)" : "")),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "shield", onClick: onRun, disabled: !available }, "Run QA"))
  );
}

function SegRow({ seg, selected, busy, checked, onCheck, onSelect, onTranslate, onConfirm, onRevert, models }) {
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
    React.createElement("td", { className: "src-cell" }, seg.source),
    React.createElement("td", { className: seg.target ? "tgt-cell" : "tgt-cell tgt-empty" }, seg.target || "— не переведено —"),
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
