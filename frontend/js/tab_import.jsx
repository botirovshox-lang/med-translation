/* ============================================================
   Tab: Projects — folders with files; quote lives here too
   ============================================================ */
/* ── Смета: знаки, страницы, деньги ─────────────────────────────────
   Считает СЕРВЕР (/api/quote): и знаки, и норму страницы, и сумму. Браузер
   не повторяет ни одного из этих чисел — второй расчёт разошёлся бы с тем,
   по которому выставят счёт. Файл никуда не сохраняется, вызовов модели нет,
   поэтому команда бесплатна и работает на исчерпанном лимите.
   Формат считаем любой, какой умеем разобрать; проект пока создаётся только
   из .docx — поэтому смету можно взять и по файлу, который импортировать
   нельзя. */
function ImpQuote({ file, src, tgt, toast, onSaved }) {
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setRes(null); setErr(""); }, [file && file.name, src, tgt]);
  const runScan = async () => {
    // Скан: платное чтение выборки страниц зрячей моделью — по отдельной кнопке,
    // после того как человек увидел, сколько страниц и почём.
    setBusy(true); setErr("");
    try {
      const r = await window.API.quoteScan(file.raw, src, tgt);
      setRes(r);
      if (r && r.saved && onSaved) onSaved();
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(false);
  };
  const run = async () => {
    if (!file || !file.raw) { toast.error(TR("Файл не выбран"), TR("Выберите файл, чтобы посчитать объём")); return; }
    setBusy(true); setErr("");
    try {
      const r = await window.API.quoteFile(file.raw, src, tgt);
      setRes(r);
      if (r && r.saved && onSaved) onSaved();
    } catch (e) {
      setRes(null);
      // Причина отказа называется словами: «не посчитали» без причины —
      // это предложение гадать, что не так с файлом.
      setErr(e.message || String(e));
    }
    setBusy(false);
  };
  const row = (k, v) => React.createElement("div", { style: { display: "flex", justifyContent: "space-between", gap: 12 } },
    React.createElement("span", { className: "dim" }, k), React.createElement("b", null, v));
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Объём и стоимость")),
    React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13 } },
      TR("Страница — 250 слов исходника (у письма без пробелов — знаки по норме языка). Цену за страницу задаёт владелец организации.")),
    React.createElement("div", null,
      React.createElement(Btn, { variant: "ghost", disabled: !file || busy, onClick: run },
        busy ? TR("Считаем…") : TR("Посчитать объём и стоимость"))),
    err && React.createElement("div", { className: "dim", style: { color: "var(--c-danger)", fontSize: 13 } }, err),
    res && res.scan && !res.counts && React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6, fontSize: 14 } },
      React.createElement("div", null, TR("Это скан: ") + res.scan.pages + TR(" стр. без текстового слоя. Объём можно оценить по выборке страниц; точный счёт — после распознавания.")),
      React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" } },
        React.createElement(Btn, { variant: "ghost", disabled: busy, onClick: runScan },
          busy ? TR("Читаем…") : TR("Оценить по выборке из ") + res.scan.sample + TR(" стр.")),
        !costHidden() && res.scan.est != null && React.createElement("span", { className: "dim", style: { fontSize: 12 } },
          TR("зрячая модель ") + res.scan.model + " · ≈ $" + Number(res.scan.est).toFixed(3)))),
    res && res.counts && React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6, fontSize: 14 } },
      res.scan && row(TR("Оценка по выборке"), res.scan.read.length + TR(" из ") + res.scan.pages + TR(" стр.")),
      row(TR("Слов"), res.counts.words.toLocaleString("ru-RU")),
      row(TR("Знаков с пробелами"), res.counts.chars.toLocaleString("ru-RU")),
      row(TR("Без пробелов"), res.counts.charsNoSpaces.toLocaleString("ru-RU")),
      row(TR("Норма страницы (") + res.norm.lang + ")", res.norm.perPage + (res.norm.unit === "words" ? TR(" слов") : TR(" знаков"))
        + (res.norm.source === "tenant" ? TR(" · ваша") : res.norm.source === "default" ? TR(" · по умолчанию") : "")),
      row(TR("Страниц"), res.pages.exact + TR(" → к оплате ") + res.pages.billed),
      row(TR("Цена страницы"), res.rate.price == null ? TR("не задана")
        : res.rate.price + " " + res.currency + (res.rate.source === "pair" ? TR(" · по паре") : TR(" · общая"))),
      React.createElement("div", {
        style: { display: "flex", justifyContent: "space-between", borderTop: "1px solid var(--c-border)", paddingTop: 8 }
      },
        React.createElement("span", null, TR("Итого")),
        React.createElement("b", { style: { fontSize: 18 } },
          res.total == null ? TR("цена не задана") : res.total.toLocaleString("ru-RU") + " " + res.currency)),
      res.rate.price == null && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        TR("Задайте цену за страницу во вкладке «Организация» — до этого сумму показать нечем.")),
      res.counts.repeatBlocks > 0 && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        TR("Повторов: ") + res.counts.repeatBlocks + TR(" кусков на ") + res.counts.repeatChars.toLocaleString("ru-RU")
        + TR(" знаков. Из объёма они НЕ вычтены — скидку за повторы решает продавец.")),
      (res.notes || []).map((n, i) => React.createElement("div", { key: i, className: "dim", style: { fontSize: 12 } }, n)),
      React.createElement("div", { className: "dim", style: { fontSize: 12 } }, res.formula),
      res.saved && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        TR("Сохранено в историю смет ") + res.saved.at + TR(" — вернуться к оплате можно ниже."))));
}


/* ── История смет: к чему вернуться при оплате ──────────────────────
   Числа в записи ЗАМОРОЖЕНЫ на момент расчёта и здесь не пересчитываются:
   клиент считал по вчерашнему прайсу, платит по нему же. Пересчитанная
   задним числом смета — другая сумма под тем же счётом.
   Право пометить оплаченной — у владельца (сервер вернёт 403 остальным):
   это решение про деньги, а не про перевод. */
const IMP_QUOTE_STATUS = { new: TR("черновик"), invoiced: TR("выставлен счёт"), paid: TR("оплачена") };

function ImpQuoteHistory({ reloadKey, toast, canOwner }) {
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(false);
  const load = () => window.API.safeCall(() => window.API.quotes()).then(r => r && setRows(r.quotes || []));
  useEffect(() => { load(); }, [reloadKey]);
  if (!rows || !rows.length) return null;
  const mark = async (q, status) => {
    try { await window.API.quoteMark(q.id, { status }); toast.success(TR("Смета отмечена"), IMP_QUOTE_STATUS[status]); load(); }
    catch (e) { toast.error(TR("Не отмечена"), e.message || String(e)); }
  };
  const del = async (q) => {
    if (!confirm(TR("Удалить смету по «") + q.file + TR("» на ") + q.total + " " + q.currency + "?")) return;
    try { await window.API.quoteDelete(q.id); toast.success(TR("Смета удалена"), q.file); load(); }
    catch (e) { toast.error(TR("Не удалена"), e.message || String(e)); }
  };
  const shown = open ? rows : rows.slice(0, 5);
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("История смет · ") + rows.length),
    React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13 } },
      TR("Числа сохранены такими, какими их посчитали тогда: смена прайса старые сметы не трогает.")),
    React.createElement("div", { style: { overflowX: "auto" } }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Дата"), TR("Файл"), TR("Пара"), TR("Слов"), TR("Страниц"), TR("Цена"), TR("Итого"), TR("Состояние"), ""].map((h, i) =>
          React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, shown.map(q => React.createElement("tr", { key: q.id, title: q.formula || "" },
        React.createElement("td", { style: { whiteSpace: "nowrap" } }, q.at),
        React.createElement("td", null, q.file || "—", q.count > 1 ? React.createElement("span", { className: "dim" }, TR(" · считали ") + q.count + TR(" раз")) : null),
        React.createElement("td", null, q.src + "→" + q.tgt),
        React.createElement("td", null, q.words == null ? "—" : Number(q.words).toLocaleString("ru-RU")),
        React.createElement("td", null, (q.basis === "scan" ? "≈ " : "") + q.pagesBilled),
        React.createElement("td", null, q.pricePerPage == null ? "—" : q.pricePerPage + " " + q.currency),
        React.createElement("td", null, React.createElement("b", null,
          q.total == null ? TR("цена не задана") : Number(q.total).toLocaleString("ru-RU") + " " + q.currency)),
        React.createElement("td", null, IMP_QUOTE_STATUS[q.status] || q.status,
          q.paidAt ? React.createElement("span", { className: "dim" }, " · " + q.paidAt) : null),
        React.createElement("td", { style: { whiteSpace: "nowrap", textAlign: "right" } },
          canOwner && q.status !== "invoiced" && q.status !== "paid" && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => mark(q, "invoiced") }, TR("Счёт выставлен")),
          canOwner && q.status !== "paid" && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => mark(q, "paid") }, TR("Оплачена")),
          canOwner && q.status === "paid" && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => mark(q, "new") }, TR("Вернуть в черновик")),
          canOwner && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => del(q) }, TR("Удалить")))))))),
    rows.length > 5 && React.createElement("div", null,
      React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setOpen(!open) },
        open ? TR("Свернуть") : TR("Показать все ") + rows.length)));
}

/* ============================================================
   Экран «Проекты»
   Проект — папка с файлами одного заказа: одна пара языков, одна область,
   свои словари. Файл внутри открывается в «Переводе». Файл без папки сервер
   отдаёт как папку с тем же номером (`virtual`) — так живут файлы, заведённые
   до появления папок, и править их можно как настоящие.
   Имена компонентов — с префиксом Imp: все .jsx живут в одной области.
   ============================================================ */
function TabImport({ store, toast }) {
  const [meta, setMeta] = useState({ langs: [["RU", TR("Русский")], ["EN", TR("Английский")]],
                                     domains: [["general", TR("Общая")]], domainDefault: "general" });
  // Каталоги языков и областей живут на сервере — хардкодить нельзя.
  useEffect(() => {
    window.API && window.API.safeCall(() => window.API.models()).then(res => {
      if (!res) return;
      setMeta({
        langs: res.languages && res.languages.length ? res.languages.map(l => [l.code, l.ru + " · " + l.native]) : meta.langs,
        domains: res.domains && res.domains.length ? res.domains.map(d => [d.id, d.label]) : meta.domains,
        domainDefault: res.domainDefault || "general",
      });
    });
  }, []);
  const folder = store.viewFolder != null ? (store.folders || []).find(f => f.id === store.viewFolder) : null;
  /* key — номер папки: состояние блока словарей (отмеченные, «не сохранено»)
     иначе переехало бы из папки A в папку B при переходе без списка. */
  if (folder) return React.createElement(ImpFolderView, { key: folder.id, folder, store, toast, meta });
  return React.createElement(ImpFolderList, { store, toast, meta });
}

/* Языки в списке: сначала частые (в том порядке, в каком их ищут глазами),
   потом все остальные по алфавиту. Каталог — с сервера, здесь только порядок
   показа: семьдесят языков по алфавиту прячут русский и английский в середине. */
const IMP_POPULAR_LANGS = ["RU", "EN", "UZ", "ZH", "ES", "AR", "FR", "DE", "TR", "KK", "KO", "JA", "PT", "IT", "HI"];
function impLangOptions(langs) {
  const by = {};
  (langs || []).forEach(([v, l]) => { by[v] = l; });
  const top = IMP_POPULAR_LANGS.filter(v => by[v]).map(v => [v, by[v]]);
  const seen = new Set(top.map(x => x[0]));
  const rest = (langs || []).filter(([v]) => !seen.has(v));
  const opt = ([v, l]) => React.createElement("option", { key: v, value: v }, l);
  if (!rest.length || !top.length) return (langs || []).map(opt);
  return [
    React.createElement("optgroup", { key: "top", label: TR("Частые") }, top.map(opt)),
    React.createElement("optgroup", { key: "rest", label: TR("Все языки") }, rest.map(opt)),
  ];
}

function impDomainLabel(meta, id) {
  const hit = (meta.domains || []).find(d => d[0] === (id || LEGACY_DOMAIN));
  return hit ? hit[1] : (id || LEGACY_DOMAIN);
}
function impFolderStats(store, folder) {
  const files = (folder.files || []).map(id => (store.projects || []).find(p => p.id === id)).filter(Boolean);
  let total = 0, done = 0;
  files.forEach(p => { const c = store.statusCounts(p); total += c.all; done += c.confirmed; });
  return { files, total, done, pct: total ? Math.round(done / total * 100) : 0 };
}
/* Словари папки: список id либо null — «все словари организации» (папка
   заведена до словарей). Показывать это надо честно, а не как пустоту. */
function impFolderDicts(folder) {
  return Array.isArray(folder.dicts) ? folder.dicts : null;
}

/* ---------- Список проектов ---------- */
function ImpFolderList({ store, toast, meta }) {
  const [creating, setCreating] = useState(false);
  const folders = store.folders || [];
  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "row between row-wrap page-head", style: { alignItems: "flex-end", gap: 12 } },
      React.createElement("div", null,
        React.createElement("h1", null, TR("Проекты")),
        React.createElement("p", { className: "lead" }, TR("Проект — это папка с файлами одного заказа: одна пара языков, одна тема и свои словари. Откройте проект, чтобы добавить файл или начать перевод."))),
      React.createElement(Btn, { variant: "primary", icon: "plus", onClick: () => setCreating(true) }, TR("Новый проект"))),
    folders.length === 0
      ? React.createElement(EmptyState, { icon: "folder", title: TR("Проектов пока нет"),
          sub: TR("Создайте проект и положите в него первый файл."),
          action: React.createElement(Btn, { variant: "primary", icon: "plus", onClick: () => setCreating(true) }, TR("Новый проект")) })
      : React.createElement("div", { className: "grid grid-3" },
          folders.map(f => React.createElement(ImpFolderCard, { key: f.id, folder: f, store, meta }))),
    React.createElement("div", { className: "section", style: { marginTop: 24 } },
      React.createElement(ImpQuoteHistory, { reloadKey: 0, toast, canOwner: !!(store.can && store.can.owner) })),
    creating && React.createElement(ImpNewFolder, { store, toast, meta, onClose: () => setCreating(false) }));
}

function ImpFolderCard({ folder, store, meta }) {
  const st = impFolderStats(store, folder);
  const dl = impFolderDicts(folder);
  const dictNames = dl === null ? [TR("все словари")]
    : dl.map(id => ((store.dicts || []).find(d => d.id === id) || {}).title || id);
  return React.createElement("div", { className: "card card-pad card-hover", style: { display: "flex", flexDirection: "column", gap: 12, cursor: "pointer" },
      onClick: () => store.openFolder(folder.id) },
    React.createElement("div", { style: { fontWeight: 600, fontSize: 15, letterSpacing: "-.2px" } }, folder.title || TR("Без названия")),
    React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
      React.createElement(LangPair, { src: folder.src, tgt: folder.tgt }),
      React.createElement(Badge, { icon: "file" }, st.files.length + " " + impPlural(st.files.length, TR("файл"), TR("файла"), TR("файлов"))),
      React.createElement(Badge, null, impDomainLabel(meta, folder.domain))),
    React.createElement("div", null,
      React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
        React.createElement("span", { className: "muted" }, TR("Готово")),
        React.createElement("span", { style: { fontWeight: 600 } }, st.pct + "%")),
      React.createElement(ProgressBar, { value: st.pct })),
    React.createElement("div", { className: "dim", style: { fontSize: 12 } },
      React.createElement(Icon, { name: "book", size: 12 }), " ", dictNames.join(", ") || TR("без словарей")),
    React.createElement("div", null,
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "folder", onClick: (e) => { e.stopPropagation(); store.openFolder(folder.id); } }, TR("Открыть"))));
}

function impPlural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

/* ---------- Новый проект ---------- */
function ImpNewFolder({ store, toast, meta, onClose }) {
  const [title, setTitle] = useState("");
  const [src, setSrc] = useState("RU");
  const [tgt, setTgt] = useState("EN");
  const [domain, setDomain] = useState(meta.domainDefault || "general");
  const [ownDict, setOwnDict] = useState(true);       // завести свой словарь
  const [dictName, setDictName] = useState("");
  const [picked, setPicked] = useState([]);           // существующие словари, в порядке выбора
  const [busy, setBusy] = useState(false);
  const dicts = store.dicts || [];
  const toggle = (id) => setPicked(p => p.indexOf(id) >= 0 ? p.filter(x => x !== id) : p.concat([id]));
  const pair = src + "→" + tgt;
  const create = async () => {
    if (src === tgt) { toast.error(TR("Языки совпадают"), TR("Выберите разные языки оригинала и перевода.")); return; }
    setBusy(true);
    try {
      const r = await window.API.createFolder({ title: title || TR("Новый проект"), src, tgt, domain,
        dicts: picked, newDict: ownDict ? (dictName || title || TR("Словарь проекта")) : null });
      store.addFolder(r);
      // Словари организации изменились (появился новый) — перечитать список.
      window.API.safeCall(() => window.API.listDicts()).then(d => { if (d && d.dicts && store.setDicts) store.setDicts(d.dicts); });
      toast.success(TR("Проект создан"), r.title);
      onClose();
      store.openFolder(r.id);
    } catch (e) { toast.error(TR("Проект не создан"), e.message || String(e)); }
    setBusy(false);
  };
  const opt = (arr) => arr.map(([v, l]) => React.createElement("option", { key: v, value: v }, l));
  return React.createElement(Modal, { title: TR("Новый проект"), icon: "folder", onClose, width: 640,
    footer: React.createElement(React.Fragment, null,
      React.createElement(Btn, { variant: "ghost", onClick: onClose }, TR("Отмена")),
      React.createElement(Btn, { variant: "primary", icon: "check", disabled: busy || src === tgt, onClick: create }, TR("Создать"))) },
    React.createElement(Field, { label: TR("Название проекта") },
      React.createElement(Input, { value: title, autoFocus: true, placeholder: TR("напр. Договор поставки"), onChange: (e) => setTitle(e.target.value) })),
    React.createElement("div", { className: "grid grid-2" },
      React.createElement(Field, { label: TR("Язык оригинала") }, React.createElement(Select, { value: src, onChange: (e) => setSrc(e.target.value) }, impLangOptions(meta.langs))),
      React.createElement(Field, { label: TR("Язык перевода") }, React.createElement(Select, { value: tgt, onChange: (e) => setTgt(e.target.value) }, impLangOptions(meta.langs)))),
    src === tgt && React.createElement("div", { style: { color: "var(--c-danger)", fontSize: 13 } }, TR("Язык оригинала и язык перевода совпадают.")),
    React.createElement(Field, { label: TR("Тема"), hint: TR("Подсказывает переводчику-модели, о чём документ. У всех файлов проекта тема одна.") },
      React.createElement(Select, { value: domain, onChange: (e) => setDomain(e.target.value) }, opt(meta.domains))),
    React.createElement(Field, { label: TR("Словари проекта"),
      hint: TR("Слова, которые надо переводить всегда одинаково. Новые слова проекта попадут в первый словарь из списка.") },
      React.createElement("div", { className: "col", style: { gap: 8 } },
        React.createElement(Checkbox, { checked: ownDict, onChange: (e) => setOwnDict(e.target.checked) }, TR("Завести свой словарь для этого проекта")),
        ownDict && React.createElement(Input, { value: dictName, placeholder: title ? TR("Словарь: ") + title : TR("Название словаря"), onChange: (e) => setDictName(e.target.value) }),
        dicts.length > 0 && React.createElement("div", { className: "dim", style: { fontSize: 12, marginTop: 4 } }, TR("Подключить уже существующие:")),
        dicts.map(d => React.createElement(Checkbox, { key: d.id, checked: picked.indexOf(d.id) >= 0, onChange: () => toggle(d.id) },
          d.title + " · " + (d.count || 0) + " " + impPlural(d.count || 0, TR("слово"), TR("слова"), TR("слов"))
          + (d.pairs && d.pairs[pair] ? "" : (d.count ? TR(" · для пары ") + pair + TR(" слов нет") : "")))))));
}

/* ---------- Папка: файлы, словари, настройки ---------- */
function ImpFolderView({ folder, store, toast, meta }) {
  const st = impFolderStats(store, folder);
  const canOwner = !!(store.can && store.can.owner);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const rename = async () => {
    const t = prompt(TR("Название проекта"), folder.title || "");
    if (t == null || !t.trim() || t.trim() === folder.title) return;
    try {
      const r = await window.API.updateFolder(folder.id, { title: t.trim() });
      store.patchFolder(folder.id, { title: r.title, virtual: false });
      /* Файл-папка носит то же имя: сервер переименовал и его. */
      if (folder.virtual) store.patchProject(folder.id, { title: r.title });
      toast.success(TR("Переименовано"), r.title);
    } catch (e) { toast.error(TR("Не переименовано"), e.message || String(e)); }
  };
  const remove = async () => {
    try {
      await window.API.deleteFolder(folder.id, true);
      store.removeFolder(folder.id);
      toast.warning(TR("Проект удалён"), folder.title);
      store.setViewFolder(null);
    } catch (e) { toast.error(TR("Не удалён"), e.message || String(e)); }
  };
  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("button", { className: "linklike dim", style: { fontSize: 13, marginBottom: 6 }, onClick: () => store.setViewFolder(null) }, "← " + TR("Все проекты")),
      React.createElement("div", { className: "row between row-wrap", style: { alignItems: "flex-end", gap: 12 } },
        React.createElement("div", null,
          React.createElement("h1", null, folder.title || TR("Без названия"), " ",
            React.createElement(IconBtn, { icon: "edit", label: TR("Переименовать"), sm: true, onClick: rename })),
          React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap", marginTop: 6 } },
            React.createElement(LangPair, { src: folder.src, tgt: folder.tgt }),
            React.createElement(Badge, null, impDomainLabel(meta, folder.domain)),
            React.createElement(Badge, { icon: "file" }, st.files.length + " " + impPlural(st.files.length, TR("файл"), TR("файла"), TR("файлов"))),
            st.total > 0 && React.createElement(Badge, { icon: "check" }, TR("готово ") + st.pct + "%"))),
        canOwner && React.createElement(Btn, { variant: "ghost", size: "sm", icon: "trash", onClick: () => setConfirmDelete(true) }, TR("Удалить проект")))),

    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, TR("Файлы")),
      React.createElement("div", { className: "grid grid-3" },
        st.files.map(p => React.createElement(ImpFileCard, { key: p.id, project: p, store, toast })),
        React.createElement(ImpAddFile, { folder, store, toast }))),

    React.createElement("div", { className: "section" },
      React.createElement(ImpFolderDicts, { folder, store, toast })),

    confirmDelete && React.createElement(Modal, {
      title: TR("Удалить проект?"), icon: "trash", onClose: () => setConfirmDelete(false),
      footer: React.createElement(React.Fragment, null,
        React.createElement(Btn, { variant: "ghost", onClick: () => setConfirmDelete(false) }, TR("Отмена")),
        React.createElement(Btn, { variant: "danger", icon: "trash", onClick: remove }, TR("Удалить всё"))) },
      React.createElement("p", { style: { margin: 0 } },
        TR("Проект «"), React.createElement("strong", null, folder.title), TR("» и все его файлы будут удалены безвозвратно."),
        React.createElement("br", null),
        React.createElement("span", { className: "dim" }, st.files.length + TR(" файлов · ") + st.total + TR(" строк · ") + st.done + TR(" подтверждено")))));
}

/* Все форматы, которые принимает импорт. Список — зеркало backend/importers.py
   (SUPPORTED_EXT); браузер только подсказывает диалогу выбора файла, решает
   сервер (415 с причиной). */
const IMP_ACCEPT = ".docx,.xlsx,.pptx,.odt,.ods,.odp,.pdf,.txt,.md,.markdown,.csv,.tsv,.html,.htm,.xml,.json,.rtf,.srt,.vtt,.po,.log,.yml,.yaml,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.gif";

function ImpFileCard({ project, store, toast }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const counts = store.statusCounts(project);
  const total = project.segments.length;
  const done = counts.confirmed;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const handleDelete = () => { store.deleteProject(project.id); toast.warning(TR("Файл удалён"), project.title); };
  /* Картинка или скан: строк нет, пока не прочитан текст с картинок (платно).
     Кнопка ведёт на экран «Скачать» — там живёт разбор надписей со сметой
     и ходом работы; второй такой экран заводить нельзя. */
  const pictures = (project.importKind === "image" || project.importKind === "scan") && total === 0;
  const undoReimport = async () => {
    const m = project.reimport;
    if (!m || !confirm(TR("Вернуть прежнюю версию файла «") + project.title + TR("»? Строки, добавленные новой версией, исчезнут; перевод прежних вернётся."))) return;
    setBusy(true);
    try {
      let r;
      try { r = await window.API.undoReimport(project.id, m.stamp, false); }
      catch (e) {
        if (e.status !== 409 || !confirm((e.message || "") + " " + TR("Откатить всё равно?"))) throw e;
        r = await window.API.undoReimport(project.id, m.stamp, true);
      }
      const fresh = await window.API.getProject(project.id);
      if (fresh) store.replaceProject(fresh);
      toast.success(TR("Прежняя версия возвращена"), r.segments + TR(" строк"));
    } catch (e) { toast.error(TR("Не возвращена"), e.message || String(e)); }
    setBusy(false);
  };
  return React.createElement(React.Fragment, null,
    React.createElement("div", { className: "card card-pad card-hover", style: { display: "flex", flexDirection: "column", gap: 12 } },
      React.createElement("div", { className: "row between", style: { alignItems: "flex-start", gap: 8 } },
        React.createElement("div", { style: { minWidth: 0, fontWeight: 600, fontSize: 15, letterSpacing: "-.2px", overflow: "hidden", textOverflow: "ellipsis" } },
          React.createElement(Icon, { name: pictures ? "image" : "file", size: 14, style: { verticalAlign: "-2px", marginRight: 6, color: "var(--c-primary)" } }), project.title),
        React.createElement(IconBtn, { icon: "trash", label: TR("Удалить файл"), sm: true, onClick: (e) => { e.stopPropagation(); setConfirmDelete(true); } })),
      React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
        React.createElement(Badge, { icon: "list" }, total + " " + impPlural(total, TR("строка"), TR("строки"), TR("строк"))),
        project.sourceDocx && !project.importKind && React.createElement(Badge, { icon: "checkCircle" }, TR("вернём в том же виде")),
        project.importKind && project.importKind !== "docx" && React.createElement(Badge, { icon: "file" }, TR("вернём как Word")),
        project.reimport && React.createElement(Badge, { icon: "repeat" }, TR("обновлён ") + project.reimport.at)),
      project.importNote && React.createElement("div", { className: "dim", style: { fontSize: 12 } }, TRS(project.importNote)),
      pictures
        ? React.createElement("div", { className: "dim", style: { fontSize: 13 } }, TR("Текст на картинках ещё не прочитан."))
        : React.createElement("div", null,
            React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
              React.createElement("span", { className: "muted" }, TR("Готово")),
              React.createElement("span", { style: { fontWeight: 600 } }, pct + "%")),
            React.createElement(ProgressBar, { value: pct })),
      React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
        pictures
          ? React.createElement(Btn, { variant: "primary", size: "sm", icon: "image", onClick: () => { store.openProject(project.id); store.go("export"); } }, TR("Прочитать текст с картинок"))
          : React.createElement(Btn, { variant: "primary", size: "sm", icon: "edit", onClick: () => store.openProject(project.id) }, TR("Переводить")),
        React.createElement(Btn, { variant: "ghost", size: "sm", icon: "download", onClick: () => { store.openProject(project.id); store.go("export"); } }, TR("Скачать")),
        project.reimport && React.createElement(Btn, { variant: "ghost", size: "sm", icon: "repeat", disabled: busy, onClick: undoReimport }, TR("Вернуть прежнюю версию")))),
    confirmDelete && React.createElement(Modal, {
      title: TR("Удалить файл?"), icon: "trash", onClose: () => setConfirmDelete(false),
      footer: React.createElement(React.Fragment, null,
        React.createElement(Btn, { variant: "ghost", onClick: () => setConfirmDelete(false) }, TR("Отмена")),
        React.createElement(Btn, { variant: "danger", icon: "trash", onClick: handleDelete }, TR("Удалить"))) },
      React.createElement("p", { style: { margin: 0 } },
        TR("Файл «"), React.createElement("strong", null, project.title), TR("» будет удалён безвозвратно. "),
        React.createElement("br", null),
        React.createElement("span", { className: "dim" }, total + TR(" строк · ") + done + TR(" подтверждено")))));
}

/* Добавить файл в проект: пара и тема берутся у проекта.
   Сначала ПРОБА (сервер, бесплатно): тот же файл уже есть? похож на новую
   версию файла проекта? Тогда человек выбирает — обновить прежний файл
   (перевод неизменившихся строк остаётся) или положить новым. */
function ImpAddFile({ folder, store, toast }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [probe, setProbe] = useState(null);      // ответ /api/projects/probe
  const [probing, setProbing] = useState(false);
  const fileRef = useRef(null);
  const probeSeq = useRef(0);
  /* Номер запроса: выбрал файл A, сразу B — ответ A может прийти позже
     и лечь на B. Устаревший ответ выбрасывается. */
  const runProbe = async (raw) => {
    const seq = ++probeSeq.current;
    setProbing(true); setProbe(null);
    let res;
    try { res = await window.API.probeUpload(raw, folder.id); }
    catch (e) { res = { error: e.message || String(e) }; }
    if (seq !== probeSeq.current) return;
    setProbe(res);
    setProbing(false);
  };
  const pickFile = (f) => {
    if (!f) return;
    setFile({ name: f.name, size: (f.size / 1024).toFixed(0) + TR(" КБ"), raw: f });
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
    runProbe(f);
  };
  const onDrop = (e) => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) pickFile(f); };
  const reset = () => { setFile(null); setTitle(""); setProbe(null); };
  const create = async () => {
    if (!file || !file.raw) { toast.error(TR("Файл не выбран"), TR("Выберите файл")); return; }
    setBusy(true);
    try {
      const project = await window.API.uploadProject(file.raw, title || file.name.replace(/\.[^.]+$/, ""),
                                                    folder.src, folder.tgt, folder.domain, folder.id);
      store.addProject(project);
      /* Виртуальная папка после второго файла стала настоящей записью. */
      store.patchFolder(folder.id, { virtual: false });
      reset();
      toast.success(TR("Файл добавлен"), project.segments.length + TR(" строк готовы к переводу.")
        + (project.importNote ? " " + project.importNote : ""));
      store.openProject(project.id);
    } catch (e) { toast.error(TR("Файл не добавлен"), e.message || TR("Не удалось разобрать файл")); }
    setBusy(false);
  };
  const update = async (target) => {
    if (!file || !file.raw) return;
    /* Заверенное человеком и распознанное на картинках уходит в копию —
       это названо числом ДО записи, а не после. */
    const warn = [];
    if (target.removedConfirmed) warn.push(TR("исчезнет заверённых человеком строк: ") + target.removedConfirmed);
    if (target.images) warn.push(TR("строки с картинок придётся прочитать заново: ") + target.images);
    if (warn.length && !confirm(TR("Обновить файл «") + target.title + "»? " + warn.join("; ") + ". "
        + TR("Прежняя версия сохранится, вернуть можно с карточки файла."))) return;
    setBusy(true);
    try {
      const r = await window.API.reimport(target.id, file.raw, false);
      const fresh = await window.API.getProject(target.id);
      if (fresh) store.replaceProject(fresh);
      reset();
      toast.success(TR("Файл обновлён"), TR("Осталось ") + (r.kept + r.moved) + TR(" строк, новых ") + r.added
        + TR(", исчезло ") + r.removed + TR(". Прежняя версия сохранена — вернуть можно с карточки файла."));
      store.openProject(target.id);
    } catch (e) { toast.error(TR("Файл не обновлён"), e.message || String(e)); }
    setBusy(false);
  };
  const exact = probe && probe.exact && probe.exact[0];
  const similar = probe && probe.similar && probe.similar[0];
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Добавить файл")),
    React.createElement("div", {
      className: "dropzone" + (dragging ? " drag" : ""), style: { padding: 18 },
      onDragOver: (e) => { e.preventDefault(); setDragging(true); }, onDragLeave: () => setDragging(false), onDrop,
      onClick: () => fileRef.current && fileRef.current.click(), role: "button", tabIndex: 0,
      onKeyDown: (e) => { if (e.key === "Enter") fileRef.current.click(); } },
      React.createElement("input", { ref: fileRef, type: "file", accept: IMP_ACCEPT, hidden: true, onChange: (e) => pickFile(e.target.files[0]) }),
      file
        ? React.createElement("div", null,
            React.createElement(Icon, { name: "file", size: 28, className: "dz-ic", style: { color: "var(--c-success)" } }),
            React.createElement("div", { style: { fontWeight: 500, fontSize: 14 } }, file.name),
            React.createElement("div", { className: "dim", style: { marginTop: 2, fontSize: 12 } }, file.size + TR(" · нажмите, чтобы заменить")))
        : React.createElement("div", null,
            React.createElement(Icon, { name: "upload", size: 28, className: "dz-ic" }),
            React.createElement("div", { style: { fontWeight: 500, fontSize: 14 } }, TR("Перетащите файл сюда")),
            React.createElement("div", { className: "dim", style: { marginTop: 2, fontSize: 12 } }, TR("Word, Excel, PowerPoint, PDF, HTML, текст или картинка")))),
    probing && React.createElement("div", { className: "dim", style: { fontSize: 12 } }, TR("Смотрим, что за файл…")),
    probe && probe.error && React.createElement("div", { style: { color: "var(--c-danger)", fontSize: 13 } }, probe.error),
    exact && React.createElement("div", { className: "card card-pad-sm", style: { background: "var(--bg-sunken)", fontSize: 13 } },
      TR("Этот файл уже есть в проекте: «") + exact.title + TR("». Второй раз он не нужен."),
      React.createElement("div", { className: "row", style: { gap: 8, marginTop: 8 } },
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "edit", onClick: () => store.openProject(exact.id) }, TR("Открыть его")),
        React.createElement(Btn, { variant: "ghost", size: "sm", onClick: reset }, TR("Выбрать другой файл")))),
    !exact && similar && React.createElement("div", { className: "card card-pad-sm", style: { background: "var(--bg-sunken)", fontSize: 13 } },
      TR("Похоже на новую версию файла «") + similar.title + TR("»: совпало ") + similar.matched + TR(" из ") + similar.total
        + TR(" строк, новых ") + similar.added + TR(", исчезнет ") + similar.removed + ".",
      React.createElement("div", { className: "row", style: { gap: 8, marginTop: 8, flexWrap: "wrap" } },
        React.createElement(Btn, { variant: "primary", size: "sm", icon: "repeat", disabled: busy, onClick: () => update(similar) }, TR("Обновить «") + similar.title + "»"),
        React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy, onClick: create }, TR("Добавить как новый файл")))),
    /* Пометка сервера о формате — русская фраза нашего кода: переводится
       подстановкой TRS() из серверной таблицы, как все detail. */
    probe && !probe.error && probe.note && React.createElement("div", { className: "dim", style: { fontSize: 12 } }, TRS(probe.note)),
    file && !exact && React.createElement(Input, { value: title, placeholder: TR("Название файла"), onChange: (e) => setTitle(e.target.value) }),
    !exact && !similar && React.createElement(Btn, { variant: "primary", icon: busy ? null : "plus", disabled: !file || busy || probing, onClick: create },
      busy ? React.createElement(React.Fragment, null, React.createElement(Spinner, null), TR("Загружаем…")) : TR("Добавить в проект")),
    file && !exact && React.createElement(ImpQuote, { file, src: folder.src, tgt: folder.tgt, toast }));
}

/* Словари проекта: какие подключены и куда пишутся новые слова.
   Порядок в списке — очерёдность: первый сильнее, туда идут новые слова. */
function ImpFolderDicts({ folder, store, toast }) {
  const all = store.dicts || [];
  const current = impFolderDicts(folder);
  const [picked, setPicked] = useState(current === null ? all.map(d => d.id) : current);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  /* Список словарей организации приезжает позже первого кадра, а папка
     может смениться: отмеченные пересчитываются по папке и по списку. */
  useEffect(() => {
    if (!dirty) setPicked(current === null ? all.map(d => d.id) : current);
  }, [folder.id, all.length, current === null ? "all" : current.join(",")]);
  const pair = folder.src + "→" + folder.tgt;
  const toggle = (id) => { setPicked(p => p.indexOf(id) >= 0 ? p.filter(x => x !== id) : p.concat([id])); setDirty(true); };
  const moveUp = (id) => { setPicked(p => { const i = p.indexOf(id); if (i <= 0) return p; const q = p.slice(); q.splice(i, 1); q.splice(i - 1, 0, id); return q; }); setDirty(true); };
  const save = async (list) => {
    setBusy(true);
    try {
      const r = await window.API.updateFolder(folder.id, { dicts: list });
      store.patchFolder(folder.id, { dicts: r.dicts, virtual: false });
      setPicked(r.dicts); setDirty(false);
      toast.success(TR("Словари проекта сохранены"), r.dicts.length + " " + impPlural(r.dicts.length, TR("словарь"), TR("словаря"), TR("словарей")));
    } catch (e) { toast.error(TR("Не сохранено"), e.message || String(e)); }
    setBusy(false);
  };
  const addNew = async () => {
    const name = prompt(TR("Название нового словаря"), TR("Словарь: ") + (folder.title || ""));
    if (name == null || !name.trim()) return;
    setBusy(true);
    try {
      const r = await window.API.createDict({ title: name.trim(), domain: folder.domain });
      if (store.setDicts) store.setDicts(all.concat([r.dict]));
      // Новый словарь — первым: новые слова проекта идут туда.
      await save([r.dict.id].concat(picked.filter(x => x !== r.dict.id)));
    } catch (e) { toast.error(TR("Словарь не создан"), e.message || String(e)); }
    setBusy(false);
  };
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "row between row-wrap", style: { gap: 8 } },
      React.createElement("h2", { className: "section-title", style: { margin: 0 } }, TR("Словари проекта")),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Btn, { variant: "ghost", size: "sm", icon: "plus", disabled: busy, onClick: addNew }, TR("Новый словарь")),
        dirty && React.createElement(Btn, { variant: "primary", size: "sm", icon: "check", disabled: busy, onClick: () => save(picked) }, TR("Сохранить")))),
    React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13 } },
      TR("Отмеченные словари подсказывают перевод слов в этом проекте. Новые слова проекта попадают в первый словарь списка.")),
    current === null && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
      TR("Пока подключены все словари организации — так было до появления словарей. Снимите лишние и сохраните.")),
    all.length === 0 && React.createElement("div", { className: "dim", style: { fontSize: 13 } }, TR("Словарей пока нет — заведите первый.")),
    React.createElement("div", { className: "col", style: { gap: 6 } },
      picked.map((id, i) => {
        const d = all.find(x => x.id === id) || { id, title: id, count: 0, pairs: {} };
        return React.createElement("div", { key: id, className: "row", style: { gap: 8, alignItems: "center" } },
          React.createElement(Checkbox, { checked: true, onChange: () => toggle(id) },
            d.title + " · " + (d.count || 0) + " " + impPlural(d.count || 0, TR("слово"), TR("слова"), TR("слов"))),
          i === 0 && React.createElement("span", { className: "st-chip" }, TR("сюда пишутся новые слова")),
          i > 0 && React.createElement("button", { className: "linklike dim", style: { fontSize: 12 }, onClick: () => moveUp(id) }, TR("выше")),
          d.count > 0 && !(d.pairs || {})[pair] && React.createElement("span", { className: "dim", style: { fontSize: 12 } }, TR("для пары ") + pair + TR(" слов нет")));
      }),
      all.filter(d => picked.indexOf(d.id) < 0).map(d => React.createElement(Checkbox, { key: d.id, checked: false, onChange: () => toggle(d.id) },
        d.title + " · " + (d.count || 0) + " " + impPlural(d.count || 0, TR("слово"), TR("слова"), TR("слов"))))));
}
window.TabImport = TabImport;
