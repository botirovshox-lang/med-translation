/* ============================================================
   API client — talks to FastAPI backend at /api/*
   ============================================================ */
(function () {
  const BASE = (window.API_BASE || "") + "/api";
  const TOKEN_KEY = "mct-token";

  /* sessionStorage, а не localStorage: закрыл вкладку — токен пропал.
     Медицинские документы не должны оставаться доступными на общем компьютере. */
  function getToken() {
    try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
  }
  function setToken(t) {
    try {
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch (e) {}
  }
  function authHeaders(h) {
    const t = getToken();
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }
  /* Токен истёк или процесс перезапущен → выкидываем на экран входа. */
  function onUnauthorized() {
    setToken("");
    window.dispatchEvent(new Event("mct-auth-expired"));
  }

  async function call(method, path, body) {
    const init = { method, headers: authHeaders({}) };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const r = await fetch(BASE + path, init);
    if (r.status === 401 && path !== "/auth/login") onUnauthorized();
    if (!r.ok) {
      const text = await r.text().catch(() => "");
      const err = new Error(`API ${method} ${path} failed: ${r.status} ${text}`);
      err.status = r.status;
      throw err;
    }
    return r.json();
  }

  window.API = {
    health:        ()                       => call("GET",    "/health"),
    seed:          ()                       => call("GET",    "/seed"),
    login: async (password) => {
      const r = await call("POST", "/auth/login", { password });
      if (!r || !r.token) throw new Error("Сервер не выдал токен сессии");
      setToken(r.token);
      return r;
    },
    logout: async () => {
      try { await call("POST", "/auth/logout"); } catch (e) { /* токен всё равно стираем */ }
      setToken("");
    },
    hasToken: () => !!getToken(),
    /* Для <a href> скачивания: заголовок в ссылку не подставить, токен идёт в query. */
    downloadUrl: (url) => url + (url.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(getToken()),

    /* lang/domain сужают выдачу до области проекта — той, что уходит в промпт. */
    listGlossary:  (q, cat, limit, offset, lang, domain) => call("GET", `/glossary?q=${encodeURIComponent(q||"")}&cat=${encodeURIComponent(cat||"")}&limit=${limit||200}&offset=${offset||0}&lang=${encodeURIComponent(lang||"")}&domain=${encodeURIComponent(domain||"")}`),
    listProjects:  ()                       => call("GET",    "/projects"),
    getProject:    (pid)                    => call("GET",    `/projects/${pid}`),
    createProject: (info)                   => call("POST",   "/projects",                          info),
    deleteProject: (pid)                    => call("DELETE", `/projects/${pid}`),
    uploadProject: async (file, title, src, tgt, domain) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", title || "");
      fd.append("src",   src  || "RU");
      fd.append("tgt",   tgt  || "EN");
      fd.append("domain", domain || "medical");
      const r = await fetch((window.API_BASE || "") + "/api/projects/upload",
                            { method: "POST", body: fd, headers: authHeaders({}) });
      if (r.status === 401) onUnauthorized();
      if (!r.ok) { const t = await r.text().catch(() => ""); throw new Error("Upload failed: " + r.status + " " + t); }
      return r.json();
    },

    models:        ()                       => call("GET",    "/models"),
    /* Движок один — выбранная модель. Параметра engine больше нет. */
    translate:     (pid, sid, force, model) => call("POST", `/segments/${pid}/${sid}/translate`, { force: !!force, model: model || null }),
    backcheck:     (pid, sid, model, judge, judgeModel) => call("POST", `/segments/${pid}/${sid}/backcheck`, { model: model || null, use_judge: !!judge, judge_model: judgeModel || null }),
    backcheckBatch:(pid, segIds, limit, model, judge, judgeModel, skipCached) => call("POST", `/projects/${pid}/backcheck/batch`, { segment_ids: segIds || null, limit: limit || 10, model: model || null, use_judge: !!judge, judge_model: judgeModel || null, skip_cached: skipCached !== false }),
    medicalQA:     (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/medical-qa`,  { run_backcheck: true }),
    qa:            (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/qa`),
    confirm:       (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/confirm`),
    revert:        (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/revert`),
    update:        (pid, sid, patch)        => call("POST",   `/segments/${pid}/${sid}/update`,     patch),

    batch:         (pid, segIds, force, limit, model) => call("POST", `/projects/${pid}/batch`, { segment_ids: segIds || null, force: !!force, limit: limit || 50, model: model || null }),
    medicalQABatch:(pid, segIds, bcModel)    => call("POST",   `/projects/${pid}/medical-qa/batch`,   { segment_ids: segIds || null, run_backcheck: true, bc_model: bcModel || null }),
    preflight:     (pid)                    => call("POST",   `/projects/${pid}/preflight`),
    exportProject: (pid, format, source)    => call("POST",   `/projects/${pid}/export`,            { format, source: source !== false }),

    termcheck:     (pid, sid, model)        => call("POST", `/segments/${pid}/${sid}/termcheck`, { model: model || null }),
    repair:        (pid, sid, opts)         => call("POST", `/segments/${pid}/${sid}/repair`, opts || {}),

    /* Фоновые прогоны: клиент только ставит задачу и смотрит прогресс */
    // Разбор прогона до запуска. Состав считает сервер тем же кодом, который
    // потом и работает: у браузера были свои предикаты, у сервера свои, и
    // расходились они не в пользу человека — смета показывала одно, а списывалось
    // другое. Ответ содержит и причины, по которым сегменты пропущены.
    runPlan:       (pid, body)              => call("POST", `/projects/${pid}/run-plan`, body || {}),
    createJob:     (pid, kind, segIds, params) => call("POST", `/projects/${pid}/jobs`, { kind, segment_ids: segIds, params: params || {} }),
    listJobs:      (pid)                    => call("GET",    `/jobs?project=${pid}`),
    fetchSegments: (pid, ids)               => call("POST",   `/projects/${pid}/segments/fetch`, { ids }),
    stopJob:       (jid)                    => call("POST",   `/jobs/${jid}/stop`),
    repairBatch:   (pid, segIds, limit, opts) => call("POST", `/projects/${pid}/repair/batch`, { segment_ids: segIds || null, limit: limit || 5, ...(opts || {}) }),
    termcheckBatch:(pid, segIds, limit, model, skipCached) => call("POST", `/projects/${pid}/termcheck/batch`, { segment_ids: segIds || null, limit: limit || 10, model: model || null, skip_cached: skipCached !== false }),

    /* Подтверждение теперь возвращает {tm, propagate, termCandidates} — см. confirm_segment */
    propagate:     (pid, sid, ids, includeConfirmed) => call("POST", `/segments/${pid}/${sid}/propagate`, { ids: ids || null, include_confirmed: !!includeConfirmed }),
    /* project — чтобы разбор «почему ждёт» считался в области проекта. */
    termQueue:     (status, limit, pid)     => call("GET",    `/term-queue?status=${encodeURIComponent(status || "pending")}&limit=${limit || 200}${pid ? "&project=" + pid : ""}`),
    /* Массовым может быть только отклонение: одобрение пачкой — auto-approve. */
    bulkReject:    (ids)                    => call("POST",   "/term-queue/bulk", { ids, action: "reject" }),
    glossaryUsage: (src, limit, lang, domain) => call("GET",  `/glossary/usage?src=${encodeURIComponent(src)}&limit=${limit || 6}&lang=${encodeURIComponent(lang||"")}&domain=${encodeURIComponent(domain||"")}`),
    /* refresh — «Пересчитать» руками: отчёт кэширован по отпечатку проекта,
       и без этого нажатие возвращало бы посчитанное раньше, ничего не сделав. */
    glossaryImpact:(pid, refresh)           => call("GET",    `/projects/${pid}/glossary-impact` + (refresh ? "?refresh=true" : "")),
    /* Итог по проекту одним экраном: чисто / исправлено машиной / нужен человек.
       Вызовов модели внутри нет, дёргать можно свободно. */
    analysis:      (pid)                    => call("GET",    `/projects/${pid}/analysis`),
    /* Разбор вариантов НА ЯЗЫКЕ ОРИГИНАЛА: обратный перевод, значение и область
       употребления по каждому. Для тех, кто целевого языка не знает: сравнивать
       нужно смысл, написанный понятным языком, а не строки. Вызов платный. */
    explainTerm:   (cid, include)            => call("POST",   `/term-queue/${cid}/explain`, { include: include || null }),
    approveTerm:   (cid, patch)             => call("POST",   `/term-queue/${cid}/approve`,          patch || {}),
    rejectTerm:    (cid)                    => call("POST",   `/term-queue/${cid}/reject`),
    extractTerms:  (pid, segIds, limit, model) => call("POST", `/projects/${pid}/extract-terms`,     { segment_ids: segIds || null, limit: limit || 30, model: model || null }),
    /* Автоодобрение: dry_run по умолчанию — сервер только считает вердикты. */
    autoApprove:   (opts)                   => call("POST",   "/term-queue/auto-approve",           opts || {}),
    undoAutoApprove:(batch)                 => call("POST",   `/term-queue/auto-approve/${batch}/undo`),
    autoBatches:   ()                       => call("GET",    "/term-queue/auto-batches"),
    /* Смысловая сверка записей, УЖЕ стоящих приказом. dry_run по умолчанию. */
    auditGlossary: (opts)                   => call("POST",   "/glossary/audit",                    opts || {}),
    /* force — переспросить и то, что уже сверялось: вердикт лежит на записи. */
    /* Массовый вынос автоимпорта. dry_run по умолчанию — сервер только считает. */
    purgeGlossary:(opts)                    => call("POST",   "/glossary/purge",                    opts || {}),
    purgeList:     ()                       => call("GET",    "/glossary/purge/list"),
    undoPurge:     (stamp)                  => call("POST",   `/glossary/purge/${stamp}/undo`),

    saveTerm:      (term, isNew)            => call("POST",   "/glossary",                          { ...term, isNew }),
    /* Область обязательна: без неё удаление уносит однофамильца из другой пары языков. */
    deleteTerm:    (src, lang, domain)      => call("DELETE", `/glossary?src=${encodeURIComponent(src)}&lang=${encodeURIComponent(lang||"")}&domain=${encodeURIComponent(domain||"")}`),
    /* Понижение приказа до подсказки: намерение, обратное правке (там «правка
       руками = приказ»), поэтому отдельной дверью. */
    demoteTerm:    (src, lang, domain)      => call("POST",   "/glossary/demote", { src, lang: lang || "", domain: domain || "" }),
    deleteTM:      (src, lang)              => call("DELETE", `/tm?src=${encodeURIComponent(src)}&lang=${encodeURIComponent(lang||"")}`),
  };

  // Best-effort: fail silently in dev if backend down (UI keeps working on mock data).
  window.API.safeCall = async function (fn) {
    try { return await fn(); }
    catch (e) { console.warn("[API] call failed, using local state:", e.message); return null; }
  };
})();
