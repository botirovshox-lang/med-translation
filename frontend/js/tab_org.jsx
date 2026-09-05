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
      toast.success(TR("Пользователь заведён"), form.login);
      setForm({ login: "", password: "", name: "", role: "translator" });
      reload();
    } catch (e) { toast.error(TR("Не заведён"), e.message || String(e)); }
    setBusy(false);
  };
  const patch = async (u, body, okMsg) => {
    try { await window.API.userUpdate(u.id, body); toast.success(okMsg, u.login); reload(); }
    catch (e) { toast.error(TR("Не удалось"), e.message || String(e)); }
  };
  const resetPw = (u) => {
    const pw = prompt(TR("Новый пароль для ") + u.login + TR(" (не короче 8 символов):"));
    if (pw) patch(u, { password: pw }, TR("Пароль сменён"));
  };
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 14 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Пользователи")),
    React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Логин"), TR("Имя"), TR("Роль"), TR("Состояние"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, users.map(u => React.createElement("tr", { key: u.id },
        React.createElement("td", null, u.login),
        React.createElement("td", null, u.name),
        React.createElement("td", null, roleLabel(u.role)),
        React.createElement("td", null, u.active ? TR("активен") : TR("отключён")),
        React.createElement("td", { style: { whiteSpace: "nowrap" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => resetPw(u) }, TR("Пароль")),
          React.createElement(RoleSelect, { value: u.role, style: { width: 130, display: "inline-block", marginRight: 6 },
            onChange: (r) => r !== u.role && patch(u, { role: r }, TR("Роль изменена")) }),
          React.createElement(Btn, { variant: "ghost", size: "sm",
            onClick: () => patch(u, { active: !u.active }, u.active ? TR("Отключён") : TR("Включён")) },
            u.active ? TR("Отключить") : TR("Включить"))))))),
    React.createElement("div", { className: "eyebrow", style: { margin: "6px 0 0" } }, TR("Новый пользователь")),
    React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
      React.createElement(Field, { label: TR("Логин") },
        React.createElement(Input, { value: form.login, onChange: (e) => setForm({ ...form, login: e.target.value }), placeholder: TR("латиница, цифры, . _ @ -") })),
      React.createElement(Field, { label: TR("Пароль (от 8 символов)") },
        React.createElement(Input, { type: "password", value: form.password, onChange: (e) => setForm({ ...form, password: e.target.value }) })),
      React.createElement(Field, { label: TR("Имя") },
        React.createElement(Input, { value: form.name, onChange: (e) => setForm({ ...form, name: e.target.value }) })),
      React.createElement(Field, { label: TR("Роль") },
        React.createElement(RoleSelect, { value: form.role, onChange: (r) => setForm({ ...form, role: r }) }))),
    React.createElement("div", null,
      React.createElement(Btn, { variant: "primary", icon: "user", disabled: busy || !form.login || form.password.length < 8, onClick: create }, TR("Завести"))));
}

function OrgGlossaryImport({ store, toast }) {
  const [file, setFile] = useState(null);
  const [langs, setLangs] = useState([["RU", TR("Русский")], ["EN", TR("Английский")]]);
  const [domains, setDomains] = useState([["medical", TR("Медицина")]]);
  const [src, setSrc] = useState("RU");
  const [tgt, setTgt] = useState("EN");
  const [domain, setDomain] = useState("general");
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
        toast.success(TR("Импортировано"), r.added + TR(" записей"));
        // Список глоссария в браузере — 150 верхних записей; подтянуть заново.
        window.API.safeCall(() => window.API.seed()).then(d => { if (d && d.glossary && store.setGlossary) store.setGlossary(d.glossary); });
      }
    } catch (e) { toast.error(TR("Импорт"), e.message || String(e)); }
    setBusy(false);
  };
  const opt = (arr) => arr.map(([v, l]) => React.createElement("option", { key: v, value: v }, l));
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Импорт глоссария (TSV / CSV)")),
    React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } },
      TR("Колонки по заголовку (src, tgt, cat, note) или первые две. Повторы в пределах области пропускаются. Уровень «подсказка» модель вправе игнорировать; «приказ» уходит в промпт как «use these exact translations» — только для выверенного словаря.")),
    React.createElement("input", { type: "file", accept: ".tsv,.csv,.txt", onChange: (e) => { setFile(e.target.files[0] || null); setPreview(null); } }),
    React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
      React.createElement(Field, { label: TR("Язык оригинала") }, React.createElement(Select, { value: src, onChange: (e) => setSrc(e.target.value) }, opt(langs))),
      React.createElement(Field, { label: TR("Язык перевода") }, React.createElement(Select, { value: tgt, onChange: (e) => setTgt(e.target.value) }, opt(langs))),
      React.createElement(Field, { label: TR("Предметная область") }, React.createElement(Select, { value: domain, onChange: (e) => setDomain(e.target.value) }, opt(domains))),
      React.createElement(Field, { label: TR("Уровень") }, React.createElement(Select, { value: tier, onChange: (e) => setTier(e.target.value) },
        React.createElement("option", { value: "auto" }, TR("Подсказка (модель вправе игнорировать)")),
        React.createElement("option", { value: "verified" }, TR("Приказ (выверенный словарь)"))))),
    React.createElement("div", { className: "row", style: { gap: 8 } },
      React.createElement(Btn, { variant: "secondary", disabled: !file || busy || src === tgt, onClick: () => run(true) }, TR("Проверить")),
      React.createElement(Btn, { variant: "primary", disabled: !file || busy || !preview || !preview.dryRun || !preview.added, onClick: () => run(false) },
        preview && preview.dryRun ? TR("Импортировать ") + preview.added : TR("Импортировать"))),
    preview && React.createElement("div", { style: { fontSize: 13 } },
      React.createElement("div", null, TR("Строк: ") + preview.rows + TR(" · добавится: ") + preview.added + TR(" · повторов: ") + preview.skippedDup + TR(" · пустых/битых: ") + preview.skippedBad + (preview.header ? TR(" · заголовок распознан") : TR(" · без заголовка: первые две колонки"))),
      preview.sample && preview.sample.length > 0 && React.createElement("ul", { style: { margin: "6px 0 0", paddingLeft: 18 } },
        preview.sample.map((x, i) => React.createElement("li", { key: i }, x.src + " → " + x.tgt)))));
}

/* Журнал действий: кто, когда, что. Пишет сервер (`_audit`), здесь показ. */
const AUDIT_LABELS = { login: TR("вход"), "segment.confirm": TR("подтвердил сегмент"), "segment.edit": TR("правил перевод"),
  "glossary.save": TR("правил глоссарий"), "glossary.demote": TR("понизил запись"), "glossary.purge": TR("вынос глоссария"),
  "glossary.import": TR("импорт глоссария"), "tm.delete": TR("удалил из памяти"), "term.approve": TR("одобрил термин"),
  "term.reject": TR("отклонил термин"), "project.delete": TR("удалил проект"), "project.export": TR("экспорт"),
  "job.create": TR("запустил прогон"), "user.create": TR("завёл пользователя"), "user.update": TR("правил пользователя"),
  "tenant.create": TR("завёл организацию") };
function OrgAudit() {
  const [items, setItems] = useState([]);
  useEffect(() => { window.API.safeCall(() => window.API.audit(200)).then(r => setItems((r && r.items) || [])); }, []);
  const detail = (r) => Object.keys(r).filter(k => !["at", "tenant", "user", "login", "action"].includes(k))
    .map(k => k + "=" + r[k]).join(" · ");
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 10px" } }, TR("Журнал действий · последние ") + items.length),
    items.length === 0 && React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, TR("Пока пусто.")),
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
  const fromBase = (b) => ({ base: b.id, label: b.label + TR(" (своя)"), expert: b.expert, terminology: b.terminology,
    extract: b.extract, examples: b.examples || "", cats: (b.cats || []).join(", "), strict: true });
  const save = async () => {
    const body = { ...edit, cats: String(edit.cats || "").split(",").map(x => x.trim()).filter(Boolean) };
    try {
      if (edit.id && data.domains.some(d => d.id === edit.id)) await window.API.domainUpdate(edit.id, body);
      else await window.API.domainCreate(body);
      toast.success(TR("Область сохранена"), edit.label); setEdit(null); reload();
    } catch (e) { toast.error(TR("Не сохранена"), e.message || String(e)); }
  };
  const del = async (d) => {
    if (!confirm(TR("Удалить область «") + d.label + "»?")) return;
    try { await window.API.domainDelete(d.id); toast.success(TR("Удалена"), d.label); reload(); }
    catch (e) { toast.error(TR("Не удалена"), e.message || String(e)); }
  };
  const F = (k, label, rows) => React.createElement(Field, { label },
    rows ? React.createElement(Textarea, { value: edit[k] || "", style: { minHeight: 60 }, onChange: (e) => setEdit({ ...edit, [k]: e.target.value }) })
         : React.createElement(Input, { value: edit[k] || "", onChange: (e) => setEdit({ ...edit, [k]: e.target.value }) }));
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Предметные области")),
    React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } },
      TR("Встроенные области — шаблон. Своя область задаёт, кем модель себя считает при переводе, что считать эталоном терминологии, что извлекать в глоссарий и какие категории терминов есть. «Приказ только от человека» — защита от самоодобрения глоссария в незнакомой области.")),
    data.domains.length > 0 && React.createElement("table", { className: "tbl" },
      React.createElement("tbody", null, data.domains.map(d => React.createElement("tr", { key: d.id },
        React.createElement("td", null, React.createElement("b", null, d.label), " ", React.createElement("span", { className: "dim" }, d.id + TR(" · шаблон: ") + d.base + (d.strict ? TR(" · приказ только от человека") : ""))),
        React.createElement("td", { style: { whiteSpace: "nowrap", textAlign: "right" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setEdit({ ...d, cats: (d.cats || []).join(", ") }) }, TR("Править")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => del(d) }, TR("Удалить"))))))),
    !edit && React.createElement("div", { className: "row row-wrap", style: { gap: 6 } },
      React.createElement("span", { className: "dim", style: { fontSize: 13 } }, TR("Создать на основе:")),
      data.builtin.map(b => React.createElement(Btn, { key: b.id, variant: "secondary", size: "sm", onClick: () => setEdit(fromBase(b)) }, b.label))),
    edit && React.createElement("div", { className: "col", style: { gap: 8 } },
      React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
        F("label", TR("Название")), F("id", TR("Идентификатор (a-z, 0-9, дефис; пусто — из названия)")),
        F("expert", TR("Кем модель себя считает (по-английски)")), F("terminology", TR("Эталон терминологии (по-английски)"))),
      F("extract", TR("Что извлекать в глоссарий (по-английски)"), true),
      F("examples", TR("Типичные кальки области: BAD / GOOD (по-английски, можно пусто)"), true),
      F("cats", TR("Категории терминов через запятую")),
      React.createElement("label", { className: "row", style: { gap: 8, fontSize: 13 } },
        React.createElement("input", { type: "checkbox", checked: !!edit.strict, onChange: (e) => setEdit({ ...edit, strict: e.target.checked }) }),
        TR("Приказ в глоссарий — только от человека (согласия сегментов не хватает)")),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Btn, { variant: "primary", disabled: !edit.label, onClick: save }, TR("Сохранить")),
        React.createElement(Btn, { variant: "ghost", onClick: () => setEdit(null) }, TR("Отмена")))));
}

/* Вид записи журнала страниц — код с сервера, подпись даёт браузер. */
function orgPagesKind(k) {
  return k === "credit" ? TR("пополнение") : k === "repeat" ? TR("повтор файла, без списания")
    : k === "init" ? TR("стартовый объём по проектам") : TR("списание");
}
function orgPagesNote(n) { return n === "env" ? TR("стартовый лимит из окружения") : n; }

/* Суперпользователь: организации, их расход и лимиты. Лимит — решение
   администратора сервиса, владелец сам себе его не ставит. */
function SuperTenants({ toast }) {
  const [tenants, setTenants] = useState([]);
  const [form, setForm] = useState({ id: "", name: "", ownerLogin: "", ownerPassword: "" });
  const reload = () => window.API.safeCall(() => window.API.tenants()).then(r => setTenants((r && r.tenants) || []));
  useEffect(() => { reload(); }, []);
  const setLimit = async (t) => {
    const v = prompt(TR("Месячный лимит для «") + t.name + TR("», $ (пусто — снять лимит):"), t.limitUsd != null ? t.limitUsd : "");
    if (v === null) return;
    try {
      await window.API.tenantUpdate(t.id, v.trim() === "" ? { clearLimit: true } : { limitUsd: Number(v) });
      toast.success(TR("Лимит обновлён"), t.name); reload();
    } catch (e) { toast.error(TR("Не обновлён"), e.message || String(e)); }
  };
  const create = async () => {
    try { await window.API.tenantCreate(form); toast.success(TR("Организация заведена"), form.name); setForm({ id: "", name: "", ownerLogin: "", ownerPassword: "" }); reload(); }
    catch (e) { toast.error(TR("Не заведена"), e.message || String(e)); }
  };
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Организации (администратор сервиса)")),
    React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Организация"), TR("Расход за месяц"), TR("Лимит"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, tenants.map(t => React.createElement("tr", { key: t.id },
        React.createElement("td", null, React.createElement("b", null, t.name), " ", React.createElement("span", { className: "dim" }, t.id)),
        React.createElement("td", { style: { color: t.spend && t.spend.over ? "var(--c-danger)" : undefined } },
          "$" + Number((t.spend && t.spend.spentUsd) || 0).toFixed(2) + TR(" · вызовов ") + ((t.spend && t.spend.calls) || 0)),
        React.createElement("td", null, t.limitUsd != null ? "$" + Number(t.limitUsd).toFixed(2) : "—"),
        React.createElement("td", { style: { textAlign: "right" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setLimit(t) }, TR("Лимит"))))))),
    React.createElement("div", { className: "eyebrow", style: { margin: "6px 0 0" } }, TR("Новая организация")),
    React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
      React.createElement(Field, { label: TR("Идентификатор (a-z, 0-9, дефис)") }, React.createElement(Input, { value: form.id, onChange: (e) => setForm({ ...form, id: e.target.value }) })),
      React.createElement(Field, { label: TR("Название") }, React.createElement(Input, { value: form.name, onChange: (e) => setForm({ ...form, name: e.target.value }) })),
      React.createElement(Field, { label: TR("Логин владельца") }, React.createElement(Input, { value: form.ownerLogin, onChange: (e) => setForm({ ...form, ownerLogin: e.target.value }) })),
      React.createElement(Field, { label: TR("Пароль владельца (от 8)") }, React.createElement(Input, { type: "password", value: form.ownerPassword, onChange: (e) => setForm({ ...form, ownerPassword: e.target.value }) }))),
    React.createElement("div", null, React.createElement(Btn, { variant: "primary", disabled: !form.id || !form.ownerLogin || form.ownerPassword.length < 8, onClick: create }, TR("Завести организацию"))));
}

/* ── Цены: сколько организация продаёт страницу перевода ────────────
   Прайс и нормы страницы приходят с сервера (/api/pricing) и туда же
   уходят: своих чисел этот экран не знает — иначе в системе появился бы
   второй прайс-лист рядом с настоящим, и смета считалась бы по одному,
   а счёт выставлялся по другому. Право ПОКАЗАТЬ — здесь, право СДЕЛАТЬ
   (владелец) — на сервере: та же команда из консоли получит 403. */
function OrgPricing({ toast }) {
  const [card, setCard] = useState(null);
  const [norms, setNorms] = useState(null);
  const [langs, setLangs] = useState([]);
  const [busy, setBusy] = useState(false);
  const reload = () => window.API.safeCall(() => window.API.pricing()).then(r => {
    if (!r) return;
    setCard(r.pricing);
    setNorms(r.norms);
  });
  useEffect(() => {
    reload();
    window.API.safeCall(() => window.API.models()).then(r => {
      if (r && r.languages) setLangs(r.languages.map(l => [l.code, l.ru]));
    });
  }, []);
  if (!card) return null;

  const set = (k, v) => setCard({ ...card, [k]: v });
  const rates = card.rates || [];
  const setRate = (i, k, v) => set("rates", rates.map((r, j) => j === i ? { ...r, [k]: v } : r));
  const normRows = Object.keys(card.norms || {}).sort();
  const save = async (body) => {
    setBusy(true);
    try {
      const r = await window.API.pricingSave(body);
      setCard(r.pricing);
      toast.success(TR("Прайс сохранён"), TR("цена за страницу применится к новым сметам"));
    } catch (e) { toast.error(TR("Не сохранено"), e.message || String(e)); }
    setBusy(false);
  };
  // Цена «не задана» и цена «ноль» — разные вещи: пустое поле снимает
  // общую цену (clearDefault), и смета честно скажет «цена не задана»,
  // а не покажет клиенту бесплатный перевод.
  const submit = () => save({
    currency: card.currency,
    default: card.default === "" || card.default == null ? null : Number(card.default),
    clearDefault: card.default === "" || card.default == null,
    minPages: Number(card.minPages || 0),
    roundTo: Number(card.roundTo || 0),
    rates: rates.filter(r => r.src && r.tgt && String(r.price).trim() !== "" && Number(r.price) > 0)
      .map(r => ({ src: r.src, tgt: r.tgt, price: Number(r.price) })),
    norms: card.norms || {},
  });

  const langOpts = (langs.length ? langs : [["RU", TR("Русский")], ["EN", TR("Английский")]])
    .map(([c, n]) => React.createElement("option", { key: c, value: c }, c + " · " + n));

  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Цены за страницу")),
    React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13 } },
      TR("Страница — условная переводческая: столько знаков ИСХОДНИКА с пробелами, сколько задано нормой языка. ")
      + TR("Смета считается по этим числам во вкладке «Импорт»: там видно знаки, страницы и сумму по файлу.")),
    React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
      React.createElement(Field, { label: TR("Валюта (ISO: USD, EUR, UZS)") },
        React.createElement(Input, { value: card.currency || "", onChange: (e) => set("currency", e.target.value.toUpperCase()) })),
      React.createElement(Field, { label: TR("Цена страницы по умолчанию (пусто — не задана)") },
        React.createElement(Input, { type: "number", step: "0.01", min: "0", value: card.default == null ? "" : card.default,
          onChange: (e) => set("default", e.target.value) })),
      React.createElement(Field, { label: TR("Минимальный заказ, страниц") },
        React.createElement(Input, { type: "number", step: "0.1", min: "0", value: card.minPages,
          onChange: (e) => set("minPages", e.target.value) })),
      React.createElement(Field, { label: TR("Округление, страниц (0 — без округления)") },
        React.createElement(Input, { type: "number", step: "0.1", min: "0", max: "1", value: card.roundTo,
          onChange: (e) => set("roundTo", e.target.value) }))),

    React.createElement("div", { className: "eyebrow", style: { margin: "6px 0 0" } }, TR("Цены по парам языков")),
    React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Исходник"), TR("Перевод"), TR("Цена за страницу"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, rates.map((r, i) => React.createElement("tr", { key: i },
        React.createElement("td", null, React.createElement(Select, { value: r.src, onChange: (e) => setRate(i, "src", e.target.value) }, langOpts)),
        React.createElement("td", null, React.createElement(Select, { value: r.tgt, onChange: (e) => setRate(i, "tgt", e.target.value) }, langOpts)),
        React.createElement("td", null, React.createElement(Input, { type: "number", step: "0.01", min: "0", value: r.price,
          onChange: (e) => setRate(i, "price", e.target.value) })),
        React.createElement("td", { style: { textAlign: "right" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => set("rates", rates.filter((_x, j) => j !== i)) }, TR("Убрать"))))))),
    React.createElement("div", null,
      React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => set("rates", rates.concat([{ src: "RU", tgt: "EN", price: 0 }])) }, TR("Добавить пару"))),

    React.createElement("div", { className: "eyebrow", style: { margin: "6px 0 0" } }, TR("Норма страницы")),
    React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13 } },
      TR("По умолчанию берётся из таблицы сервиса (базис — 250 слов на страницу; ")
      + (norms ? TR("русский ") + (norms.rows.find(x => x.lang === "RU") || {}).chars + TR(" знаков, английский ")
        + (norms.rows.find(x => x.lang === "EN") || {}).chars + TR(" знаков") : "") + "). "
      + TR("Договор с клиентом может называть другое число — задайте его здесь, и смета пойдёт по нему.")),
    normRows.length > 0 && React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Язык исходника"), TR("Знаков в странице"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, normRows.map(code => React.createElement("tr", { key: code },
        React.createElement("td", null, code),
        React.createElement("td", null, React.createElement(Input, {
          type: "number", step: "50", min: "100", value: card.norms[code],
          onChange: (e) => set("norms", { ...card.norms, [code]: e.target.value }) })),
        React.createElement("td", { style: { textAlign: "right" } },
          React.createElement(Btn, {
            variant: "ghost", size: "sm",
            onClick: () => { const n = { ...card.norms }; delete n[code]; set("norms", n); }
          }, TR("Вернуть норму сервиса"))))))),
    React.createElement("div", null,
      React.createElement(Btn, {
        variant: "ghost", size: "sm",
        onClick: () => {
          const code = (prompt(TR("Код языка исходника (две буквы, например RU):")) || "").trim().toUpperCase();
          if (!code) return;
          const row = norms && norms.rows.find(x => x.lang === code);
          set("norms", { ...(card.norms || {}), [code]: row ? row.chars : (norms ? norms.default : 1800) });
        }
      }, TR("Задать свою норму"))),

    React.createElement("div", { style: { display: "flex", gap: 8, alignItems: "center", marginTop: 6 } },
      React.createElement(Btn, { variant: "primary", disabled: busy, onClick: submit }, busy ? TR("Сохраняем…") : TR("Сохранить прайс")),
      rates.some(r => String(r.price).trim() === "" || !(Number(r.price) > 0)) && React.createElement(
        "span", { className: "dim", style: { fontSize: 12 } },
        TR("Строки без цены не сохранятся: ноль — это не цена, а «не задана».")),
      card.updated && React.createElement("span", { className: "dim", style: { fontSize: 12 } },
        TR("изменён ") + card.updated + (card.by ? " · " + card.by : ""))));
}

function TabOrg({ store, toast }) {
  const [info, setInfo] = useState(null);
  useEffect(() => { window.API.safeCall(() => window.API.me()).then(r => r && setInfo(r)); }, []);
  if (!(store.can && store.can.owner))
    return React.createElement("div", { className: "page" },
      React.createElement("p", { className: "dim" }, TR("Этот экран доступен владельцу организации.")));
  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, TR("Организация") + (info && info.tenant && info.tenant.name ? " · " + info.tenant.name : "")),
      React.createElement("p", { className: "lead" }, TR("Пользователи и словарь организации. Проекты, глоссарий и память переводов других организаций отсюда не видны."))),
    info && info.adminPath && !window.ADMIN_ENTRY && React.createElement("p", { className: "dim", style: { fontSize: 13, marginTop: -8 } },
      TR("Админка сервиса — по служебному адресу "), React.createElement("a", { href: info.adminPath }, info.adminPath)),
    info && info.spend && React.createElement("div", { className: "card card-pad", style: { marginBottom: 16, fontSize: 13 } },
      React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("Расход за ") + info.spend.month),
      React.createElement("div", { style: { fontWeight: 600, color: info.spend.over ? "var(--c-danger)" : undefined } },
        "$" + Number(info.spend.spentUsd || 0).toFixed(2)
        + (info.spend.limitUsd != null ? TR(" из $") + Number(info.spend.limitUsd).toFixed(2) : TR(" · лимит не задан"))
        + TR(" · вызовов: ") + info.spend.calls
        + (info.spend.unpriced ? TR(" · без цены: ") + info.spend.unpriced : "")),
      info.spend.over && React.createElement("div", { className: "dim", style: { marginTop: 4 } },
        TR("Лимит исчерпан: платные прогоны отвечают отказом, бесплатные команды и экспорт работают. Лимит ставит администратор сервиса.")),
      // Объём в СТРАНИЦАХ — мера заказа, а не наших затрат: считается
      // по загруженным файлам (как смета), потолок выдаёт администратор.
      info.usage && React.createElement("div", { style: { marginTop: 6 } },
        TR("Страниц списано: ") + info.usage.used
        + (info.usage.imagePages ? TR(" · на картинках: ") + info.usage.imagePages : "")
        + (info.usage.left != null ? TR(" · всего ") + info.usage.pages + TR(" из ") + info.caps.maxPages + TR(" · осталось ") + info.usage.left : "")
        + TR(" · проектов: ") + info.usage.projects
        + (info.caps && info.caps.maxProjects ? TR(" из ") + info.caps.maxProjects : "")),
      info.pagesLog && info.pagesLog.length > 0 && React.createElement("div", { className: "dim", style: { marginTop: 4, fontSize: 12 } },
        info.pagesLog.slice().reverse().slice(0, 10).map((e, i) => React.createElement("div", { key: i },
          e.at + " · " + orgPagesKind(e.kind) + " " + (e.kind === "credit" && e.pages > 0 ? "+" : "") + e.pages
          + (e.title ? " · " + e.title : "") + (e.note ? " · " + orgPagesNote(e.note) : ""))))),
    React.createElement("div", { className: "col", style: { gap: 16 } },
      React.createElement(OrgUsers, { toast }),
      React.createElement(OrgPricing, { toast }),
      store.can && store.can.super && React.createElement(SuperTenants, { toast }),
      React.createElement(OrgDomains, { toast }),
      React.createElement(OrgGlossaryImport, { store, toast }),
      React.createElement(OrgAudit, null)));
}
