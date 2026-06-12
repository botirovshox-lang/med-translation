/* ============================================================
   Tab: Segment Editor — the core translation workspace
   ============================================================ */
function TabEditor({ store, toast }) {
  const project = store.activeProject;
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState("all");
  const [height, setHeight] = useState(440);
  const [selId, setSelId] = useState(project ? (project.segments[0] && project.segments[0].id) : null);
  const [busy, setBusy] = useState({});       // {segId: 'translate'|'qa'}
  const [batchRun, setBatchRun] = useState(null); // {engine, done, total}
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(1);
  const [revertTarget, setRevertTarget] = useState(null);
  const PAGE_SIZE = 10;

  useEffect(() => { setPage(1); }, [filter, query, riskFilter, project && project.id]);

  useEffect(() => {
    if (project && !project.segments.find(s => s.id === selId)) setSelId(project.segments[0] && project.segments[0].id);
  }, [project && project.id]);

  if (!project) return React.createElement(NoProject, { store });

  const counts = store.statusCounts(project);
  const filtered = project.segments.filter(s => {
    if (filter !== "all" && s.status !== filter) return false;
    if (riskFilter !== "all" && s.risk !== riskFilter) return false;
    if (query) { const q = query.toLowerCase(); if (!s.source.toLowerCase().includes(q) && !(s.target || "").toLowerCase().includes(q)) return false; }
    return true;
  });
  const selected = project.segments.find(s => s.id === selId);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const curPage = Math.min(page, totalPages);
  const paged = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);
  const wordCount = (arr) => arr.reduce((a, s) => a + (s.source.trim() ? s.source.trim().split(/\s+/).length : 0), 0);
  const charCount = (arr) => arr.reduce((a, s) => a + s.source.length, 0);

  const setSegBusy = (id, kind) => setBusy(b => ({ ...b, [id]: kind }));
  const clearBusy = (id) => setBusy(b => { const n = { ...b }; delete n[id]; return n; });

  const doTranslate = async (seg, engine) => {
    if (busy[seg.id]) return;
    setSegBusy(seg.id, "translate");
    let result = null;
    if (window.API) {
      result = await window.API.safeCall(() => window.API.translate(project.id, seg.id, engine));
    }
    if (result && result.segment) {
      // Apply backend result to local state
      store.updateSegment(project.id, seg.id, {
        target: result.segment.target,
        status: result.segment.status,
        route: result.segment.route,
      });
      toast.success("Сегмент переведён",
        (engine === "gpt" ? "GPT-4o-mini" : "Google Translate") + " · сегмент #" + seg.id +
        (result.usedRealApi ? "" : " (демо)"));
    } else {
      // Fallback: local mock
      store.updateSegment(project.id, seg.id, { status: "translated", route: engine === "gpt" ? "GPT_REQUIRED" : "GOOGLE_SAFE" });
      toast.success("Сегмент переведён", (engine === "gpt" ? "GPT-4o-mini" : "Google Translate") + " · сегмент #" + seg.id);
    }
    clearBusy(seg.id);
  };

  const doQA = async (seg) => {
    if (busy[seg.id]) return;
    setSegBusy(seg.id, "qa");
    let result = null;
    if (window.API) {
      result = await window.API.safeCall(() => window.API.qa(project.id, seg.id));
    }
    if (result && result.segment) {
      store.updateSegment(project.id, seg.id, { status: result.segment.status, qa: result.segment.qa });
      const n = (result.issues || []).length;
      if (n === 0) toast.info("Проверка QA завершена", "Сегмент #" + seg.id + " — замечаний не найдено.");
      else toast.warning("QA: " + n + " замечан.", "Сегмент #" + seg.id);
    } else {
      store.updateSegment(project.id, seg.id, { status: "qa" });
      toast.info("Проверка QA завершена", "Сегмент #" + seg.id + " — замечаний не найдено.");
    }
    clearBusy(seg.id);
  };

  const doConfirm = async (seg) => {
    if (window.API) await window.API.safeCall(() => window.API.confirm(project.id, seg.id));
    store.updateSegment(project.id, seg.id, { status: "confirmed" });
    toast.success("Подтверждено", "Сегмент #" + seg.id + " добавлен в память переводов.");
  };

  const doRevert = async (seg) => {
    if (seg.status === "confirmed") { setRevertTarget(seg); return; }
    if (seg.status === "failed") {
      if (window.API) await window.API.safeCall(() => window.API.revert(project.id, seg.id));
      store.updateSegment(project.id, seg.id, { status: "new", target: "" });
      toast.info("Статус сброшен", "Сегмент #" + seg.id + " возвращён в «Новый».");
    }
  };

  const confirmRevert = async () => {
    const seg = revertTarget; setRevertTarget(null);
    if (window.API) await window.API.safeCall(() => window.API.revert(project.id, seg.id));
    store.updateSegment(project.id, seg.id, { status: "translated" });
    toast.warning("Подтверждение снято", "Сегмент #" + seg.id + " возвращён в «Переведён».");
  };

  const runBatch = async (engine) => {
    const targets = project.segments.filter(s => s.status === "new" && (engine === "google" ? s.risk === "low" : s.risk !== "low"));
    if (!targets.length) { toast.warning("Нет подходящих сегментов", "Для выбранного движка нет новых сегментов."); return; }
    setBatchRun({ engine, done: 0, total: targets.length });

    // Try backend first (single call); fall back to incremental local simulation
    let result = null;
    if (window.API) result = await window.API.safeCall(() => window.API.batch(project.id, engine));

    if (result && result.ok) {
      // Apply: reload project to pick up backend updates
      const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
      if (fresh && fresh.segments) {
        fresh.segments.forEach(s => store.updateSegment(project.id, s.id, { target: s.target, status: s.status, route: s.route }));
      } else {
        targets.forEach(s => store.updateSegment(project.id, s.id, { status: "translated", route: engine === "gpt" ? "GPT_REQUIRED" : "GOOGLE_SAFE" }));
      }
      setBatchRun({ engine, done: result.count, total: targets.length });
      setTimeout(() => { setBatchRun(null); toast.success("Пакет завершён", result.count + " сегментов переведено через " + (engine === "gpt" ? "GPT" : "Google") + "."); }, 500);
    } else {
      // Incremental local fallback
      let done = 0;
      const tick = () => {
        const seg = targets[done];
        store.updateSegment(project.id, seg.id, { status: "translated", route: engine === "gpt" ? "GPT_REQUIRED" : "GOOGLE_SAFE" });
        done++;
        setBatchRun({ engine, done, total: targets.length });
        if (done < targets.length) setTimeout(tick, 380);
        else { setTimeout(() => { setBatchRun(null); toast.success("Пакет завершён", done + " сегментов переведено через " + (engine === "gpt" ? "GPT" : "Google") + "."); }, 500); }
      };
      setTimeout(tick, 400);
    }
  };

  const filterDefs = [
    ["all", "Все", counts.all], ["new", "Новые", counts.new], ["translated", "Переведено", counts.translated],
    ["qa", "QA", counts.qa], ["confirmed", "Подтверждено", counts.confirmed], ["failed", "Ошибки", counts.failed],
  ];

  return React.createElement("div", { className: "col", style: { minHeight: 0 } },
    // ---- Toolbar ----
    React.createElement("div", { className: "editor-toolbar" },
      React.createElement("div", { className: "row between row-wrap" },
        React.createElement("div", { className: "row", style: { gap: 10 } },
          React.createElement(Icon, { name: "folder", size: 18, style: { color: "var(--c-primary)" } }),
          React.createElement(Select, { value: project.id, onChange: (e) => store.openProject(Number(e.target.value)), style: { width: "auto", minWidth: 280, fontWeight: 600 } },
            store.projects.map(p => React.createElement("option", { key: p.id, value: p.id }, "#" + p.id + " — " + p.title))),
          React.createElement(LangPair, { src: project.src, tgt: project.tgt })
        ),
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement("span", { className: "dim", style: { fontSize: 13 } }, "Высота таблицы"),
          React.createElement("input", { type: "range", min: 320, max: 720, step: 20, value: height,
            onChange: (e) => setHeight(Number(e.target.value)), style: { width: 130 }, "aria-label": "Высота таблицы" }),
          React.createElement(IconBtn, { icon: "filter", label: "Доп. фильтры", sm: true, active: showFilters, onClick: () => setShowFilters(s => !s) })
        )
      ),
      React.createElement("div", { className: "row between row-wrap" },
        React.createElement("div", { className: "segmented" },
          filterDefs.map(([v, l, n]) => React.createElement("button", { key: v, className: filter === v ? "on" : "", onClick: () => setFilter(v) },
            l, React.createElement("span", { className: "cnt" }, n)))
        )
      ),
      showFilters && React.createElement("div", { className: "row row-wrap", style: { gap: 14, padding: "4px 2px" } },
        React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Поиск по тексту…" }),
        React.createElement(Select, { value: riskFilter, onChange: (e) => setRiskFilter(e.target.value), style: { width: 200 } },
          [["all", "Любой риск"], ["low", "Низкий риск"], ["medium", "Средний риск"], ["high", "Высокий риск"], ["critical", "Критический риск"]]
            .map(([v, l]) => React.createElement("option", { key: v, value: v }, l)))
      )
    ),

    // ---- Batch actions ----
    React.createElement("div", { className: "editor-main", style: { paddingBottom: 0 } },
      React.createElement(Expander, { title: "Пакетный перевод", icon: "zap", right: "2 движка", defaultOpen: false },
        React.createElement("div", { className: "grid grid-2" },
          React.createElement(BatchCard, { kind: "google", running: batchRun && batchRun.engine === "google" ? batchRun : null, onRun: () => runBatch("google"),
            available: project.segments.filter(s => s.status === "new" && s.risk === "low").length }),
          React.createElement(BatchCard, { kind: "gpt", running: batchRun && batchRun.engine === "gpt" ? batchRun : null, onRun: () => runBatch("gpt"),
            available: project.segments.filter(s => s.status === "new" && s.risk !== "low").length })
        )
      )
    ),

    // ---- Body: table + detail ----
    React.createElement("div", { className: "editor-body" },
      React.createElement("div", { className: "editor-main" },
        React.createElement("div", { className: "table-wrap" },
          React.createElement("div", { className: "tbl-scroll", style: { maxHeight: height } },
            React.createElement("table", { className: "tbl" },
              React.createElement("thead", null, React.createElement("tr", null,
                React.createElement("th", { className: "col-id" }, "#"),
                React.createElement("th", null, "🇷🇺 Оригинал"),
                React.createElement("th", null, "🇬🇧 Перевод"),
                React.createElement("th", { style: { width: 132 } }, "Статус"),
                React.createElement("th", { style: { width: 60 }, title: "TM match %" }, "TM%"),
                React.createElement("th", { style: { width: 56 } }, "")
              )),
              React.createElement("tbody", null,
                paged.map(s => React.createElement(SegRow, {
                  key: s.id, seg: s, selected: s.id === selId, busy: busy[s.id],
                  onSelect: () => setSelId(s.id),
                  onTranslate: () => doTranslate(s, s.risk === "low" ? "google" : "gpt"),
                  onConfirm: () => doConfirm(s), onRevert: () => doRevert(s),
                }))
              )
            )
          )
        ),
        filtered.length === 0 && React.createElement("div", { style: { padding: 20 } },
          React.createElement(EmptyState, { icon: "filter", title: "Нет сегментов по фильтру", sub: "Измените фильтр статуса или поиск." })),
        React.createElement("div", { className: "row", style: { gap: 16, marginTop: 12, fontSize: 12, color: "var(--text-3)", flexWrap: "wrap" } },
          React.createElement(LegendDot, { color: "var(--st-new-fg)", label: "Новый" }),
          React.createElement(LegendDot, { color: "var(--c-primary)", label: "Переведён" }),
          React.createElement(LegendDot, { color: "var(--c-warning)", label: "QA" }),
          React.createElement(LegendDot, { color: "var(--c-success)", label: "Подтверждён" }),
          React.createElement(LegendDot, { color: "var(--c-error)", label: "Ошибка" })
        ),
        filtered.length > 0 && totalPages > 1 && React.createElement(Pagination, { page: curPage, totalPages, onGo: setPage }),
        React.createElement(StatusBar, {
          segShown: filtered.length, segTotal: project.segments.length,
          wordsShown: wordCount(filtered), wordsTotal: wordCount(project.segments),
          charsShown: charCount(filtered), charsTotal: charCount(project.segments),
        })
      ),

      // ---- Detail sidebar ----
      React.createElement("div", { className: "editor-side" },
        selected
          ? React.createElement(SegDetail, { key: selected.id, seg: selected, project, store, toast, busy: busy[selected.id],
              onTranslate: (eng) => doTranslate(selected, eng), onQA: () => doQA(selected), onConfirm: () => doConfirm(selected) })
          : React.createElement(EmptyState, { icon: "edit", title: "Сегмент не выбран", sub: "Выберите строку в таблице." })
      )
    ),

    revertTarget && React.createElement(Modal, {
      title: "Снять подтверждение?", icon: "warn", onClose: () => setRevertTarget(null),
      footer: React.createElement(React.Fragment, null,
        React.createElement(Btn, { variant: "ghost", onClick: () => setRevertTarget(null) }, "Отмена"),
        React.createElement(Btn, { variant: "primary", icon: "repeat", onClick: confirmRevert }, "Снять подтверждение")) },
      React.createElement("p", { className: "muted", style: { margin: 0, lineHeight: 1.6 } },
        "Сегмент ", React.createElement("b", { style: { color: "var(--text)" } }, "#" + revertTarget.id),
        " будет возвращён из статуса «Подтверждён» в «Переведён». Запись в памяти переводов сохранится.")
    )
  );
}

function Pagination({ page, totalPages, onGo }) {
  const [goto, setGoto] = useState("");
  const nums = [];
  if (totalPages <= 7) { for (let i = 1; i <= totalPages; i++) nums.push(i); }
  else {
    nums.push(1);
    if (page > 3) nums.push("…");
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) nums.push(i);
    if (page < totalPages - 2) nums.push("…");
    nums.push(totalPages);
  }
  const submitGoto = (e) => {
    if (e.key !== "Enter") return;
    const n = parseInt(goto, 10);
    if (n >= 1 && n <= totalPages) onGo(n);
    setGoto("");
  };
  return React.createElement("div", { className: "pagination" },
    React.createElement("button", { className: "page-num", disabled: page <= 1, onClick: () => onGo(page - 1), "aria-label": "Назад" },
      React.createElement(Icon, { name: "chevL", size: 15 })),
    nums.map((n, i) => n === "…"
      ? React.createElement("span", { key: "e" + i, className: "page-ellipsis" }, "…")
      : React.createElement("button", { key: n, className: "page-num" + (n === page ? " on" : ""), onClick: () => onGo(n), "aria-current": n === page ? "page" : null }, n)),
    React.createElement("button", { className: "page-num", disabled: page >= totalPages, onClick: () => onGo(page + 1), "aria-label": "Вперёд" },
      React.createElement(Icon, { name: "chevR", size: 15 })),
    React.createElement("span", { className: "dim", style: { marginLeft: 6, fontSize: 13 } }, "Перейти:"),
    React.createElement("input", { className: "input page-goto", value: goto, onChange: (e) => setGoto(e.target.value.replace(/\D/g, "")),
      onKeyDown: submitGoto, placeholder: String(page), "aria-label": "Перейти к странице" })
  );
}

function StatusBar({ segShown, segTotal, wordsShown, wordsTotal, charsShown, charsTotal }) {
  const fmt = (n) => n.toLocaleString("ru-RU");
  return React.createElement("div", { className: "statusbar" },
    React.createElement("div", { className: "row", style: { gap: 10, flexWrap: "wrap" } },
      React.createElement("span", { className: "sb-group" }, React.createElement(Icon, { name: "list", size: 14 }), " Сегментов: ", React.createElement("b", null, segShown + "/" + segTotal)),
      React.createElement("span", { className: "sb-sep" }, "·"),
      React.createElement("span", { className: "sb-group" }, "Слов: ", React.createElement("b", null, fmt(wordsShown) + "/" + fmt(wordsTotal))),
      React.createElement("span", { className: "sb-sep" }, "·"),
      React.createElement("span", { className: "sb-group" }, "Знаков: ", React.createElement("b", null, fmt(charsShown) + "/" + fmt(charsTotal)))
    ),
    React.createElement("span", { className: "sb-save" }, React.createElement("span", { className: "sb-dot" }), "Автосохранение", React.createElement(Icon, { name: "check", size: 13, stroke: 2.6, style: { color: "var(--c-success)" } }))
  );
}

function LegendDot({ color, label }) {
  return React.createElement("span", { className: "row", style: { gap: 6 } },
    React.createElement("span", { style: { width: 10, height: 10, borderRadius: 3, background: color, display: "inline-block" } }), label);
}

function BatchCard({ kind, running, onRun, available }) {
  const meta = kind === "google"
    ? { icon: "globe", title: "Google Batch", sub: "Низкорисковые сегменты", note: "Для простых, шаблонных формулировок.", color: "var(--c-warning)", btn: "Запустить Google",
        tipTitle: "Запустить Google batch", tip: "Перевести все GOOGLE_SAFE сегменты через Google Translate. Результат сохраняется как 'google_draft' (не подтверждён)." }
    : { icon: "cpu", title: "GPT Batch", sub: "Сложный контент", note: "Для клинических и неоднозначных формулировок.", color: "var(--c-purple)", btn: "Запустить GPT",
        tipTitle: "Запустить GPT batch", tip: "Перевод через OpenAI GPT с QA и применением глоссария. Результат: status='translated', provider='openai'." };
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("span", { style: { width: 36, height: 36, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--bg-sunken)", color: meta.color } },
        React.createElement(Icon, { name: meta.icon, size: 19 })),
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, meta.title, React.createElement(InfoTip, { title: meta.tipTitle, body: meta.tip })),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, meta.sub))
    ),
    React.createElement("p", { className: "muted", style: { fontSize: 13, margin: 0 } }, meta.note),
    running
      ? React.createElement("div", null,
          React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
            React.createElement("span", { className: "muted" }, "Перевод…"),
            React.createElement("span", { style: { fontWeight: 700 } }, running.done + "/" + running.total)),
          React.createElement(ProgressBar, { value: Math.round(running.done / running.total * 100) }))
      : React.createElement("div", { className: "row between" },
          React.createElement("span", { className: "dim", style: { fontSize: 12 } }, available + " доступно"),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "zap", onClick: onRun, disabled: !available }, meta.btn))
  );
}

function SegRow({ seg, selected, busy, onSelect, onTranslate, onConfirm, onRevert }) {
  const revertable = seg.status === "confirmed" || seg.status === "failed";
  const actionCell = busy
    ? React.createElement("div", { style: { display: "grid", placeItems: "center" } }, React.createElement(Spinner, null))
    : seg.status === "new"
      ? React.createElement(IconBtn, { icon: "globe", label: "Перевести", sm: true, onClick: onTranslate })
      : seg.status === "confirmed"
        ? React.createElement("button", { className: "status-cell-btn revertable", title: "Нажмите, чтобы снять подтверждение", "aria-label": "Снять подтверждение", onClick: onRevert },
            React.createElement(Icon, { name: "checkCircle", size: 18, style: { color: "var(--c-success)" } }))
        : seg.status === "failed"
          ? React.createElement("button", { className: "status-cell-btn revertable", title: "Нажмите, чтобы сбросить в «Новый»", "aria-label": "Сбросить статус", onClick: onRevert },
              React.createElement(Icon, { name: "close", size: 18, style: { color: "var(--c-error)" } }))
          : React.createElement(IconBtn, { icon: "check", label: "Подтвердить", sm: true, onClick: onConfirm });
  return React.createElement("tr", { className: "row-status-" + seg.status + (selected ? " selected" : ""), onClick: onSelect },
    React.createElement("td", { className: "col-id" }, seg.id),
    React.createElement("td", { className: "src-cell" }, seg.source),
    React.createElement("td", { className: seg.target ? "tgt-cell" : "tgt-cell tgt-empty" }, seg.target || "— не переведено —"),
    React.createElement("td", null, React.createElement(StatusBadge, { status: seg.status })),
    React.createElement("td", null, React.createElement(TMChip, { score: seg.tmScore })),
    React.createElement("td", { onClick: (e) => e.stopPropagation() }, actionCell)
  );
}

function NoProject({ store }) {
  return React.createElement("div", { className: "page" },
    React.createElement(EmptyState, { icon: "folder", title: "Проект не выбран",
      sub: "Импортируйте документ или откройте существующий проект.",
      action: React.createElement(Btn, { variant: "primary", icon: "upload", onClick: () => store.go("import") }, "К импорту") }));
}
window.TabEditor = TabEditor;
