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

    listProjects:  ()                       => call("GET",    "/projects"),
    getProject:    (pid)                    => call("GET",    `/projects/${pid}`),
    createProject: (info)                   => call("POST",   "/projects",                          info),

    translate:     (pid, sid, engine)       => call("POST",   `/segments/${pid}/${sid}/translate`,  { engine }),
    qa:            (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/qa`),
    confirm:       (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/confirm`),
    revert:        (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/revert`),
    update:        (pid, sid, patch)        => call("POST",   `/segments/${pid}/${sid}/update`,     patch),

    batch:         (pid, engine)            => call("POST",   `/projects/${pid}/batch`,             { engine }),
    preflight:     (pid)                    => call("POST",   `/projects/${pid}/preflight`),
    exportProject: (pid, format)            => call("POST",   `/projects/${pid}/export`,            { format }),

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
