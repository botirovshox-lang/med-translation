/* ============================================================
   Tab: Организация — пользователи, импорт глоссария.
   Виден только владельцу (store.can.owner). Право ПОКАЗАТЬ — здесь,
   право СДЕЛАТЬ — на сервере: те же команды из консоли получают 403.
   ============================================================ */
function OrgUsers({ toast }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ login: "", password: "", name: "", role: "translator" });
  const [busy, setBusy] = useState(false);
  const reload = () => window.API.safeCall(() => window.API.users()).then(r => setUsers((r && r.users) || []));
  useEffect(() => { reload(); }, []);
  const create = async () => {
    setBusy(true);
    try {
      await window.API.userCreate(form);
      toast.success("Пользователь заведён", form.login);
      setForm({ login: "", password: "", name: "", role: "translator" });
      reload();
    } catch (e) { toast.error("Не заведён", e.message || String(e)); }
    setBusy(false);
  };
  const patch = async (u, body, okMsg) => {
    try { await window.API.userUpdate(u.id, body); toast.success(okMsg, u.login); reload(); }
    catch (e) { toast.error("Не удалось", e.message || String(e)); }
  };
  const resetPw = (u) => {
    const pw = prompt("Новый пароль для " + u.login + " (не короче 8 символов):");
    if (pw) patch(u, { password: pw }, "Пароль сменён");
  };
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 14 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, "Пользователи"),
    React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        ["Логин", "Имя", "Роль", "Состояние", ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, users.map(u => React.createElement("tr", { key: u.id },
        React.createElement("td", null, u.login),
        React.createElement("td", null, u.name),
        React.createElement("td", null, u.role === "owner" ? "владелец" : "переводчик"),
        React.createElement("td", null, u.active ? "активен" : "отключён"),
        React.createElement("td", { style: { whiteSpace: "nowrap" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => resetPw(u) }, "Пароль"),
          React.createElement(Btn, { variant: "ghost", size: "sm",
            onClick: () => patch(u, { role: u.role === "owner" ? "translator" : "owner" }, "Роль изменена") },
            u.role === "owner" ? "→ переводчик" : "→ владелец"),
          React.createElement(Btn, { variant: "ghost", size: "sm",
            onClick: () => patch(u, { active: !u.active }, u.active ? "Отключён" : "Включён") },
            u.active ? "Отключить" : "Включить")))))),
    React.createElement("div", { className: "eyebrow", style: { margin: "6px 0 0" } }, "Новый пользователь"),
    React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
      React.createElement(Field, { label: "Логин" },
        React.createElement(Input, { value: form.login, onChange: (e) => setForm({ ...form, login: e.target.value }), placeholder: "латиница, цифры, . _ @ -" })),
      React.createElement(Field, { label: "Пароль (от 8 символов)" },
        React.createElement(Input, { type: "password", value: form.password, onChange: (e) => setForm({ ...form, password: e.target.value }) })),
      React.createElement(Field, { label: "Имя" },
        React.createElement(Input, { value: form.name, onChange: (e) => setForm({ ...form, name: e.target.value }) })),
      React.createElement(Field, { label: "Роль" },
        React.createElement(Select, { value: form.role, onChange: (e) => setForm({ ...form, role: e.target.value }) },
          React.createElement("option", { value: "translator" }, "Переводчик"),
          React.createElement("option", { value: "owner" }, "Владелец")))),
    React.createElement("div", null,
      React.createElement(Btn, { variant: "primary", icon: "user", disabled: busy || !form.login || form.password.length < 8, onClick: create }, "Завести")));
}

function OrgGlossaryImport({ store, toast }) {
  const [file, setFile] = useState(null);
  const [langs, setLangs] = useState([["RU", "Русский"], ["EN", "Английский"]]);
  const [domains, setDomains] = useState([["medical", "Медицина"]]);
  const [src, setSrc] = useState("RU");
  const [tgt, setTgt] = useState("EN");
  const [domain, setDomain] = useState("medical");
  const [tier, setTier] = useState("auto");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    window.API.safeCall(() => window.API.models()).then(r => {
      if (!r) return;
      if (r.languages && r.languages.length) setLangs(r.languages.map(l => [l.code, l.ru + " · " + l.native]));
      if (r.domains && r.domains.length) { setDomains(r.domains.map(d => [d.id, d.label])); setDomain(r.domainDefault || r.domains[0].id); }
    });
  }, []);
  const run = async (dry) => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await window.API.importGlossary(file, src + "→" + tgt, domain, tier, dry);
      setPreview(r);
      if (!dry) {
        toast.success("Импортировано", r.added + " записей");
        // Список глоссария в браузере — 150 верхних записей; подтянуть заново.
        window.API.safeCall(() => window.API.seed()).then(d => { if (d && d.glossary && store.setGlossary) store.setGlossary(d.glossary); });
      }
    } catch (e) { toast.error("Импорт", e.message || String(e)); }
    setBusy(false);
  };
  const opt = (arr) => arr.map(([v, l]) => React.createElement("option", { key: v, value: v }, l));
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, "Импорт глоссария (TSV / CSV)"),
    React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } },
      "Колонки по заголовку (src, tgt, cat, note) или первые две. Повторы в пределах области пропускаются. Уровень «подсказка» модель вправе игнорировать; «приказ» уходит в промпт как «use these exact translations» — только для выверенного словаря."),
    React.createElement("input", { type: "file", accept: ".tsv,.csv,.txt", onChange: (e) => { setFile(e.target.files[0] || null); setPreview(null); } }),
    React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
      React.createElement(Field, { label: "Язык оригинала" }, React.createElement(Select, { value: src, onChange: (e) => setSrc(e.target.value) }, opt(langs))),
      React.createElement(Field, { label: "Язык перевода" }, React.createElement(Select, { value: tgt, onChange: (e) => setTgt(e.target.value) }, opt(langs))),
      React.createElement(Field, { label: "Предметная область" }, React.createElement(Select, { value: domain, onChange: (e) => setDomain(e.target.value) }, opt(domains))),
      React.createElement(Field, { label: "Уровень" }, React.createElement(Select, { value: tier, onChange: (e) => setTier(e.target.value) },
        React.createElement("option", { value: "auto" }, "Подсказка (модель вправе игнорировать)"),
        React.createElement("option", { value: "verified" }, "Приказ (выверенный словарь)")))),
    React.createElement("div", { className: "row", style: { gap: 8 } },
      React.createElement(Btn, { variant: "secondary", disabled: !file || busy || src === tgt, onClick: () => run(true) }, "Проверить"),
      React.createElement(Btn, { variant: "primary", disabled: !file || busy || !preview || !preview.dryRun || !preview.added, onClick: () => run(false) },
        preview && preview.dryRun ? "Импортировать " + preview.added : "Импортировать")),
    preview && React.createElement("div", { style: { fontSize: 13 } },
      React.createElement("div", null, "Строк: " + preview.rows + " · добавится: " + preview.added + " · повторов: " + preview.skippedDup + " · пустых/битых: " + preview.skippedBad + (preview.header ? " · заголовок распознан" : " · без заголовка: первые две колонки")),
      preview.sample && preview.sample.length > 0 && React.createElement("ul", { style: { margin: "6px 0 0", paddingLeft: 18 } },
        preview.sample.map((x, i) => React.createElement("li", { key: i }, x.src + " → " + x.tgt)))));
}

function TabOrg({ store, toast }) {
  const [info, setInfo] = useState(null);
  useEffect(() => { window.API.safeCall(() => window.API.me()).then(r => r && setInfo(r)); }, []);
  if (!(store.can && store.can.owner))
    return React.createElement("div", { className: "page" },
      React.createElement("p", { className: "dim" }, "Этот экран доступен владельцу организации."));
  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Организация" + (info && info.tenant && info.tenant.name ? " · " + info.tenant.name : "")),
      React.createElement("p", { className: "lead" }, "Пользователи и словарь организации. Проекты, глоссарий и память переводов других организаций отсюда не видны.")),
    React.createElement("div", { className: "col", style: { gap: 16 } },
      React.createElement(OrgUsers, { toast }),
      React.createElement(OrgGlossaryImport, { store, toast })));
}
