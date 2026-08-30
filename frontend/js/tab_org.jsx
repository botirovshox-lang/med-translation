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

/* Журнал действий: кто, когда, что. Пишет сервер (`_audit`), здесь показ. */
const AUDIT_LABELS = { login: "вход", "segment.confirm": "подтвердил сегмент", "segment.edit": "правил перевод",
  "glossary.save": "правил глоссарий", "glossary.demote": "понизил запись", "glossary.purge": "вынос глоссария",
  "glossary.import": "импорт глоссария", "tm.delete": "удалил из памяти", "term.approve": "одобрил термин",
  "term.reject": "отклонил термин", "project.delete": "удалил проект", "project.export": "экспорт",
  "job.create": "запустил прогон", "user.create": "завёл пользователя", "user.update": "правил пользователя",
  "tenant.create": "завёл организацию" };
function OrgAudit() {
  const [items, setItems] = useState([]);
  useEffect(() => { window.API.safeCall(() => window.API.audit(200)).then(r => setItems((r && r.items) || [])); }, []);
  const detail = (r) => Object.keys(r).filter(k => !["at", "tenant", "user", "login", "action"].includes(k))
    .map(k => k + "=" + r[k]).join(" · ");
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 10px" } }, "Журнал действий · последние " + items.length),
    items.length === 0 && React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, "Пока пусто."),
    items.length > 0 && React.createElement("div", { style: { maxHeight: 360, overflow: "auto" } },
      React.createElement("table", { className: "tbl" },
        React.createElement("tbody", null, items.map((r, i) => React.createElement("tr", { key: i },
          React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap", fontSize: 12 } }, r.at),
          React.createElement("td", { style: { whiteSpace: "nowrap" } }, r.login || "—"),
          React.createElement("td", null, AUDIT_LABELS[r.action] || r.action),
          React.createElement("td", { className: "dim", style: { fontSize: 12 } }, detail(r))))))));
}

/* Свои предметные области: копия встроенного шаблона с правками. Поля —
   ровно те, что читают промпты перевода, проверки и извлечения терминов. */
function OrgDomains({ toast }) {
  const [data, setData] = useState({ builtin: [], domains: [] });
  const [edit, setEdit] = useState(null);      // { id?, base, label, expert, terminology, extract, examples, cats, strict }
  const reload = () => window.API.safeCall(() => window.API.domains()).then(r => r && setData(r));
  useEffect(() => { reload(); }, []);
  const fromBase = (b) => ({ base: b.id, label: b.label + " (своя)", expert: b.expert, terminology: b.terminology,
    extract: b.extract, examples: b.examples || "", cats: (b.cats || []).join(", "), strict: true });
  const save = async () => {
    const body = { ...edit, cats: String(edit.cats || "").split(",").map(x => x.trim()).filter(Boolean) };
    try {
      if (edit.id && data.domains.some(d => d.id === edit.id)) await window.API.domainUpdate(edit.id, body);
      else await window.API.domainCreate(body);
      toast.success("Область сохранена", edit.label); setEdit(null); reload();
    } catch (e) { toast.error("Не сохранена", e.message || String(e)); }
  };
  const del = async (d) => {
    if (!confirm("Удалить область «" + d.label + "»?")) return;
    try { await window.API.domainDelete(d.id); toast.success("Удалена", d.label); reload(); }
    catch (e) { toast.error("Не удалена", e.message || String(e)); }
  };
  const F = (k, label, rows) => React.createElement(Field, { label },
    rows ? React.createElement(Textarea, { value: edit[k] || "", style: { minHeight: 60 }, onChange: (e) => setEdit({ ...edit, [k]: e.target.value }) })
         : React.createElement(Input, { value: edit[k] || "", onChange: (e) => setEdit({ ...edit, [k]: e.target.value }) }));
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, "Предметные области"),
    React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } },
      "Встроенные области — шаблон. Своя область задаёт, кем модель себя считает при переводе, что считать эталоном терминологии, что извлекать в глоссарий и какие категории терминов есть. «Приказ только от человека» — защита от самоодобрения глоссария в незнакомой области."),
    data.domains.length > 0 && React.createElement("table", { className: "tbl" },
      React.createElement("tbody", null, data.domains.map(d => React.createElement("tr", { key: d.id },
        React.createElement("td", null, React.createElement("b", null, d.label), " ", React.createElement("span", { className: "dim" }, d.id + " · шаблон: " + d.base + (d.strict ? " · приказ только от человека" : ""))),
        React.createElement("td", { style: { whiteSpace: "nowrap", textAlign: "right" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setEdit({ ...d, cats: (d.cats || []).join(", ") }) }, "Править"),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => del(d) }, "Удалить")))))),
    !edit && React.createElement("div", { className: "row row-wrap", style: { gap: 6 } },
      React.createElement("span", { className: "dim", style: { fontSize: 13 } }, "Создать на основе:"),
      data.builtin.map(b => React.createElement(Btn, { key: b.id, variant: "secondary", size: "sm", onClick: () => setEdit(fromBase(b)) }, b.label))),
    edit && React.createElement("div", { className: "col", style: { gap: 8 } },
      React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
        F("label", "Название"), F("id", "Идентификатор (a-z, 0-9, дефис; пусто — из названия)"),
        F("expert", "Кем модель себя считает (по-английски)"), F("terminology", "Эталон терминологии (по-английски)")),
      F("extract", "Что извлекать в глоссарий (по-английски)", true),
      F("examples", "Типичные кальки области: BAD / GOOD (по-английски, можно пусто)", true),
      F("cats", "Категории терминов через запятую"),
      React.createElement("label", { className: "row", style: { gap: 8, fontSize: 13 } },
        React.createElement("input", { type: "checkbox", checked: !!edit.strict, onChange: (e) => setEdit({ ...edit, strict: e.target.checked }) }),
        "Приказ в глоссарий — только от человека (согласия сегментов не хватает)"),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Btn, { variant: "primary", disabled: !edit.label, onClick: save }, "Сохранить"),
        React.createElement(Btn, { variant: "ghost", onClick: () => setEdit(null) }, "Отмена"))));
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
    info && info.spend && React.createElement("div", { className: "card card-pad", style: { marginBottom: 16, fontSize: 13 } },
      React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, "Расход за " + info.spend.month),
      React.createElement("div", { style: { fontWeight: 600, color: info.spend.over ? "var(--c-danger)" : undefined } },
        "$" + Number(info.spend.spentUsd || 0).toFixed(2)
        + (info.spend.limitUsd != null ? " из $" + Number(info.spend.limitUsd).toFixed(2) : " · лимит не задан")
        + " · вызовов: " + info.spend.calls
        + (info.spend.unpriced ? " · без цены: " + info.spend.unpriced : "")),
      info.spend.over && React.createElement("div", { className: "dim", style: { marginTop: 4 } },
        "Лимит исчерпан: платные прогоны отвечают отказом, бесплатные команды и экспорт работают. Лимит ставит администратор сервиса.")),
    React.createElement("div", { className: "col", style: { gap: 16 } },
      React.createElement(OrgUsers, { toast }),
      React.createElement(OrgDomains, { toast }),
      React.createElement(OrgGlossaryImport, { store, toast }),
      React.createElement(OrgAudit, null)));
}
