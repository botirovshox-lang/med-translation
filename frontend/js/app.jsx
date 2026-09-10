/* ============================================================
   App shell — store, auth, header, tab routing
   ============================================================ */
function useStore(authed) {
  /* Стартуем с пустого: мок data.js показывал выдуманный чужой проект,
     пока грузился /api/seed, а активным проектом стоял его номер 7. */
  const [projects, setProjects] = useState([]);
  const [glossary, setGlossary] = useState([]);
  const [tm, setTM] = useState([]);
  const [exportHistory, setExportHistory] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [tab, setTab] = useState("editor");
  const [apiReady, setApiReady] = useState(false);
  const [segmentFilter, setSegmentFilterState] = useState(null); // Set<id> | null
  const [gotoSegId, setGotoSegId] = useState(null);

  /* Кто я — с сервера (/api/auth/me), а не заглушка: аватар, роль и то,
     какие кнопки показывать. Право СДЕЛАТЬ проверяет сервер. */
  const [me, setMe] = useState({ name: TR("Вы"), initials: TR("ВЫ"), color: "var(--c-primary)", role: "translator" });
  const [can, setCan] = useState({ owner: false, super: false });
  const [brand, setBrand] = useState("CAT Translator");
  /* Команды и приглашения нужны ШАПКЕ: переключатель рабочего пространства
     и счётчик «вас куда-то зовут». Приезжают тем же /auth/me — второй
     запрос ради двух чисел не нужен. */
  const [teams, setTeams] = useState([]);
  const [tenant, setTenant] = useState(null);
  const [invites, setInvites] = useState([]);
  /* Страницы — то, чем организация меряет свою работу. Сервер их уже
     отдаёт в /api/auth/me, браузер до сих пор выбрасывал. */
  const [caps, setCaps] = useState(null);
  const [usage, setUsage] = useState(null);
  useEffect(() => {
    if (!authed || !window.API || !window.API.me) return;
    let cancelled = false;
    window.API.safeCall(() => window.API.me()).then(r => {
      if (cancelled || !r || !r.me) return;
      setMe(r.me); setCan(r.can || { owner: false, super: false });
      setTeams(r.teams || []); setTenant(r.tenant || null); setInvites(r.invites || []);
      setCaps(r.caps || null); setUsage(r.usage || null);
      /* Источник правды про язык — ЗАПИСЬ ПОЛЬЗОВАТЕЛЯ: он переезжает на
         другой компьютер вместе с человеком. localStorage — только кэш,
         чтобы экран ВХОДА не мигал чужим языком. Разошлись — верим серверу
         и перезагружаемся ОДИН раз: setLang перезагружает лишь при
         настоящем расхождении, поэтому петли нет. */
      if (window.I18N && r.me.uiLang && r.me.uiLang !== window.I18N.lang)
        window.I18N.setLang(r.me.uiLang);
      if (window.ADMIN_ENTRY && r.can && r.can.super) setTab("admin");
    });
    window.API.safeCall(() => window.API.models()).then(r => {
      if (!cancelled && r && r.brand) setBrand(r.brand);
    });
    return () => { cancelled = true; };
  }, [authed]);
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
    // Перевод изменился — значит проверки к нему больше не относятся. Признак
    // stale считает сервер по хешу, браузеру sha1 не посчитать; но факт правки
    // он знает точно, и молчать о нём нельзя: иначе прогон пропустит изменённый
    // сегмент как «уже проверенный».
    if (patch && patch.target !== undefined) {
      const mark = (c) => (c ? { ...c, stale: true } : c);
      const cur = (projects.find(p => p.id === pid) || {}).segments || [];
      const seg = cur.find(s => s.id === sid);
      if (seg) patch = { ...patch,
        backcheck: mark(seg.backcheck), termcheck: mark(seg.termcheck),
        qa_result: mark(seg.qa_result) };
    }
    _patchLocal(pid, sid, patch);
    // Sync to backend (best-effort)
    if (window.API && patch && (patch.target !== undefined || patch.status !== undefined)) {
      window.API.safeCall(() => window.API.update(pid, sid, {
        target: patch.target, status: patch.status,
      })).then(r => {
        /* Сервер вправе ответить ДРУГИМ статусом: правка заверенного текста
           снимает подпись («подтвердил человек» относилась к прежнему
           тексту), и копия в браузере обязана это увидеть — иначе на экране
           стоит отметка, которой на сервере больше нет. */
        if (r && r.segment && r.segment.status && r.segment.status !== patch.status)
          _patchLocal(pid, sid, { status: r.segment.status, confirmedBy: r.segment.confirmedBy,
                                  confirmedAt: r.segment.confirmedAt, confirmedRole: r.segment.confirmedRole,
                                  confirmedByName: r.segment.confirmedByName,
                                  unconfirmed: r.segment.unconfirmed, prevTarget: r.segment.prevTarget });
      });
    }
  };

  const addComment = (pid, sid, text) => {
    setProjects(ps => ps.map(p => p.id !== pid ? p : ({
      ...p, segments: p.segments.map(s => s.id === sid ? { ...s, comments: [...s.comments, { author: me, when: TR("только что"), text }] } : s) })));
    if (window.API) {
      window.API.safeCall(() => window.API.update(pid, sid, { comment: text, commentAuthor: me }));
    }
  };

  const createProject = (info) => {
    // Optimistic local create; if backend is up it will replace IDs on refresh.
    const id = Math.max(0, ...projects.map(p => p.id)) + 1;
    const np = { id, title: info.title, titleEn: info.title, src: info.src, tgt: info.tgt, status: "in_progress",
      created: new Date().toISOString().slice(0, 10), deadline: "",
      segments: [] };
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
  /* Правка полей проекта БЕЗ его перезагрузки и без изменения порядка списка:
     проект на 2670 сегментов весит 5 МБ, и тянуть его ради одной отметки
     (например, о приложенном исходнике) — мегабайты трафика на пустом месте. */
  const patchProject = (pid, patch) =>
    setProjects(ps => ps.map(p => p.id !== pid ? p : { ...p, ...patch }));
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
    && (a.domain || LEGACY_DOMAIN) === (b.domain || LEGACY_DOMAIN);

  const saveTerm = (term, isNew) => {
    setGlossary(g => isNew ? [term, ...g] : g.map(t => sameEntry(t, term) ? term : t));
    if (window.API) window.API.safeCall(() => window.API.saveTerm(term, isNew));
  };

  const deleteTerm = (term) => {
    setGlossary(g => g.filter(t => !sameEntry(t, term)));
    if (window.API) window.API.safeCall(() => window.API.deleteTerm(term.src, term.lang, term.domain, term.project));
  };

  const deleteTM = (entry) => {
    setTM(t => t.filter(x => !(x.src === entry.src
      && (x.lang || "RU→EN") === (entry.lang || "RU→EN"))));
    if (window.API) window.API.safeCall(() => window.API.deleteTM(entry.src, entry.lang, entry.project));
  };

  return {
    projects, glossary, tm, activeId, activeProject, tab,
    exportHistory, team: [], me, can, brand, apiReady, setGlossary,
    segmentFilter, gotoSegId,
    go: setTab, statusCounts, updateSegment, addComment, createProject, addProject, patchProject, openProject, deleteProject, replaceProjectSegments, saveTerm, deleteTerm, deleteTM,
    setExportHistory,
    setSegmentFilter: (ids) => {
      const f = ids && ids.length ? new Set(ids) : null;
      window._mcat_sf = f; // synchronous bridge for TabEditor first render
      setSegmentFilterState(f);
    },
    goToSegment: (id) => { window._mcat_sf = null; setSegmentFilterState(null); setGotoSegId(id); setTab("editor"); },
    teams, tenant, invites, caps, usage,
    clearGotoSeg: () => setGotoSegId(null),
  };
}

/* ---------- Theme ---------- */
function useTheme() {
  const [theme, setTheme] = useState(() => {
    /* По умолчанию СВЕТЛАЯ, а не системная: инструмент открывают в рабочий
       день рядом с бумажным оригиналом, и тёмный лист рядом с белой бумагой
       читается хуже. Свой выбор человека сильнее и живёт в localStorage. */
    try { return localStorage.getItem("mct-theme") || "light"; }
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
  return React.createElement(IconBtn, { icon: theme === "dark" ? "sun" : "moon", label: theme === "dark" ? TR("Светлая тема") : TR("Тёмная тема"), onClick: onToggle });
}

/* ---------- Auth screen ---------- */
function AuthScreen({ onLogin, theme, onToggleTheme }) {
  /* Четыре состояния одной двери: вход, регистрация, код из письма,
     восстановление пароля. Регистрация показывается, только если сервер
     говорит, что она открыта (/auth/signup-info) — выключенная кнопка,
     ведущая в 403, хуже отсутствующей. */
  const [mode, setMode] = useState("login");   // login | register | verify | forgot | reset
  const [info, setInfo] = useState({ signup: false, mail: false, brand: "CAT Translator", trialUsd: 0 });
  const [f, setF] = useState({ login: "", password: "", email: "", org: "", name: "", code: "" });
  const [accepted, setAccepted] = useState(false);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [shake, setShake] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    window.API && window.API.safeCall(() => window.API.signupInfo()).then(r => r && setInfo(r));
  }, []);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const bad = (m) => { setErr(m); setShake(true); setTimeout(() => setShake(false), 400); };
  const go = (m) => { setMode(m); setErr(""); setNote(""); };
  const msg = (e) => (e && e.message) ? e.message : TR("Сервер недоступен");

  const submit = async (ev) => {
    ev.preventDefault();
    setErr(""); setNote(""); setBusy(true);
    try {
      if (mode === "login") {
        if (!f.password) throw new Error(TR("Введите пароль"));
        await window.API.login(f.login, f.password);
        onLogin();
      } else if (mode === "register") {
        const r = await window.API.register({ email: f.email, password: f.password,
                                              org: f.org, name: f.name, accept: accepted });
        setNote(r.note || TR("Код отправлен на почту."));
        setMode("verify");
      } else if (mode === "verify") {
        await window.API.verifyEmail(f.email, f.code);
        onLogin();
      } else if (mode === "forgot") {
        await window.API.forgotPassword(f.email);
        setNote(TR("Если такая почта у нас есть, письмо с кодом уже ушло."));
        setMode("reset");
      } else if (mode === "reset") {
        await window.API.resetPassword(f.email, f.code, f.password);
        onLogin();
      }
    } catch (e) {
      if (e.status === 401) bad(TR("Неверный логин или пароль"));
      else if (e.status === 429) bad(msg(e));
      else bad(msg(e));
    }
    setBusy(false);
  };

  const field = (label, key, type, ph, extra) => React.createElement(Field, { label, key: key },
    React.createElement("input", Object.assign({
      className: "input", type: type || "text", value: f[key], onChange: set(key), placeholder: ph,
    }, extra || {})));
  const title = { login: TR("Вход"), register: TR("Регистрация"), verify: TR("Код из письма"),
                  forgot: TR("Восстановление пароля"), reset: TR("Новый пароль") }[mode];
  const sub = {
    login: TR("Система перевода документов с проверками"),
    register: TR("Своя организация: проекты, глоссарий и память переводов видите только вы"),
    verify: TR("Мы отправили шестизначный код на ") + (f.email || TR("вашу почту")),
    forgot: TR("Пришлём код на почту, которой вы регистрировались"),
    reset: TR("Введите код из письма и новый пароль"),
  }[mode];

  const rows = [];
  if (mode === "login") {
    rows.push(field(TR("Логин или почта"), "login", "text", TR("admin или you@mail.com"), { autoComplete: "username", autoFocus: true }));
    rows.push(field(TR("Пароль"), "password", "password", "", { autoComplete: "current-password" }));
  } else if (mode === "register") {
    rows.push(field(TR("Рабочая почта"), "email", "email", "you@company.com", { autoComplete: "email", autoFocus: true }));
    rows.push(field(TR("Название организации"), "org", "text", TR("напр. Бюро переводов")));
    rows.push(field(TR("Ваше имя"), "name", "text", TR("необязательно")));
    rows.push(field(TR("Пароль (от 8 символов)"), "password", "password", "", { autoComplete: "new-password" }));
  } else if (mode === "verify") {
    rows.push(field(TR("Почта"), "email", "email", "", { autoComplete: "email" }));
    rows.push(field(TR("Код из письма"), "code", "text", "123456", { inputMode: "numeric", autoFocus: true }));
  } else if (mode === "forgot") {
    rows.push(field(TR("Почта"), "email", "email", "you@company.com", { autoComplete: "email", autoFocus: true }));
  } else if (mode === "reset") {
    rows.push(field(TR("Почта"), "email", "email", "", { autoComplete: "email" }));
    rows.push(field(TR("Код из письма"), "code", "text", "123456", { inputMode: "numeric", autoFocus: true }));
    rows.push(field(TR("Новый пароль (от 8)"), "password", "password", "", { autoComplete: "new-password" }));
  }

  const link = (label, m) => React.createElement("button", {
    type: "button", className: "linklike", onClick: () => go(m),
    style: { background: "none", border: 0, color: "var(--c-primary)", cursor: "pointer", fontSize: 13, padding: 0 },
  }, label);

  return React.createElement("div", { className: "auth-wrap" },
    React.createElement("div", { className: "auth-theme" }, React.createElement(ThemeToggle, { theme, onToggle: onToggleTheme })),
    React.createElement("form", { className: "auth-card", onSubmit: submit, style: shake ? { animation: "pop .1s, shake .4s" } : null },
      /* Марка с названием — строка .auth-brand макета, а не одинокий значок:
         название сервиса на экране входа берётся с сервера (APP_BRAND). */
      React.createElement("div", { className: "auth-brand" },
        React.createElement("span", { className: "auth-logo" }, React.createElement(Icon, { name: "globe", size: 11 })),
        info.brand || "CAT Translator"),
      React.createElement("h1", null, title),
      React.createElement("p", { className: "auth-sub" }, sub),
      React.createElement("div", { className: "col", style: { gap: 4 } }, rows),
      /* Почта на сервере не настроена — говорим об этом ДО того, как человек
         нажмёт «Зарегистрироваться» и уйдёт ждать письма, которого не будет. */
      mode === "register" && !info.mail && React.createElement("div", { className: "dim", style: { fontSize: 12, marginTop: 8 } },
        TR("Отправка почты на сервере не настроена: код придётся взять у администратора.")),
      /* Согласие — условие заключения договора: сервер откажет без него,
         поэтому и кнопка погашена. Ссылки открываются в новой вкладке,
         чтобы человек не потерял заполненную форму. */
      mode === "register" && React.createElement("label", {
        className: "row", style: { gap: 8, alignItems: "flex-start", marginTop: 12, fontSize: 13 } },
        React.createElement("input", { type: "checkbox", checked: accepted, style: { marginTop: 3 },
          onChange: (e) => setAccepted(e.target.checked) }),
        React.createElement("span", null, TR("Принимаю "),
          React.createElement("a", { href: (info.legal || {}).terms || "/terms", target: "_blank", rel: "noopener" }, TR("оферту")),
          TR(" и "),
          React.createElement("a", { href: (info.legal || {}).privacy || "/privacy", target: "_blank", rel: "noopener" },
            TR("политику обработки персональных данных")),
          TR(". Загружаемые документы обрабатываются языковой моделью стороннего поставщика."))),
      note && React.createElement("div", { style: { color: "var(--c-info)", fontSize: 13, marginTop: 8 } }, note),
      err && React.createElement("div", { style: { color: "var(--c-danger)", fontSize: 13, marginTop: 8 } }, err),
      React.createElement("div", { className: "row", style: { gap: 10, marginTop: 18 } },
        React.createElement(Btn, { variant: "primary", type: "submit", icon: "unlock", className: "btn-block",
          disabled: busy || (mode === "register" && !accepted) },
          busy ? TR("Минуту…") : { login: TR("Войти"), register: TR("Зарегистрироваться"), verify: TR("Подтвердить"),
                               forgot: TR("Прислать код"), reset: TR("Сменить пароль") }[mode])),
      React.createElement("div", { className: "row row-wrap", style: { gap: 14, marginTop: 14, justifyContent: "center" } },
        mode !== "login" && link(TR("← Ко входу"), "login"),
        mode === "login" && info.signup && link(TR("Создать организацию"), "register"),
        mode === "login" && link(TR("Забыли пароль?"), "forgot"),
        mode === "verify" && React.createElement("button", {
          type: "button", style: { background: "none", border: 0, color: "var(--c-primary)", cursor: "pointer", fontSize: 13, padding: 0 },
          onClick: () => window.API.safeCall(() => window.API.resendCode(f.email)).then(() => setNote(TR("Код отправлен заново."))),
        }, TR("Прислать код заново"))),
      React.createElement("p", { className: "auth-foot" },
        React.createElement("a", { href: "/terms", target: "_blank", rel: "noopener" }, TR("Оферта")),
        " · ",
        React.createElement("a", { href: "/privacy", target: "_blank", rel: "noopener" }, TR("Персональные данные")))
    )
  );
}

function TeamSwitcher({ store }) {
  const teams = store.teams || [];
  if (teams.length < 2) return null;
  const active = (store.tenant && store.tenant.id) || "";
  return React.createElement("select", {
    className: "select", value: active, "aria-label": TR("Команда"),
    style: { height: 32, maxWidth: 200, fontSize: 13 },
    onChange: (e) => {
      const tid = e.target.value;
      if (tid === active) return;
      window.API.safeCall(() => window.API.teamSwitch(tid))
        .then(() => window.location.reload());
    },
  }, teams.map(t => React.createElement("option", { key: t.id, value: t.id }, t.name)));
}

function Header({ store, theme, onToggleTheme, onLogout, onSearch }) {
  return React.createElement("header", { className: "header" },
    React.createElement("div", { className: "brand" },
      React.createElement("div", { className: "brand-mark" }, React.createElement(Icon, { name: "globe", size: 20 })),
      React.createElement("div", null,
        React.createElement("div", { className: "brand-title" }, store.brand || "CAT Translator"),
        React.createElement("div", { className: "brand-sub" }, store.activeProject ? store.activeProject.title : TR("Нет проекта")))),
    React.createElement("div", { className: "spacer" }),
    React.createElement("div", { className: "h-actions" },
      React.createElement(IconBtn, { icon: "search", label: TR("Поиск"), onClick: onSearch }),
      React.createElement(ThemeToggle, { theme, onToggle: onToggleTheme }),
      /* Мёртвая кнопка неотличима от сломанной: у владельца она ведёт
         на экран организации, остальным не показывается. */
      store.can && store.can.owner && React.createElement(IconBtn, { icon: "settings", label: TR("Организация"), onClick: () => store.go("org") }),
      React.createElement("div", { style: { width: 1, height: 26, background: "var(--border)", margin: "0 6px" } }),
      React.createElement(TeamSwitcher, { store }),
      /* Аватар — дверь в профиль, а не украшение: единственный экран, где
         человек меняет язык, пароль и отвечает на приглашения. */
      React.createElement("button", {
        className: "iconbtn", title: (store.me.name || "") + (store.can && store.can.role ? " · " + roleLabel(store.can.role) : ""),
        "aria-label": TR("Профиль"), onClick: () => store.go("profile"),
        style: { position: "relative", padding: 0, background: "none", border: "none", cursor: "pointer" } },
        React.createElement(Avatar, { person: store.me, size: 32 }),
        store.invites && store.invites.length > 0 && React.createElement("span", {
          style: { position: "absolute", top: -2, right: -2, minWidth: 16, height: 16, borderRadius: 8,
                   background: "var(--c-danger)", color: "var(--text-on-accent)", fontSize: 10, fontWeight: 600,
                   lineHeight: "16px", textAlign: "center", padding: "0 3px" } }, store.invites.length)),
      React.createElement(IconBtn, { icon: "logout", label: TR("Выйти"), onClick: onLogout }))
  );
}

/* ---------- Tabs ---------- */
/* Пять вкладок вместо девяти. Слиты те, что отвечали на один вопрос в разных
   местах: глоссарий и память — обе справочные базы одной области; «Анализ»
   и «QA» — обе про «что не так и во что обойдётся», просто до и после прогона.
   Бэклог и статистика — командные инструменты, они уехали внутрь «Анализа». */
/* group — колонка бокового меню. Порядок групп: сначала работа над текстом,
   потом файлы и настройки, потом служебное. */
const TABS = [
  { key: "import", label: TR("Импорт"), icon: "upload", group: "files" },
  { key: "editor", label: TR("Редактор"), icon: "edit", group: "work" },
  { key: "glossary", label: TR("Знания"), icon: "book", group: "work" },
  { key: "preflight", label: TR("Анализ"), icon: "target", group: "work" },
  { key: "export", label: TR("Экспорт"), icon: "download", group: "work" },
  /* Профиль — ВСЕМ, и это не мелочь: до него у переводчика не было ни
     одного экрана про себя, включая язык, на котором с ним разговаривают. */
  { key: "profile", label: TR("Профиль"), icon: "user", group: "files" },
  { key: "org", label: TR("Организация"), icon: "settings", owner: true, group: "files" },
  /* Админка открывается только с нестандартного адреса (window.ADMIN_ENTRY
     ставит сервер на /console-…), а не с главной — и только super. */
  { key: "admin", label: TR("Админ"), icon: "settings", super: true, entry: true, group: "sys" },
];
const TAB_GROUPS = [["work", TR("Работа")], ["files", TR("Файлы")], ["sys", TR("Служебное")]];
/* Счётчик у пункта меню. Вынесен из TabBar: его читают и меню, и крошки. */
function tabBadge(store, k, counts) {
  if (k === "profile") return (store.invites && store.invites.length) || null;
  if (!counts) return null;
  if (k === "editor") return counts.all;
  if (k === "preflight") return counts.failed + counts.qa || null;
  if (k === "glossary") return store.glossary.length;
  return null;
}
function visibleTabs(store) {
  return TABS.filter(t => (!t.owner || (store.can && store.can.owner))
    && (!t.super || (store.can && store.can.super))
    && (!t.entry || window.ADMIN_ENTRY));
}

/* Боковое меню. Заменило верхнюю ленту вкладок: пунктов девять, они не
   помещались в строку на ноутбуке и уезжали в горизонтальную прокрутку —
   то есть половину экранов не было видно. Ниже 900 px колонка сама
   ложится лентой (см. styles.css), поэтому разметка одна на оба случая. */
function Sidebar({ store, theme, onToggleTheme, onLogout }) {
  const counts = store.activeProject ? store.statusCounts(store.activeProject) : null;
  const tabs = visibleTabs(store);
  const caps = store.caps || null, usage = store.usage || null;
  /* Полоса страниц — только когда потолок ВЫДАН. Без него «0 из 0» читалось
     бы как «всё кончилось», а это «без потолка». */
  const limited = caps && caps.pagesLimited && caps.maxPages > 0;
  const used = usage ? (usage.pages || 0) : 0;
  const left = limited ? Math.max(0, caps.maxPages - used) : null;
  return React.createElement("aside", { className: "side" },
    React.createElement("div", { className: "side-brand" },
      React.createElement("span", { className: "side-mark" }, React.createElement(Icon, { name: "globe", size: 15 })),
      store.brand || "CAT Translator"),
    React.createElement(TeamChip, { store }),
    TAB_GROUPS.map(([g, title]) => {
      const items = tabs.filter(t => (t.group || "work") === g);
      if (!items.length) return null;
      return React.createElement("nav", { className: "grp", key: g, role: "tablist", "aria-label": title },
        React.createElement("h3", null, title),
        items.map(t => {
          const b = tabBadge(store, t.key, counts);
          return React.createElement("button", { key: t.key, className: "navi" + (store.tab === t.key ? " on" : ""),
            role: "tab", "aria-selected": store.tab === t.key, onClick: () => store.go(t.key) },
            React.createElement(Icon, { name: t.icon, size: 15 }),
            React.createElement("span", { className: "navi-t" }, t.label),
            b != null && React.createElement("span", { className: "navi-n" }, b));
        }));
    }),
    limited && React.createElement("div", { className: "side-foot" },
      React.createElement("div", { className: "sf-row" },
        React.createElement("span", null, TR("Страницы")),
        React.createElement("b", null, left + TR(" осталось"))),
      React.createElement("div", { className: "sf-meter" },
        React.createElement("i", { style: { width: Math.min(100, used / caps.maxPages * 100) + "%" } }))));
}

/* Организация в шапке меню. Команд больше одной — переключатель, одна —
   просто подпись: пустой список выбора выглядит сломанным. */
function TeamChip({ store }) {
  const teams = store.teams || [];
  const name = (store.tenant && store.tenant.name) || "";
  if (teams.length < 2) {
    return name ? React.createElement("div", { className: "org-chip" },
      React.createElement("span", { className: "org-dot" }), name) : null;
  }
  return React.createElement("div", { className: "org-chip org-chip-sel" },
    React.createElement("span", { className: "org-dot" }),
    React.createElement(TeamSwitcher, { store }));
}

/* Тонкая шапка: где я (крошки) и действия про себя. Всё, что про документ,
   живёт на самих экранах. */
function Topbar({ store, theme, onToggleTheme, onLogout, onSearch }) {
  const tab = TABS.filter(t => t.key === store.tab)[0];
  const proj = store.activeProject;
  return React.createElement("header", { className: "topbar" },
    React.createElement("div", { className: "crumb" },
      React.createElement("span", null, tab ? tab.label : TR("Редактор")),
      proj && React.createElement("span", { className: "crumb-sep" }, "/"),
      proj && React.createElement("b", null, proj.title)),
    React.createElement("div", { className: "tb-right" },
      React.createElement(IconBtn, { icon: "search", label: TR("Поиск"), sm: true, onClick: onSearch }),
      React.createElement(ThemeToggle, { theme, onToggle: onToggleTheme }),
      React.createElement("button", {
        className: "iconbtn sm", title: (store.me.name || "") + (store.can && store.can.role ? " · " + roleLabel(store.can.role) : ""),
        "aria-label": TR("Профиль"), onClick: () => store.go("profile"),
        style: { position: "relative", padding: 0, background: "none", border: "none", cursor: "pointer" } },
        React.createElement(Avatar, { person: store.me, size: 26, plain: true }),
        store.invites && store.invites.length > 0 && React.createElement("span", {
          style: { position: "absolute", top: -2, right: -2, minWidth: 16, height: 16, borderRadius: 8,
                   background: "var(--c-danger)", color: "var(--text-on-accent)", fontSize: 10, fontWeight: 600,
                   lineHeight: "16px", textAlign: "center", padding: "0 3px" } }, store.invites.length)),
      React.createElement(IconBtn, { icon: "logout", label: TR("Выйти"), sm: true, onClick: onLogout })));
}

/* ---------- Search palette ---------- */
function SearchPalette({ store, onClose }) {
  const [q, setQ] = useState("");
  const results = [];
  if (store.activeProject) store.activeProject.segments.forEach(s => {
    if (q && (s.source.toLowerCase().includes(q.toLowerCase()) || (s.target || "").toLowerCase().includes(q.toLowerCase())))
      /* Переход к зоне сегмента (jumpRef в редакторе), а не просто на вкладку:
         иначе найденное приходилось искать глазами второй раз. */
      results.push({ type: TR("Сегмент #") + s.id, text: s.source, action: () => { store.goToSegment(s.id); onClose(); } });
  });
  store.glossary.forEach(g => { if (q && g.src.toLowerCase().includes(q.toLowerCase())) results.push({ type: TR("Глоссарий"), text: g.src + " → " + g.tgt, action: () => { store.go("glossary"); onClose(); } }); });
  return React.createElement(Modal, { title: TR("Поиск по проекту"), icon: "search", onClose },
    React.createElement(Input, { value: q, onChange: (e) => setQ(e.target.value), placeholder: TR("Сегменты, термины…"), autoFocus: true }),
    React.createElement("div", { className: "col", style: { gap: 6, maxHeight: 320, overflow: "auto" } },
      q && results.length === 0 && React.createElement("p", { className: "dim", style: { fontSize: 13, padding: 8 } }, TR("Ничего не найдено.")),
      results.slice(0, 20).map((r, i) => React.createElement("button", { key: i, className: "card", style: { padding: "10px 12px", textAlign: "left", cursor: "pointer" }, onClick: r.action },
        React.createElement("div", { className: "dim", style: { fontSize: 11, fontWeight: 600 } }, r.type),
        React.createElement("div", { style: { fontSize: 13, marginTop: 2 } }, r.text)))));
}

/* ---------- Root App ---------- */
/* Экран падения. React в production-сборке не печатает стек компонента,
   а белый экран — известный способ падения этого фронтенда (совпавшее имя
   верхнего уровня, забытый хук). Без этой рамки диагностика на боевом
   сервере сводится к «Minified React error #130». */
class Boundary extends React.Component {
  constructor(props) { super(props); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err: err }; }
  componentDidCatch(err, info) {
    try { console.error("[ui]", err, info && info.componentStack); } catch (e) {}
  }
  render() {
    if (!this.state.err) return this.props.children;
    return React.createElement("div", { className: "page" },
      React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12, alignItems: "flex-start" } },
        React.createElement("h2", { className: "section-title", style: { margin: 0 } }, TR("Этот экран не открылся")),
        React.createElement("p", { className: "dim" }, TR("Работа не потеряна: всё сделанное сохранено на сервере. Откройте другую вкладку или обновите страницу.")),
        React.createElement("code", { className: "tt-code", style: { whiteSpace: "pre-wrap" } }, String(this.state.err && this.state.err.message || this.state.err)),
        React.createElement("button", { className: "btn btn-primary", onClick: () => window.location.reload() }, TR("Обновить страницу"))));
  }
}

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

  if (!authed) return React.createElement(AuthScreen, { onLogin: () => { setAuthed(true); toast.success(TR("Добро пожаловать"), TR("Вы вошли в систему.")); }, theme, onToggleTheme: toggleTheme });

  // Старые ключи оставлены живыми: на них ведут ссылки изнутри страниц
  // (например «показать сегменты с термином») и сохранённое состояние вкладки.
  const tabMap = {
    import: TabImport, editor: TabEditor, glossary: TabKnowledge, tm: TabKnowledge,
    export: TabExport, preflight: TabAnalysis, qa: TabAnalysis,
    backlog: TabAnalysis, stats: TabAnalysis, org: TabOrg, admin: TabAdmin,
    profile: TabProfile,
  };
  const Active = tabMap[store.tab] || TabEditor;

  /* Перезагрузка после выхода: иначе документы клиента остаются в памяти вкладки. */
  const logout = () => {
    const done = () => window.location.reload();
    if (window.API) window.API.logout().then(done, done); else done();
  };
  return React.createElement("div", { className: "shell" },
    React.createElement(Sidebar, { store, theme, onToggleTheme: toggleTheme, onLogout: logout }),
    React.createElement("div", { className: "shell-main" },
      React.createElement(Topbar, { store, theme, onToggleTheme: toggleTheme, onLogout: logout,
        onSearch: () => setSearch(true) }),
      React.createElement("main", { className: "main" },
        React.createElement(Boundary, { key: store.tab },
          React.createElement(Active, { store, toast, theme, onToggleTheme: toggleTheme })))),
    search && React.createElement(SearchPalette, { store, onClose: () => setSearch(false) })
  );
}

function Root() { return React.createElement(ToastProvider, null, React.createElement(App, null)); }
ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(Root, null));
