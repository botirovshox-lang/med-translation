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

    listGlossary:  (q, cat, limit, offset)  => call("GET",    `/glossary?q=${encodeURIComponent(q||"")}&cat=${encodeURIComponent(cat||"")}&limit=${limit||200}&offset=${offset||0}`),
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
    translate:     (pid, sid, engine, force, model) => call("POST", `/segments/${pid}/${sid}/translate`, { engine, force: !!force, model: model || null }),
    backcheck:     (pid, sid, model, judge, judgeModel) => call("POST", `/segments/${pid}/${sid}/backcheck`, { model: model || null, use_judge: !!judge, judge_model: judgeModel || null }),
    backcheckBatch:(pid, segIds, limit, model, judge, judgeModel, skipCached) => call("POST", `/projects/${pid}/backcheck/batch`, { segment_ids: segIds || null, limit: limit || 10, model: model || null, use_judge: !!judge, judge_model: judgeModel || null, skip_cached: skipCached !== false }),
    medicalQA:     (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/medical-qa`,  { run_backcheck: true }),
    qa:            (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/qa`),
    confirm:       (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/confirm`),
    revert:        (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/revert`),
    update:        (pid, sid, patch)        => call("POST",   `/segments/${pid}/${sid}/update`,     patch),

    batch:         (pid, engine, segIds, force, limit, model) => call("POST", `/projects/${pid}/batch`, { engine, segment_ids: segIds || null, force: !!force, limit: limit || 50, model: model || null }),
    medicalQABatch:(pid, segIds)             => call("POST",   `/projects/${pid}/medical-qa/batch`,   { segment_ids: segIds || null, run_backcheck: true }),
    preflight:     (pid)                    => call("POST",   `/projects/${pid}/preflight`),
    exportProject: (pid, format, source)    => call("POST",   `/projects/${pid}/export`,            { format, source: source !== false }),

    termcheck:     (pid, sid, model)        => call("POST", `/segments/${pid}/${sid}/termcheck`, { model: model || null }),
    termcheckBatch:(pid, segIds, limit, model, skipCached) => call("POST", `/projects/${pid}/termcheck/batch`, { segment_ids: segIds || null, limit: limit || 10, model: model || null, skip_cached: skipCached !== false }),

    /* Подтверждение теперь возвращает {tm, propagate, termCandidates} — см. confirm_segment */
    propagate:     (pid, sid, ids, includeConfirmed) => call("POST", `/segments/${pid}/${sid}/propagate`, { ids: ids || null, include_confirmed: !!includeConfirmed }),
    termQueue:     (status, limit)          => call("GET",    `/term-queue?status=${encodeURIComponent(status || "pending")}&limit=${limit || 200}`),
    approveTerm:   (cid, patch)             => call("POST",   `/term-queue/${cid}/approve`,          patch || {}),
    rejectTerm:    (cid)                    => call("POST",   `/term-queue/${cid}/reject`),
    extractTerms:  (pid, segIds, limit, model) => call("POST", `/projects/${pid}/extract-terms`,     { segment_ids: segIds || null, limit: limit || 30, model: model || null }),

    saveTerm:      (term, isNew)            => call("POST",   "/glossary",                          { ...term, isNew }),
    deleteTerm:    (src)                    => call("DELETE", `/glossary?src=${encodeURIComponent(src)}`),
    deleteTM:      (src)                    => call("DELETE", `/tm?src=${encodeURIComponent(src)}`),
  };

  // Best-effort: fail silently in dev if backend down (UI keeps working on mock data).
  window.API.safeCall = async function (fn) {
    try { return await fn(); }
    catch (e) { console.warn("[API] call failed, using local state:", e.message); return null; }
  };
})();
