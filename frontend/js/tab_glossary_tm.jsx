/* ============================================================
   Tab: Glossary — medical terminology management
   ============================================================ */
function TabGlossary({ store, toast }) {
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState("all");
  const [sort, setSort] = useState("freq");
  const [modal, setModal] = useState(null); // null | 'add' | term object

  const cats = ["all", ...Array.from(new Set(store.glossary.map(g => g.cat)))];
  let rows = store.glossary.filter(g => {
    if (cat !== "all" && g.cat !== cat) return false;
    if (query) { const q = query.toLowerCase(); if (!g.src.toLowerCase().includes(q) && !g.tgt.toLowerCase().includes(q)) return false; }
    return true;
  });
  rows = rows.slice().sort((a, b) => sort === "freq" ? b.freq - a.freq : a.src.localeCompare(b.src, "ru"));

  const save = (term, isNew) => {
    store.saveTerm(term, isNew);
    setModal(null);
    toast.success(isNew ? "Термин добавлен" : "Термин обновлён", term.src + " → " + term.tgt);
  };
  const del = (term) => { store.deleteTerm(term); toast.warning("Термин удалён", term.src); };

  const confMeta = { high: ["badge-confirmed", "Высокая"], medium: ["badge-review", "Средняя"], low: ["badge-failed", "Низкая"] };

  return React.createElement("div", { className: "page page-wide" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Глоссарий",
        React.createElement(InfoTip, { title: "Глоссарий", body: "База утверждённых медицинских терминов с переводами. Используется для инъекции в GPT-промпт и проверки консистентности в QA." })),
      React.createElement("p", { className: "lead" }, "Утверждённая медицинская терминология. Совпадения автоматически подсказываются в редакторе сегментов.")),

    React.createElement("div", { className: "row between row-wrap", style: { marginBottom: 16, gap: 12 } },
      React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Поиск по глоссарию…" }),
      React.createElement("div", { className: "row", style: { gap: 8 } },
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
            rows.map((g, i) => { const [cls, lab] = confMeta[g.conf];
              return React.createElement("tr", { key: i, onClick: () => setModal(g) },
                React.createElement("td", { style: { fontWeight: 600 } }, g.src),
                React.createElement("td", { style: { color: "var(--c-primary)", fontWeight: 500 } }, g.tgt),
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
    React.createElement("div", { className: "dim", style: { marginTop: 12, fontSize: 13 } }, "Показано " + rows.length + " из " + store.glossary.length + " терминов"),

    modal && React.createElement(TermModal, { term: modal === "add" ? null : modal, onClose: () => setModal(null), onSave: save })
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
  const [quality, setQuality] = useState("all");
  const rows = store.tm.filter(t => {
    if (quality !== "all" && t.quality !== quality) return false;
    if (query) { const q = query.toLowerCase(); if (!t.src.toLowerCase().includes(q) && !t.tgt.toLowerCase().includes(q)) return false; }
    return true;
  });
  return React.createElement("div", { className: "page page-wide" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Память переводов",
        React.createElement(InfoTip, { title: "Память переводов (TM)", body: "База подтверждённых пар (оригинал → перевод). Используется для поиска точных и нечётких совпадений в новых проектах. Экономит токены." })),
      React.createElement("p", { className: "lead" }, "Подтверждённые пары из предыдущих проектов. Точные совпадения подставляются автоматически и не тарифицируются.")),
    React.createElement("div", { className: "row between row-wrap", style: { marginBottom: 18, gap: 12 } },
      React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Поиск в памяти переводов…" }),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Select, { value: quality, onChange: (e) => setQuality(e.target.value), style: { width: "auto" } },
          React.createElement("option", { value: "all" }, "Любое качество"),
          React.createElement("option", { value: "verified" }, "Проверенные"),
          React.createElement("option", { value: "draft" }, "Черновые")),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "upload" }, "Импорт TMX"),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "download" }, "Экспорт TMX"))),
    React.createElement("div", { className: "grid grid-2" },
      rows.map((t, i) => React.createElement("div", { key: i, className: "card card-pad card-hover", style: { display: "flex", flexDirection: "column", gap: 12 } },
        React.createElement("div", { className: "row between" },
          t.quality === "verified"
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
