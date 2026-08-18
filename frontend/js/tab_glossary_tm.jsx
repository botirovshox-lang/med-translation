/* ============================================================
   Tab: Glossary — medical terminology management
   ============================================================ */
const PAGE_SIZE = 100;

// Поиск с выбором стороны: русский термин или английский перевод.
// «ё» приравнена к «е» — в медицинских текстах их пишут вперемешку.
const PAIR_SCOPES = [["all", "Везде"], ["src", "Оригинал (RU)"], ["tgt", "Перевод (EN)"]];
function pairNorm(t) { return (t || "").toLowerCase().replace(/ё/g, "е"); }
function pairMatches(row, q, scope) {
  const needle = pairNorm(q);
  if (!needle) return true;
  return (scope !== "tgt" && pairNorm(row.src).includes(needle))
      || (scope !== "src" && pairNorm(row.tgt).includes(needle));
}
function ScopeSelect({ value, onChange }) {
  return React.createElement(Select, { value, onChange, style: { width: "auto" }, "aria-label": "Где искать" },
    PAIR_SCOPES.map(([v, l]) => React.createElement("option", { key: v, value: v }, l)));
}


/* ============================================================
   Очередь кандидатов в глоссарий
   Сюда попадает всё, чему система научилась сама: расхождения между
   глоссарием и подтверждённым переводом, короткие подтверждённые сегменты,
   извлечённые моделью пары. В глоссарий кандидат уходит ТОЛЬКО после
   одобрения человеком — записи глоссария идут в промпт как правило, и
   автопополнение закрепляло бы собственные ошибки.
   ============================================================ */
const CAND_KIND = {
  conflict: ["Конфликт с глоссарием", "warn", "var(--c-warning)"],
  segment:  ["Из подтверждённого сегмента", "checkCircle", "var(--c-success)"],
  extract:  ["Извлечено моделью", "cpu", "var(--c-primary)"],
  audit:    ["Проверка терминологии", "book", "var(--c-purple)"],
};

function TermQueue({ store, toast }) {
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({});
  const [loading, setLoading] = useState(true);
  const [drafts, setDrafts] = useState({});      // {id: предлагаемый перевод}
  const [busy, setBusy] = useState(null);
  const [open, setOpen] = useState(true);

  const load = async () => {
    if (!window.API) { setLoading(false); return; }
    const res = await window.API.safeCall(() => window.API.termQueue("pending", 200));
    setItems((res && res.items) || []);
    setCounts((res && res.counts) || {});
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const approve = async (c) => {
    const tgt = (drafts[c.id] !== undefined ? drafts[c.id] : c.tgt || "").trim();
    if (!tgt) { toast.warning("Нужен перевод", "Впишите верный вариант — он станет проверенной записью глоссария."); return; }
    setBusy(c.id);
    const res = await window.API.safeCall(() => window.API.approveTerm(c.id, { tgt }));
    setBusy(null);
    if (!res || !res.ok) { toast.error("Не удалось одобрить", "Сервер не ответил."); return; }
    setItems(list => list.filter(x => x.id !== c.id));
    toast.success(res.replaced ? "Запись глоссария заменена" : "Термин добавлен в глоссарий", c.src + " → " + tgt);
  };

  const reject = async (c) => {
    setBusy(c.id);
    const res = await window.API.safeCall(() => window.API.rejectTerm(c.id));
    setBusy(null);
    if (!res || !res.ok) { toast.error("Не удалось отклонить", "Сервер не ответил."); return; }
    setItems(list => list.filter(x => x.id !== c.id));
    toast.info("Отклонено", "Этот кандидат больше не всплывёт.");
  };

  if (loading) return null;
  if (!items.length && !(counts.pending > 0)) return null;

  return React.createElement("div", { className: "card card-pad", style: { marginBottom: 18 } },
    React.createElement("div", { className: "row between", style: { cursor: "pointer" }, onClick: () => setOpen(o => !o) },
      React.createElement("div", { className: "row", style: { gap: 10 } },
        React.createElement(Icon, { name: open ? "chevD" : "chevR", size: 16 }),
        React.createElement("h3", { style: { margin: 0, fontSize: 16 } }, "Кандидаты в глоссарий"),
        React.createElement(Badge, { variant: "review" }, items.length),
        React.createElement(InfoTip, { title: "Откуда берутся кандидаты",
          body: "Система учится на подтверждённых сегментах: расхождение с глоссарием, короткий сегмент-термин, извлечение моделью. Ни один кандидат не попадает в глоссарий сам — глоссарий уходит в промпт как правило, и автопополнение закрепляло бы ошибки перевода." })),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } },
        "по частоте · одобрено: " + (counts.approved || 0) + " · отклонено: " + (counts.rejected || 0))),

    open && React.createElement("div", { className: "col", style: { gap: 10, marginTop: 14 } },
      items.map(c => {
        const [label, icon, color] = CAND_KIND[c.kind] || ["Кандидат", "info", "var(--text-2)"];
        return React.createElement("div", { key: c.id, className: "card", style: { padding: "12px 14px", background: "var(--bg-sunken)", display: "flex", flexDirection: "column", gap: 8 } },
          React.createElement("div", { className: "row between row-wrap", style: { gap: 8 } },
            React.createElement("div", { className: "row", style: { gap: 8 } },
              React.createElement(Icon, { name: icon, size: 15, style: { color } }),
              React.createElement("span", { style: { fontSize: 12, color, fontWeight: 600 } }, label),
              c.hits > 1 && React.createElement(Badge, { variant: "soft" }, "встречалось " + c.hits + "×")),
            React.createElement("span", { className: "dim", style: { fontSize: 12 } },
              (c.project ? "проект #" + c.project : "") + (c.segment ? " · сегмент #" + c.segment : ""))),

          React.createElement("div", { className: "row row-wrap", style: { gap: 10, alignItems: "center" } },
            React.createElement("span", { style: { fontWeight: 600 } }, c.src),
            React.createElement(Icon, { name: "chevR", size: 14, style: { color: "var(--text-3)" } }),
            React.createElement(Input, {
              value: drafts[c.id] !== undefined ? drafts[c.id] : (c.tgt || ""),
              placeholder: c.kind === "conflict" ? "верный перевод" : "перевод",
              onChange: (e) => setDrafts(d => ({ ...d, [c.id]: e.target.value })),
              style: { maxWidth: 320 } }),
            c.wasTgt && React.createElement("span", { className: "dim", style: { fontSize: 12.5 } },
              "в глоссарии сейчас: ", React.createElement("s", null, c.wasTgt))),

          c.note && React.createElement("div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.5 } }, c.note),

          c.sampleSrc && React.createElement("div", { className: "dim", style: { fontSize: 12, lineHeight: 1.6 } },
            React.createElement("div", null, c.sampleSrc),
            React.createElement("div", { style: { color: "var(--c-primary)" } }, c.sampleTgt)),

          React.createElement("div", { className: "row", style: { gap: 8 } },
            React.createElement(Btn, { variant: "primary", size: "sm", icon: "check", disabled: busy === c.id, onClick: () => approve(c) }, "В глоссарий"),
            React.createElement(Btn, { variant: "ghost", size: "sm", icon: "close", disabled: busy === c.id, onClick: () => reject(c) }, "Отклонить")));
      }),
      !items.length && React.createElement("div", { className: "dim", style: { fontSize: 13 } }, "Нерешённых кандидатов нет.")
    )
  );
}

function TabGlossary({ store, toast }) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [cat, setCat] = useState("all");
  const [sort, setSort] = useState("alpha");
  const [modal, setModal] = useState(null);
  const [allTerms, setAllTerms] = useState(store.glossary);
  const [loaded, setLoaded] = useState(false);
  const [page, setPage] = useState(0);

  // Load full glossary from API on mount
  useEffect(() => {
    if (loaded) return;
    window.API && window.API.safeCall(() => window.API.listGlossary("", "", 10000, 0)).then(res => {
      if (res && res.items) { setAllTerms(res.items); store.glossary = res.items; }
      setLoaded(true);
    });
  }, []);

  // Reset page on filter change
  useEffect(() => { setPage(0); }, [query, scope, cat, sort]);

  const cats = ["all", "Anatomy", "Cardiology", "Disease", "Dosage", "Symptom", "Lab", "Procedure", "Device", "Document"];
  let rows = allTerms.filter(g => {
    if (cat !== "all" && g.cat !== cat) return false;
    if (query && !pairMatches(g, query, scope)) return false;
    return true;
  });
  rows = rows.slice().sort((a, b) => sort === "freq" ? (b.freq||0) - (a.freq||0) : a.src.localeCompare(b.src, "ru"));
  const totalPages = Math.ceil(rows.length / PAGE_SIZE);
  const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const save = (term, isNew) => {
    store.saveTerm(term, isNew);
    setModal(null);
    toast.success(isNew ? "Термин добавлен" : "Термин обновлён", term.src + " → " + term.tgt);
  };
  const del = (term) => { store.deleteTerm(term); toast.warning("Термин удалён", term.src); };

  // Клик по самому термину = «покажи, где он используется»: открываем редактор
  // с фильтром по затронутым сегментам. Совпадения ищет сервер тем же матчером,
  // что и инъекция в промпт, — иначе список разошёлся бы с реальностью.
  const openUsage = async (term, e) => {
    e.stopPropagation();
    if (!window.API) return;
    const res = await window.API.safeCall(() => window.API.glossaryUsage(term.src, 1));
    if (!res || !res.total) {
      toast.info("Термин не встречается", "«" + term.src + "» не найден ни в одном сегменте проектов.");
      return;
    }
    // Фильтр применяется к активному проекту — открываем тот, где совпадений больше
    const best = res.projects.slice().sort((a, b) => b.segments.length - a.segments.length)[0];
    const active = store.activeProject;
    const pick = (active && res.projects.find(x => x.id === active.id)) || best;
    if (!active || active.id !== pick.id) store.openProject(pick.id);
    store.setSegmentFilter(pick.segments);
    store.go("editor");
    toast.info("Показаны сегменты с термином", "«" + term.src + "» — " + pick.segments.length
      + " сегм." + (pick.violating.length ? " · перевод расходится с глоссарием: " + pick.violating.length : ""));
  };

  const confMeta = { high: ["badge-confirmed", "Высокая"], medium: ["badge-review", "Средняя"], low: ["badge-failed", "Низкая"] };

  return React.createElement("div", { className: "page page-wide" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Глоссарий",
        React.createElement(InfoTip, { title: "Глоссарий", body: "База утверждённых медицинских терминов с переводами. Используется для инъекции в GPT-промпт и проверки консистентности в QA." })),
      React.createElement("p", { className: "lead" }, "Утверждённая медицинская терминология. Совпадения автоматически подсказываются в редакторе сегментов.")),

    React.createElement(TermQueue, { store, toast }),

    React.createElement("div", { className: "row between row-wrap", style: { marginBottom: 16, gap: 12 } },
      React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value),
        placeholder: scope === "src" ? "Поиск по термину (RU)…" : scope === "tgt" ? "Поиск по переводу (EN)…" : "Поиск по глоссарию…" }),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(ScopeSelect, { value: scope, onChange: (e) => setScope(e.target.value) }),
        React.createElement(Select, { value: cat, onChange: (e) => setCat(e.target.value), style: { width: "auto" } },
          cats.map(c => React.createElement("option", { key: c, value: c }, c === "all" ? "Все категории" : c))),
        React.createElement(Select, { value: sort, onChange: (e) => setSort(e.target.value), style: { width: "auto" } },
          React.createElement("option", { value: "freq" }, "По частоте"),
          React.createElement("option", { value: "alpha" }, "По алфавиту")),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "download" }, "TSV"),
        React.createElement(Btn, { variant: "primary", size: "sm", icon: "plus", onClick: () => setModal("add") }, "Термин")
      )
    ),

    React.createElement("div", { className: "table-wrap" },
      React.createElement("div", { className: "tbl-scroll" },
        React.createElement("table", { className: "tbl" },
          React.createElement("thead", null, React.createElement("tr", null,
            React.createElement("th", null, "Термин (RU)"), React.createElement("th", null, "Перевод (EN)"),
            React.createElement("th", { style: { width: 150 } }, "Категория", React.createElement(InfoTip, { title: "Категория", body: "Anatomy (анатомия), Dosage (дозировки), Disease (заболевания), Device (медтехника), Procedure (процедуры) и др." })),
            React.createElement("th", { style: { width: 120 } }, "Частота", React.createElement(InfoTip, { title: "Частота", body: "Сколько раз термин встречался в проектах." })),
            React.createElement("th", { style: { width: 150 } }, "Достоверность", React.createElement(InfoTip, { title: "Уверенность", body: "High — проверен экспертом, Medium — авто-извлечён, Low — требует проверки." })), React.createElement("th", { style: { width: 96 } }, ""))),
          React.createElement("tbody", null,
            pageRows.map((g, i) => { const [cls, lab] = confMeta[(g.conf || "").toLowerCase()] || confMeta.medium;
              return React.createElement("tr", { key: i, onClick: () => setModal(g) },
                React.createElement("td", { style: { fontWeight: 600 } },
                  React.createElement("button", {
                    className: "linklike", onClick: (e) => openUsage(g, e),
                    title: "Показать сегменты, где встречается этот термин" }, g.src)),
                React.createElement("td", { style: { color: "var(--c-primary)", fontWeight: 500 } }, g.tgt,
                  // auto = массовый автоимпорт: модель получает такую запись подсказкой, а не правилом
                  g.tier === "auto" && React.createElement("span", { className: "dim", style: { fontSize: 11, marginLeft: 8, whiteSpace: "nowrap" },
                    title: "Автоимпорт, не проверено человеком. В промпт уходит подсказкой, а не жёстким правилом." }, "авто")),
                React.createElement("td", null, React.createElement(Badge, { variant: "soft" }, g.cat)),
                React.createElement("td", { className: "tnum dim" }, g.freq + "×"),
                React.createElement("td", null, React.createElement("span", { className: "badge " + cls }, lab)),
                React.createElement("td", { onClick: (e) => e.stopPropagation() },
                  React.createElement("div", { className: "row", style: { gap: 2 } },
                    React.createElement(IconBtn, { icon: "edit", label: "Редактировать", sm: true, onClick: () => setModal(g) }),
                    React.createElement(IconBtn, { icon: "trash", label: "Удалить", sm: true, onClick: () => del(g) }))));
            })
          )
        )
      )
    ),
    React.createElement("div", { className: "row between", style: { marginTop: 12 } },
      React.createElement("span", { className: "dim", style: { fontSize: 13 } },
        loaded ? ("Показано " + pageRows.length + " из " + rows.length + " (всего " + allTerms.length + ")") : "Загрузка…"),
      totalPages > 1 && React.createElement("div", { className: "row", style: { gap: 6 } },
        React.createElement(Btn, { variant: "ghost", size: "sm", disabled: page === 0, onClick: () => setPage(p => p - 1) }, "←"),
        React.createElement("span", { className: "dim", style: { fontSize: 13, padding: "0 4px" } }, (page + 1) + " / " + totalPages),
        React.createElement(Btn, { variant: "ghost", size: "sm", disabled: page >= totalPages - 1, onClick: () => setPage(p => p + 1) }, "→")
      )
    ),

    modal && React.createElement(TermModal, { term: modal === "add" ? null : modal, onClose: () => setModal(null), onSave: save })
  );
}

// Примеры употребления прямо в карточке: без них правка термина делается вслепую.
// Предпросмотр — механическая замена старого варианта на новый в готовом переводе,
// поэтому подписан именно как предпросмотр, а не как перевод.
function TermUsage({ src, oldTgt, newTgt }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let dead = false;
    if (!src || !window.API) { setData({ total: 0, examples: [] }); return; }
    window.API.safeCall(() => window.API.glossaryUsage(src, 4)).then(r => {
      if (!dead) setData(r || { total: 0, examples: [] });
    });
    return () => { dead = true; };
  }, [src]);

  if (!data) return React.createElement("div", { className: "row", style: { gap: 8 } },
    React.createElement(Spinner, null),
    React.createElement("span", { className: "dim", style: { fontSize: 13 } }, "Ищем примеры…"));
  if (!data.total) return React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } },
    "В переведённых сегментах этот термин пока не встречается.");

  const replaced = (text) => {
    if (!oldTgt || !newTgt || oldTgt === newTgt) return null;
    const i = (text || "").toLowerCase().indexOf(oldTgt.toLowerCase());
    if (i === -1) return null;
    return text.slice(0, i) + newTgt + text.slice(i + oldTgt.length);
  };

  return React.createElement("div", { className: "col", style: { gap: 10 } },
    React.createElement("div", { className: "dim", style: { fontSize: 12.5 } },
      "Встречается в " + data.total + " сегм."
      + (data.violatingTotal ? " · перевод расходится с глоссарием: " + data.violatingTotal : "")),
    data.examples.map((ex, i) => {
      const preview = replaced(ex.target);
      return React.createElement("div", { key: i, className: "card", style: { padding: "9px 11px", background: "var(--bg-sunken)", display: "flex", flexDirection: "column", gap: 4 } },
        React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
          "#" + ex.id + " · " + (ex.projectTitle || "проект " + ex.project)),
        React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, ex.source),
        ex.target
          ? React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5, color: "var(--c-primary)" } }, ex.target)
          : React.createElement("div", { className: "dim", style: { fontSize: 12.5, fontStyle: "italic" } }, "— не переведено —"),
        preview && React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5, color: "var(--c-success)" } },
          "→ " + preview),
        ex.target && !preview && oldTgt !== newTgt && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
          "прежний вариант «" + oldTgt + "» в этом переводе не найден — сегмент нужно переперевести"));
    })
  );
}

function TermModal({ term, onClose, onSave }) {
  const [src, setSrc] = useState(term ? term.src : "");
  const [tgt, setTgt] = useState(term ? term.tgt : "");
  const [cat, setCat] = useState(term ? term.cat : "Disease");
  const [note, setNote] = useState(term ? term.note : "");
  const [conf, setConf] = useState(term ? term.conf : "high");
  const cats = ["Anatomy", "Cardiology", "Disease", "Dosage", "Symptom", "Lab", "Vitals", "Regulatory", "Document", "Device"];
  return React.createElement(Modal, {
    title: term ? "Редактировать термин" : "Новый термин", icon: "book", onClose,
    footer: React.createElement(React.Fragment, null,
      React.createElement(Btn, { variant: "ghost", onClick: onClose }, "Отмена"),
      React.createElement(Btn, { variant: "primary", icon: "check", disabled: !src || !tgt,
        onClick: () => onSave({ src, tgt, cat, note, conf, freq: term ? term.freq : 1 }, !term) }, "Сохранить"))
  },
    React.createElement("div", { className: "grid grid-2" },
      React.createElement(Field, { label: "Термин (русский)" }, React.createElement(Input, { value: src, onChange: (e) => setSrc(e.target.value), placeholder: "напр. стеноз" })),
      React.createElement(Field, { label: "Перевод (английский)" }, React.createElement(Input, { value: tgt, onChange: (e) => setTgt(e.target.value), placeholder: "e.g. stenosis" }))),
    React.createElement(Field, { label: "Категория" },
      React.createElement(Select, { value: cat, onChange: (e) => setCat(e.target.value) }, cats.map(c => React.createElement("option", { key: c, value: c }, c)))),
    React.createElement(Field, { label: "Примечание (необязательно)" },
      React.createElement(Textarea, { value: note, onChange: (e) => setNote(e.target.value), placeholder: "Контекст использования, предпочтительные варианты…", style: { minHeight: 70 } })),
    term && term.src && React.createElement(Field, { label: "Где используется",
      hint: "Зелёным — как будет выглядеть перевод после замены" },
      React.createElement(TermUsage, { src: term.src, oldTgt: (term.tgt || ""), newTgt: tgt })),
    React.createElement(Field, { label: "Достоверность" },
      React.createElement("div", { className: "row", style: { gap: 18 } },
        ["high", "medium", "low"].map(c => React.createElement(Radio, { key: c, name: "conf", checked: conf === c, onChange: () => setConf(c) },
          { high: "Высокая", medium: "Средняя", low: "Низкая" }[c]))))
  );
}
window.TabGlossary = TabGlossary;

/* ============================================================
   Tab: TM — translation memory
   ============================================================ */
function TabTM({ store, toast }) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [quality, setQuality] = useState("all");
  const tmQuality = (t) => t.quality || (t.verified === true ? "verified" : t.verified === false ? "draft" : "draft");
  const rows = store.tm.filter(t => {
    const q2 = tmQuality(t);
    if (quality !== "all" && q2 !== quality) return false;
    if (query && !pairMatches(t, query, scope)) return false;
    return true;
  });
  return React.createElement("div", { className: "page page-wide" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Память переводов",
        React.createElement(InfoTip, { title: "Память переводов (TM)", body: "База подтверждённых пар (оригинал → перевод). Используется для поиска точных и нечётких совпадений в новых проектах. Экономит токены." })),
      React.createElement("p", { className: "lead" }, "Подтверждённые пары из предыдущих проектов. Точные совпадения подставляются автоматически и не тарифицируются.")),
    React.createElement("div", { className: "row between row-wrap", style: { marginBottom: 18, gap: 12 } },
      React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value),
        placeholder: scope === "src" ? "Поиск по оригиналу (RU)…" : scope === "tgt" ? "Поиск по переводу (EN)…" : "Поиск в памяти переводов…" }),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(ScopeSelect, { value: scope, onChange: (e) => setScope(e.target.value) }),
        React.createElement(Select, { value: quality, onChange: (e) => setQuality(e.target.value), style: { width: "auto" } },
          React.createElement("option", { value: "all" }, "Любое качество"),
          React.createElement("option", { value: "verified" }, "Проверенные"),
          React.createElement("option", { value: "draft" }, "Черновые")),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "upload" }, "Импорт TMX"),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "download" }, "Экспорт TMX"))),
    React.createElement("div", { className: "grid grid-2" },
      rows.map((t, i) => React.createElement("div", { key: i, className: "card card-pad card-hover", style: { display: "flex", flexDirection: "column", gap: 12 } },
        React.createElement("div", { className: "row between" },
          tmQuality(t) === "verified"
            ? React.createElement(Badge, { variant: "confirmed", icon: "checkCircle" }, "Проверено")
            : React.createElement(Badge, { variant: "review", icon: "warn" }, "Черновик"),
          React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "Использовано " + t.used + "×")),
        React.createElement("div", { style: { fontSize: 14, lineHeight: 1.5 } }, t.src),
        React.createElement("div", { className: "divider", style: { margin: "0" } }),
        React.createElement("div", { style: { fontSize: 14, lineHeight: 1.5, color: "var(--c-primary)" } }, t.tgt),
        React.createElement("div", { className: "row between", style: { marginTop: 2 } },
          React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "Создано " + t.created),
          React.createElement("div", { className: "row", style: { gap: 2 } },
            React.createElement(IconBtn, { icon: "copy", label: "Копировать", sm: true, onClick: () => { navigator.clipboard && navigator.clipboard.writeText(t.tgt); toast.info("Скопировано"); } }),
            React.createElement(IconBtn, { icon: "edit", label: "Редактировать", sm: true }),
            React.createElement(IconBtn, { icon: "trash", label: "Удалить", sm: true, onClick: () => { store.deleteTM(t); toast.warning("Запись удалена"); } })))
      ))
    )
  );
}
window.TabTM = TabTM;
