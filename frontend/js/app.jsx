/* ============================================================
   App shell — store, auth, header, tab routing
   ============================================================ */
function useStore(authed) {
  const [projects, setProjects] = useState(() => JSON.parse(JSON.stringify(window.SEED.projects)));
  const [glossary, setGlossary] = useState(() => window.SEED.glossary.slice());
  const [tm, setTM] = useState(() => window.SEED.tm.slice());
  const [exportHistory, setExportHistory] = useState(() => window.SEED.exportHistory.slice());
  const [activeId, setActiveId] = useState(7);
  const [tab, setTab] = useState("editor");
  const [apiReady, setApiReady] = useState(false);
  const [segmentFilter, setSegmentFilterState] = useState(null); // Set<id> | null
  const [gotoSegId, setGotoSegId] = useState(null);

  const me = { name: "Вы", initials: "ВЫ", color: "var(--c-primary)" };
  const activeProject = projects.find(p => p.id === activeId) || null;

  /* Hydrate from backend after login; fall back to SEED if backend unreachable.
     Ждём именно authed: без токена /api/seed отдаст 401, и в UI остались бы моки. */
  useEffect(() => {
    let cancelled = false;
    if (authed && window.API) {
      window.API.seed().then(d => {
        if (cancelled || !d) return;
        if (d.projects) setProjects(d.projects);
        if (d.glossary) setGlossary(d.glossary);
        if (d.tm) setTM(d.tm);
        if (d.exportHistory) setExportHistory(d.exportHistory);
        if (d.projects && d.projects.length && !d.projects.find(p => p.id === activeId))
          setActiveId(d.projects[0].id);
        setApiReady(true);
      }).catch(e => {
        console.warn("[store] /api/seed unavailable, using local mock data:", e.message);
      });
    }
    return () => { cancelled = true; };
  }, [authed]);

  const statusCounts = (p) => {
    const out = { all: p.segments.length, new: 0, translated: 0, qa: 0, confirmed: 0, failed: 0, review: 0 };
    p.segments.forEach(s => { out[s.status] = (out[s.status] || 0) + 1; });
    return out;
  };

  // Local state mutators (used for optimistic updates + fallback)
  const _patchLocal = (pid, sid, patch) => setProjects(ps => ps.map(p => p.id !== pid ? p : ({
    ...p, segments: p.segments.map(s => s.id === sid ? { ...s, ...patch } : s) })));

  const updateSegment = (pid, sid, patch) => {
    _patchLocal(pid, sid, patch);
    // Sync to backend (best-effort)
    if (window.API && patch && (patch.target !== undefined || patch.status !== undefined)) {
      window.API.safeCall(() => window.API.update(pid, sid, {
        target: patch.target, status: patch.status,
      }));
    }
  };

  const addComment = (pid, sid, text) => {
    setProjects(ps => ps.map(p => p.id !== pid ? p : ({
      ...p, segments: p.segments.map(s => s.id === sid ? { ...s, comments: [...s.comments, { author: me, when: "только что", text }] } : s) })));
    if (window.API) {
      window.API.safeCall(() => window.API.update(pid, sid, { comment: text, commentAuthor: me }));
    }
  };

  const createProject = (info) => {
    // Optimistic local create; if backend is up it will replace IDs on refresh.
    const id = Math.max(0, ...projects.map(p => p.id)) + 1;
    const np = { id, title: info.title, titleEn: info.title, src: info.src, tgt: info.tgt, status: "in_progress",
      created: new Date().toISOString().slice(0, 10), deadline: "",
      segments: window.SEED.projects[0].segments.slice(0, 8).map((s, i) => ({ ...s, id: i + 1, target: "", status: "new", comments: [], qa: [] })) };
    setProjects(ps => [np, ...ps]);
    if (window.API) {
      window.API.safeCall(() => window.API.createProject({
        title: info.title, src: info.src, tgt: info.tgt, fileName: info.fileName,
      })).then(real => {
        if (real && real.id) {
          // Replace optimistic project with real one from backend
          setProjects(ps => ps.map(p => p.id === id ? real : p));
          setActiveId(real.id);
        }
      });
    }
    return id;
  };

  const addProject = (project) => setProjects(ps => [project, ...ps.filter(p => p.id !== project.id)]);
  const openProject = (id) => { setActiveId(id); setTab("editor"); };
  const replaceProjectSegments = (pid, segments) =>
    setProjects(ps => ps.map(p => p.id !== pid ? p : { ...p, segments }));
  const deleteProject = (id) => {
    setProjects(ps => ps.filter(p => p.id !== id));
    if (activeId === id) setActiveId(null);
    window.API.safeCall(() => window.API.deleteProject(id));
  };

  /* Записи с одинаковым src, но разной областью — теперь норма, поэтому
     локальное обновление сверяет и область: иначе правка RU→EN термина
     затирала бы в таблице его RU→DE тёзку, а удаление убирало бы обоих. */
  const sameEntry = (a, b) => a.src === b.src
    && (a.lang || "RU→EN") === (b.lang || "RU→EN")
    && (a.domain || "medical") === (b.domain || "medical");

  const saveTerm = (term, isNew) => {
    setGlossary(g => isNew ? [term, ...g] : g.map(t => sameEntry(t, term) ? term : t));
    if (window.API) window.API.safeCall(() => window.API.saveTerm(term, isNew));
  };

  const deleteTerm = (term) => {
    setGlossary(g => g.filter(t => !sameEntry(t, term)));
    if (window.API) window.API.safeCall(() => window.API.deleteTerm(term.src, term.lang, term.domain));
  };

  const deleteTM = (entry) => {
    setTM(t => t.filter(x => !(x.src === entry.src
      && (x.lang || "RU→EN") === (entry.lang || "RU→EN"))));
    if (window.API) window.API.safeCall(() => window.API.deleteTM(entry.src, entry.lang));
  };

  return {
    projects, glossary, tm, activeId, activeProject, tab,
    exportHistory, team: window.SEED.team, me, apiReady,
    segmentFilter, gotoSegId,
    go: setTab, statusCounts, updateSegment, addComment, createProject, addProject, openProject, deleteProject, replaceProjectSegments, saveTerm, deleteTerm, deleteTM,
    setExportHistory,
    setSegmentFilter: (ids) => {
      const f = ids && ids.length ? new Set(ids) : null;
      window._mcat_sf = f; // synchronous bridge for TabEditor first render
      setSegmentFilterState(f);
    },
    goToSegment: (id) => { window._mcat_sf = null; setSegmentFilterState(null); setGotoSegId(id); setTab("editor"); },
    clearGotoSeg: () => setGotoSegId(null),
  };
}

/* ---------- Theme ---------- */
function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("mct-theme") || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); }
    catch (e) { return "light"; }
  });
  useEffect(() => {
    const el = document.documentElement;
    el.classList.add("theme-switching");
    el.setAttribute("data-theme", theme);
    try { localStorage.setItem("mct-theme", theme); } catch (e) {}
    const id = requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("theme-switching")));
    return () => cancelAnimationFrame(id);
  }, [theme]);
  return [theme, () => setTheme(t => t === "dark" ? "light" : "dark")];
}
function ThemeToggle({ theme, onToggle }) {
  return React.createElement(IconBtn, { icon: theme === "dark" ? "sun" : "moon", label: theme === "dark" ? "Светлая тема" : "Тёмная тема", onClick: onToggle });
}

/* ---------- Auth screen ---------- */
function AuthScreen({ onLogin, theme, onToggleTheme }) {
  const [pw, setPw] = useState("");
  const [shake, setShake] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (!pw.length) { setShake(true); setTimeout(() => setShake(false), 400); return; }
    setBusy(true);
    /* Без токена от сервера входа нет: раньше сетевая ошибка пускала внутрь
       на локальных мок-данных, и это же скрывало отсутствие реальной защиты. */
    let ok = false;
    try {
      await window.API.login(pw);
      ok = true;
    } catch (e2) {
      if (e2.status === 401) setErr("Неверный пароль");
      else if (e2.status === 429) setErr("Слишком много попыток. Повторите через 15 минут.");
      else setErr("Сервер недоступен — вход невозможен");
    }
    setBusy(false);
    if (ok) onLogin();
    else { setShake(true); setTimeout(() => setShake(false), 400); }
  };
  return React.createElement("div", { className: "auth-wrap" },
    React.createElement("div", { className: "auth-theme" }, React.createElement(ThemeToggle, { theme, onToggle: onToggleTheme })),
    React.createElement("form", { className: "auth-card", onSubmit: submit, style: shake ? { animation: "pop .1s, shake .4s" } : null },
      React.createElement("div", { className: "auth-logo" }, React.createElement(Icon, { name: "hospital", size: 28 })),
      React.createElement("h1", null, "Medical CAT Translator"),
      React.createElement("p", { className: "auth-sub" }, "Система перевода медицинских документов · v5.5"),
      React.createElement(Field, { label: "Пароль доступа" },
        React.createElement("div", { className: "search" },
          React.createElement(Icon, { name: "lock", size: 17 }),
          React.createElement("input", { className: "input", style: { paddingLeft: 38 }, type: "password", value: pw,
            onChange: (e) => setPw(e.target.value), placeholder: "Введите пароль", autoFocus: true }))),
      err && React.createElement("div", { style: { color: "var(--c-danger)", fontSize: 13, marginTop: 8 } }, err),
      React.createElement("div", { className: "row", style: { gap: 10, marginTop: 20 } },
        React.createElement(Btn, { variant: "primary", type: "submit", icon: "unlock", className: "btn-block", disabled: busy }, busy ? "Проверка..." : "Войти"),
        React.createElement(Btn, { variant: "secondary", type: "button", icon: "info", onClick: () => alert("Пароль выдаёт администратор сервиса (переменная окружения APP_PASSWORD на сервере).") }, "Справка")),
      React.createElement("p", { className: "auth-foot" }, "© 2026 Medical CAT Translator · Конфиденциально")
    )
  );
}

/* ---------- Header ---------- */
function Header({ store, theme, onToggleTheme, onLogout, onSearch }) {
  return React.createElement("header", { className: "header" },
    React.createElement("div", { className: "brand" },
      React.createElement("div", { className: "brand-mark" }, React.createElement(Icon, { name: "hospital", size: 20 })),
      React.createElement("div", null,
        React.createElement("div", { className: "brand-title" }, "Medical CAT Translator"),
        React.createElement("div", { className: "brand-sub" }, "v5.5 · " + (store.activeProject ? store.activeProject.title : "Нет проекта")))),
    React.createElement("div", { className: "spacer" }),
    React.createElement("div", { className: "h-actions" },
      React.createElement(IconBtn, { icon: "search", label: "Поиск", onClick: onSearch }),
      React.createElement(ThemeToggle, { theme, onToggle: onToggleTheme }),
      React.createElement(IconBtn, { icon: "settings", label: "Настройки" }),
      React.createElement("div", { style: { width: 1, height: 26, background: "var(--border)", margin: "0 6px" } }),
      React.createElement(Avatar, { person: store.me, size: 32 }),
      React.createElement(IconBtn, { icon: "logout", label: "Выйти", onClick: onLogout }))
  );
}

/* ---------- Tabs ---------- */
const TABS = [
  { key: "import", label: "Импорт", icon: "upload" },
  { key: "editor", label: "Редактор", icon: "edit" },
  { key: "glossary", label: "Глоссарий", icon: "book" },
  { key: "tm", label: "Память (TM)", icon: "repeat" },
  { key: "export", label: "Экспорт", icon: "download" },
  { key: "preflight", label: "Анализ", icon: "target" },
  { key: "qa", label: "QA", icon: "shield" },
  { key: "backlog", label: "Бэклог", icon: "columns" },
  { key: "stats", label: "Статистика", icon: "chart" },
];
function TabBar({ store }) {
  const counts = store.activeProject ? store.statusCounts(store.activeProject) : null;
  const badgeFor = (k) => {
    if (!counts) return null;
    if (k === "editor") return counts.all;
    if (k === "qa") return counts.failed + counts.qa || null;
    if (k === "glossary") return store.glossary.length;
    return null;
  };
  return React.createElement("nav", { className: "tabbar", role: "tablist" },
    TABS.map(t => {
      const b = badgeFor(t.key);
      return React.createElement("button", { key: t.key, className: "tab" + (store.tab === t.key ? " active" : ""),
        role: "tab", "aria-selected": store.tab === t.key, onClick: () => store.go(t.key) },
        React.createElement(Icon, { name: t.icon, size: 17 }), t.label,
        b != null && React.createElement("span", { className: "tab-count" }, b));
    })
  );
}

/* ---------- Search palette ---------- */
function SearchPalette({ store, onClose }) {
  const [q, setQ] = useState("");
  const results = [];
  if (store.activeProject) store.activeProject.segments.forEach(s => {
    if (q && (s.source.toLowerCase().includes(q.toLowerCase()) || (s.target || "").toLowerCase().includes(q.toLowerCase())))
      results.push({ type: "Сегмент #" + s.id, text: s.source, action: () => { store.go("editor"); onClose(); } });
  });
  store.glossary.forEach(g => { if (q && g.src.toLowerCase().includes(q.toLowerCase())) results.push({ type: "Глоссарий", text: g.src + " → " + g.tgt, action: () => { store.go("glossary"); onClose(); } }); });
  return React.createElement(Modal, { title: "Поиск по проекту", icon: "search", onClose },
    React.createElement(Input, { value: q, onChange: (e) => setQ(e.target.value), placeholder: "Сегменты, термины…", autoFocus: true }),
    React.createElement("div", { className: "col", style: { gap: 6, maxHeight: 320, overflow: "auto" } },
      q && results.length === 0 && React.createElement("p", { className: "dim", style: { fontSize: 13, padding: 8 } }, "Ничего не найдено."),
      results.slice(0, 20).map((r, i) => React.createElement("button", { key: i, className: "card", style: { padding: "10px 12px", textAlign: "left", cursor: "pointer" }, onClick: r.action },
        React.createElement("div", { className: "dim", style: { fontSize: 11, fontWeight: 600 } }, r.type),
        React.createElement("div", { style: { fontSize: 13, marginTop: 2 } }, r.text)))));
}

/* ---------- Root App ---------- */
function App() {
  /* Токен в sessionStorage переживает F5, но не закрытие вкладки. */
  const [authed, setAuthed] = useState(() => !!(window.API && window.API.hasToken()));
  const [theme, toggleTheme] = useTheme();
  const store = useStore(authed);
  const toast = useToast();
  const [search, setSearch] = useState(false);

  useEffect(() => {
    const h = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); setSearch(true); } };
    window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h);
  }, []);

  /* Любой 401 из api.js (истёк токен, рестарт бэкенда) → обратно на вход. */
  useEffect(() => {
    const h = () => setAuthed(false);
    window.addEventListener("mct-auth-expired", h);
    return () => window.removeEventListener("mct-auth-expired", h);
  }, []);

  if (!authed) return React.createElement(AuthScreen, { onLogin: () => { setAuthed(true); toast.success("Добро пожаловать", "Вы вошли в систему."); }, theme, onToggleTheme: toggleTheme });

  const tabMap = {
    import: TabImport, editor: TabEditor, glossary: TabGlossary, tm: TabTM,
    export: TabExport, preflight: TabPreflight, qa: TabQA, backlog: TabBacklog, stats: TabStats,
  };
  const Active = tabMap[store.tab] || TabEditor;

  return React.createElement("div", { className: "app" },
    React.createElement(Header, { store, theme, onToggleTheme: toggleTheme,
      /* Перезагрузка после выхода: иначе документы пациентов остаются в памяти вкладки. */
      onLogout: () => {
        const done = () => window.location.reload();
        if (window.API) window.API.logout().then(done, done); else done();
      },
      onSearch: () => setSearch(true) }),
    React.createElement(TabBar, { store }),
    React.createElement("main", { className: "main" }, React.createElement(Active, { store, toast })),
    search && React.createElement(SearchPalette, { store, onClose: () => setSearch(false) })
  );
}

function Root() { return React.createElement(ToastProvider, null, React.createElement(App, null)); }
ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(Root, null));
