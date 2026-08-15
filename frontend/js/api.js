/* ============================================================
   API client — talks to FastAPI backend at /api/*
   ============================================================ */
(function () {
  const BASE = (window.API_BASE || "") + "/api";

  async function call(method, path, body) {
    const init = { method, headers: {} };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const r = await fetch(BASE + path, init);
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
    login:         (password)               => call("POST",   "/auth/login",                       { password }),

    listGlossary:  (q, cat, limit, offset)  => call("GET",    `/glossary?q=${encodeURIComponent(q||"")}&cat=${encodeURIComponent(cat||"")}&limit=${limit||200}&offset=${offset||0}`),
    listProjects:  ()                       => call("GET",    "/projects"),
    getProject:    (pid)                    => call("GET",    `/projects/${pid}`),
    createProject: (info)                   => call("POST",   "/projects",                          info),
    deleteProject: (pid)                    => call("DELETE", `/projects/${pid}`),
    uploadProject: async (file, title, src, tgt) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", title || "");
      fd.append("src",   src  || "RU");
      fd.append("tgt",   tgt  || "EN");
      const r = await fetch((window.API_BASE || "") + "/api/projects/upload", { method: "POST", body: fd });
      if (!r.ok) { const t = await r.text().catch(() => ""); throw new Error("Upload failed: " + r.status + " " + t); }
      return r.json();
    },

    models:        ()                       => call("GET",    "/models"),
    translate:     (pid, sid, engine, force, model) => call("POST", `/segments/${pid}/${sid}/translate`, { engine, force: !!force, model: model || null }),
    backcheck:     (pid, sid, model, judge) => call("POST",   `/segments/${pid}/${sid}/backcheck`,  { model: model || null, use_judge: !!judge }),
    backcheckBatch:(pid, segIds, limit, model, judge) => call("POST", `/projects/${pid}/backcheck/batch`, { segment_ids: segIds || null, limit: limit || 10, model: model || null, use_judge: !!judge }),
    medicalQA:     (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/medical-qa`,  { run_backcheck: true }),
    qa:            (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/qa`),
    confirm:       (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/confirm`),
    revert:        (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/revert`),
    update:        (pid, sid, patch)        => call("POST",   `/segments/${pid}/${sid}/update`,     patch),

    batch:         (pid, engine, segIds, force, limit, model) => call("POST", `/projects/${pid}/batch`, { engine, segment_ids: segIds || null, force: !!force, limit: limit || 50, model: model || null }),
    medicalQABatch:(pid, segIds)             => call("POST",   `/projects/${pid}/medical-qa/batch`,   { segment_ids: segIds || null, run_backcheck: true }),
    preflight:     (pid)                    => call("POST",   `/projects/${pid}/preflight`),
    exportProject: (pid, format, source)    => call("POST",   `/projects/${pid}/export`,            { format, source: source !== false }),

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
