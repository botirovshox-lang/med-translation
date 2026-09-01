/* ============================================================
   Tab: Import DOCX — create projects from Word documents
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
  const run = async () => {
    if (!file || !file.raw) { toast.error("Файл не выбран", "Выберите файл, чтобы посчитать объём"); return; }
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
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, "Объём и стоимость"),
    React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13 } },
      "Знаки исходника с пробелами делятся на норму страницы для языка оригинала. Цену за страницу задаёт владелец организации."),
    React.createElement("div", null,
      React.createElement(Btn, { variant: "ghost", disabled: !file || busy, onClick: run },
        busy ? "Считаем…" : "Посчитать объём и стоимость")),
    err && React.createElement("div", { className: "dim", style: { color: "var(--c-danger)", fontSize: 13 } }, err),
    res && React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6, fontSize: 14 } },
      row("Знаков с пробелами", res.counts.chars.toLocaleString("ru-RU")),
      row("Без пробелов", res.counts.charsNoSpaces.toLocaleString("ru-RU")),
      row("Слов", res.counts.words.toLocaleString("ru-RU")),
      row("Норма страницы (" + res.norm.lang + ")", res.norm.chars + " знаков"
        + (res.norm.source === "tenant" ? " · ваша" : res.norm.source === "default" ? " · по умолчанию" : "")),
      row("Страниц", res.pages.exact + " → к оплате " + res.pages.billed),
      row("Цена страницы", res.rate.price == null ? "не задана"
        : res.rate.price + " " + res.currency + (res.rate.source === "pair" ? " · по паре" : " · общая")),
      React.createElement("div", {
        style: { display: "flex", justifyContent: "space-between", borderTop: "1px solid var(--c-border)", paddingTop: 8 }
      },
        React.createElement("span", null, "Итого"),
        React.createElement("b", { style: { fontSize: 18 } },
          res.total == null ? "цена не задана" : res.total.toLocaleString("ru-RU") + " " + res.currency)),
      res.rate.price == null && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        "Задайте цену за страницу во вкладке «Организация» — до этого сумму показать нечем."),
      res.counts.repeatBlocks > 0 && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        "Повторов: " + res.counts.repeatBlocks + " кусков на " + res.counts.repeatChars.toLocaleString("ru-RU")
        + " знаков. Из объёма они НЕ вычтены — скидку за повторы решает продавец."),
      (res.notes || []).map((n, i) => React.createElement("div", { key: i, className: "dim", style: { fontSize: 12 } }, n)),
      React.createElement("div", { className: "dim", style: { fontSize: 12 } }, res.formula),
      res.saved && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        "Сохранено в историю смет " + res.saved.at + " — вернуться к оплате можно ниже.")));
}


/* ── История смет: к чему вернуться при оплате ──────────────────────
   Числа в записи ЗАМОРОЖЕНЫ на момент расчёта и здесь не пересчитываются:
   клиент считал по вчерашнему прайсу, платит по нему же. Пересчитанная
   задним числом смета — другая сумма под тем же счётом.
   Право пометить оплаченной — у владельца (сервер вернёт 403 остальным):
   это решение про деньги, а не про перевод. */
const IMP_QUOTE_STATUS = { new: "черновик", invoiced: "выставлен счёт", paid: "оплачена" };

function ImpQuoteHistory({ reloadKey, toast, canOwner }) {
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(false);
  const load = () => window.API.safeCall(() => window.API.quotes()).then(r => r && setRows(r.quotes || []));
  useEffect(() => { load(); }, [reloadKey]);
  if (!rows || !rows.length) return null;
  const mark = async (q, status) => {
    try { await window.API.quoteMark(q.id, { status }); toast.success("Смета отмечена", IMP_QUOTE_STATUS[status]); load(); }
    catch (e) { toast.error("Не отмечена", e.message || String(e)); }
  };
  const del = async (q) => {
    if (!confirm("Удалить смету по «" + q.file + "» на " + q.total + " " + q.currency + "?")) return;
    try { await window.API.quoteDelete(q.id); toast.success("Смета удалена", q.file); load(); }
    catch (e) { toast.error("Не удалена", e.message || String(e)); }
  };
  const shown = open ? rows : rows.slice(0, 5);
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, "История смет · " + rows.length),
    React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13 } },
      "Числа сохранены такими, какими их посчитали тогда: смена прайса старые сметы не трогает."),
    React.createElement("div", { style: { overflowX: "auto" } }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        ["Дата", "Файл", "Пара", "Знаков", "Страниц", "Цена", "Итого", "Состояние", ""].map((h, i) =>
          React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, shown.map(q => React.createElement("tr", { key: q.id, title: q.formula || "" },
        React.createElement("td", { style: { whiteSpace: "nowrap" } }, q.at),
        React.createElement("td", null, q.file || "—", q.count > 1 ? React.createElement("span", { className: "dim" }, " · считали " + q.count + " раз") : null),
        React.createElement("td", null, q.src + "→" + q.tgt),
        React.createElement("td", null, Number(q.chars).toLocaleString("ru-RU")),
        React.createElement("td", null, q.pagesBilled),
        React.createElement("td", null, q.pricePerPage == null ? "—" : q.pricePerPage + " " + q.currency),
        React.createElement("td", null, React.createElement("b", null,
          q.total == null ? "цена не задана" : Number(q.total).toLocaleString("ru-RU") + " " + q.currency)),
        React.createElement("td", null, IMP_QUOTE_STATUS[q.status] || q.status,
          q.paidAt ? React.createElement("span", { className: "dim" }, " · " + q.paidAt) : null),
        React.createElement("td", { style: { whiteSpace: "nowrap", textAlign: "right" } },
          canOwner && q.status !== "invoiced" && q.status !== "paid" && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => mark(q, "invoiced") }, "Счёт выставлен"),
          canOwner && q.status !== "paid" && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => mark(q, "paid") }, "Оплачена"),
          canOwner && q.status === "paid" && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => mark(q, "new") }, "Вернуть в черновик"),
          canOwner && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => del(q) }, "Удалить"))))))),
    rows.length > 5 && React.createElement("div", null,
      React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setOpen(!open) },
        open ? "Свернуть" : "Показать все " + rows.length)));
}

function TabImport({ store, toast }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);      // { name, size, raw: File }
  const [title, setTitle] = useState("");
  const [src, setSrc] = useState("RU");
  const [tgt, setTgt] = useState("EN");
  const [domain, setDomain] = useState("medical");   // область: от неё зависят промпты перевода и проверки
  const [domains, setDomains] = useState([["medical", "Медицина"]]);
  // Каталог языков — тоже с сервера: пара проекта может быть любой.
  const [langs, setLangs] = useState([["RU", "Русский"], ["EN", "Английский"]]);
  const [creating, setCreating] = useState(false);
  const [quoted, setQuoted] = useState(0);   // счётчик сохранённых смет: им обновляется история
  const [progress, setProgress] = useState("");
  const fileRef = useRef(null);

  // Каталог областей живёт на сервере (DOMAINS в main.py) — хардкодить нельзя
  useEffect(() => {
    window.API && window.API.safeCall(() => window.API.models()).then(res => {
      if (res && res.domains && res.domains.length) {
        setDomains(res.domains.map(d => [d.id, d.label]));
        setDomain(res.domainDefault || res.domains[0].id);
      }
      if (res && res.languages && res.languages.length)
        setLangs(res.languages.map(l => [l.code, l.ru + " · " + l.native]));
    });
  }, []);

  const pickFile = (f) => {
    if (!f) return;
    setFile({ name: f.name, size: (f.size / 1024).toFixed(0) + " КБ", raw: f });
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  };
  const onDrop = (e) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) pickFile(f);
  };
  const create = async () => {
    if (!file || !file.raw) { toast.error("Файл не выбран", "Выберите .docx файл"); return; }
    setCreating(true);
    setProgress("Загружаем файл…");
    try {
      const project = await window.API.uploadProject(file.raw, title || file.name.replace(/\.[^.]+$/, ""), src, tgt, domain);
      setProgress("");
      setCreating(false);
      store.addProject(project);
      toast.success("Проект создан", project.segments.length + " сегментов готовы к переводу.");
      store.openProject(project.id);
    } catch (e) {
      setProgress("");
      setCreating(false);
      toast.error("Ошибка импорта", e.message || "Не удалось разобрать файл");
    }
  };

  const langOpts = langs;
  const pairBad = src === tgt;

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Импорт документа"),
      React.createElement("p", { className: "lead" }, "Загрузите файл Word, чтобы создать новый проект перевода. Документ автоматически разбивается на сегменты с сохранением форматирования.")
    ),

    // Section 1: upload
    React.createElement("div", { className: "section" },
      React.createElement("div", { className: "grid", style: { gridTemplateColumns: "1.3fr 1fr", gap: 24, alignItems: "start" } },
        React.createElement("div", null,
          React.createElement("div", { className: "eyebrow" }, "Шаг 1 — Файл"),
          React.createElement("div", {
            className: "dropzone" + (dragging ? " drag" : ""),
            onDragOver: (e) => { e.preventDefault(); setDragging(true); },
            onDragLeave: () => setDragging(false),
            onDrop,
            onClick: () => fileRef.current && fileRef.current.click(),
            role: "button", tabIndex: 0,
            onKeyDown: (e) => { if (e.key === "Enter") fileRef.current.click(); },
          },
            React.createElement("input", { ref: fileRef, type: "file", accept: ".docx", hidden: true,
              onChange: (e) => pickFile(e.target.files[0]) }),
            file
              ? React.createElement("div", null,
                  React.createElement(Icon, { name: "file", size: 36, className: "dz-ic", style: { color: "var(--c-success)" } }),
                  React.createElement("div", { style: { fontWeight: 650, fontSize: 16 } }, file.name),
                  React.createElement("div", { className: "dim", style: { marginTop: 4 } }, file.size + " · нажмите, чтобы заменить"))
              : React.createElement("div", null,
                  React.createElement(Icon, { name: "upload", size: 36, className: "dz-ic" }),
                  React.createElement("div", { style: { fontWeight: 650, fontSize: 16 } }, "Перетащите DOCX сюда"),
                  React.createElement("div", { className: "dim", style: { marginTop: 4 } }, "или нажмите для выбора файла"))
          )
        ),
        React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 18 } },
          React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, "Шаг 2 — Параметры"),
          React.createElement(Field, { label: "Название проекта" },
            React.createElement(Input, { value: title, placeholder: "напр. Эпикриз 2026", onChange: (e) => setTitle(e.target.value) })),
          React.createElement("div", { className: "grid grid-2" },
            React.createElement(Field, { label: "Язык оригинала" },
              React.createElement(Select, { value: src, onChange: (e) => setSrc(e.target.value) },
                langOpts.map(([v, l]) => React.createElement("option", { key: v, value: v }, l)))),
            React.createElement(Field, { label: "Язык перевода" },
              React.createElement(Select, { value: tgt, onChange: (e) => setTgt(e.target.value) },
                langOpts.map(([v, l]) => React.createElement("option", { key: v, value: v }, l))))
          ),
          pairBad && React.createElement("div", { style: { color: "var(--c-danger)", fontSize: 13 } },
            "Язык оригинала и язык перевода совпадают."),
          React.createElement(Field, { label: "Предметная область",
            hint: "Задаёт терминологию в промптах перевода и проверки. Меняется только для новых проектов." },
            React.createElement(Select, { value: domain, onChange: (e) => setDomain(e.target.value) },
              domains.map(([v, l]) => React.createElement("option", { key: v, value: v }, l)))),
          React.createElement(Btn, { variant: "primary", icon: creating ? null : "arrowR", disabled: !file || !file.raw || creating, onClick: create },
            creating ? React.createElement(React.Fragment, null, React.createElement(Spinner, null), progress || "Загрузка…") : "Создать проект")
        )
      ),
      // Смета стоит РЯДОМ с выбором файла и пары: считается она по языку
      // исходника и по прайсу организации, и оба уже выбраны выше.
      React.createElement("div", { style: { marginTop: 20, maxWidth: 560 } },
        React.createElement(ImpQuote, { file, src, tgt, toast, onSaved: () => setQuoted(quoted + 1) })),
      React.createElement("div", { style: { marginTop: 16 } },
        React.createElement(ImpQuoteHistory, { reloadKey: quoted, toast, canOwner: !!(store.can && store.can.owner) }))
    ),

    // Section 2: existing projects
    React.createElement("div", { className: "section" },
      React.createElement("div", { className: "row between", style: { marginBottom: 16 } },
        React.createElement("h2", { className: "section-title", style: { margin: 0 } }, "Ваши проекты"),
        React.createElement("span", { className: "dim" }, store.projects.length + " всего")
      ),
      React.createElement("div", { className: "grid grid-3" },
        store.projects.map(p => React.createElement(ProjectCard, { key: p.id, project: p, store, toast }))
      )
    )
  );
}

function ProjectCard({ project, store, toast }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const counts = store.statusCounts(project);
  const total = project.segments.length;
  const done = counts.confirmed;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const statusMap = { in_progress: ["badge-review", "В работе"], review: ["badge-qa", "На проверке"], done: ["badge-confirmed", "Завершён"] };
  const [bcls, blab] = statusMap[project.status] || statusMap.in_progress;

  const handleDelete = () => {
    store.deleteProject(project.id);
    toast.warning("Проект удалён", project.title);
  };

  return React.createElement(React.Fragment, null,
    React.createElement("div", { className: "card card-pad card-hover", style: { display: "flex", flexDirection: "column", gap: 14 } },
      React.createElement("div", { className: "row between", style: { alignItems: "flex-start" } },
        React.createElement("div", { style: { minWidth: 0 } },
          React.createElement("div", { style: { fontWeight: 700, fontSize: 16, letterSpacing: "-.2px" } }, project.title),
          React.createElement("div", { className: "dim", style: { fontSize: 13, marginTop: 2 } }, project.titleEn)),
        React.createElement("span", { className: "badge " + bcls }, blab)
      ),
      React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
        React.createElement(Badge, { icon: "list" }, total + " сегментов"),
        React.createElement(LangPair, { src: project.src, tgt: project.tgt })
      ),
      React.createElement("div", null,
        React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
          React.createElement("span", { className: "muted" }, "Подтверждено"),
          React.createElement("span", { style: { fontWeight: 700 } }, pct + "%")),
        React.createElement(ProgressBar, { value: pct })
      ),
      React.createElement("div", { className: "row between", style: { marginTop: 2 } },
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "edit", onClick: () => store.openProject(project.id) }, "Открыть"),
          React.createElement(Btn, { variant: "ghost", size: "sm", icon: "download", onClick: () => { store.openProject(project.id); store.go("export"); } }, "Экспорт")
        ),
        React.createElement(IconBtn, { icon: "trash", label: "Удалить проект", sm: true, onClick: (e) => { e.stopPropagation(); setConfirmDelete(true); } })
      )
    ),
    confirmDelete && React.createElement(Modal, {
      title: "Удалить проект?", icon: "trash", onClose: () => setConfirmDelete(false),
      footer: React.createElement(React.Fragment, null,
        React.createElement(Btn, { variant: "ghost", onClick: () => setConfirmDelete(false) }, "Отмена"),
        React.createElement(Btn, { variant: "danger", icon: "trash", onClick: handleDelete }, "Удалить"))
    },
      React.createElement("p", { style: { margin: 0 } },
        "Проект «", React.createElement("strong", null, project.title), "» будет удалён безвозвратно. ",
        React.createElement("br", null),
        React.createElement("span", { className: "dim" }, total + " сегментов · " + done + " подтверждено"))
    )
  );
}
window.TabImport = TabImport;
