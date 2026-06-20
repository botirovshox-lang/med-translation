/* ============================================================
   Tab: QA Dashboard
   ============================================================ */
function TabQA({ store, toast }) {
  const project = store.activeProject;
  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));

  const issueText = (it) => {
    const desc = it.explanation_ru || it.msg || "QA issue";
    const fragment = it.bad_fragment || it.target_fragment || it.source_fragment || "";
    const suggestion = it.suggested_fragment || "";
    return desc + (fragment ? " Фрагмент: " + fragment + "." : "") + (suggestion ? " → " + suggestion : "");
  };
  const issueSeverity = (it) => it.severity || it.sev || "medium";
  const openIssueSegments = project.segments
    .filter(s => s.status !== "confirmed")
    .map(s => {
      const sourceIssues = (s.qa_issues && s.qa_issues.length) ? s.qa_issues : (s.qa || []);
      return { seg: s, issues: sourceIssues };
    })
    .filter(row => row.issues.length > 0);
  const issues = [];
  openIssueSegments.forEach(row => {
    row.issues.forEach(q => issues.push({ ...q, seg: row.seg.id, risk_color: row.seg.risk_color, risk_score: row.seg.risk_score }));
  });
  const passed = project.segments.filter(s => s.status === "confirmed").length;
  const warnings = project.segments.filter(s => s.status === "qa" || s.status === "review").length;
  const failed = project.segments.filter(s => s.status === "failed").length;

  const structuralTypes = ["negation_shift", "laterality_shift", "upper_lower_shift", "inner_outer_shift", "anatomy_shift", "uncertainty_changed", "diagnosis_symptom_finding_changed"];
  const numericTypes = ["numeric", "number_unit_dosage_mismatch", "unit_mismatch"];
  const termTypes = ["terminology", "literal_calque", "glossary_violation", "forbidden_term", "weak_collocation"];
  const lengthTypes = ["length"];

  const getSegIds = (types) => [...new Set(issues.filter(i => types.includes(i.type)).map(i => i.seg))];

  const goCategory = (segIds) => {
    store.setSegmentFilter(segIds);
    store.go("editor");
  };

  const groups = [
    { icon: "file", title: "Структурные", segIds: getSegIds(structuralTypes), n: getSegIds(structuralTypes).length,
      desc: "Нарушения отрицания, стороны или ориентации.", tip: "Потеря отрицания, сдвиг лево/право, верх/низ, внутри/снаружи — критические смысловые ошибки." },
    { icon: "target", title: "Числовые ошибки", segIds: getSegIds(numericTypes), n: issues.filter(i => numericTypes.includes(i.type)).length,
      desc: "Несоответствие чисел или единиц измерения.", tip: "Несовпадение чисел, дозировок, единиц измерения между оригиналом и переводом (КРИТИЧНО для медицины)." },
    { icon: "book", title: "Терминология", segIds: getSegIds(termTypes), n: issues.filter(i => termTypes.includes(i.type)).length,
      desc: "Обнаружены нежелательные или нестандартные термины.", tip: "Использованы запрещённые термины или термины не из утверждённого глоссария." },
    { icon: "list", title: "Длина перевода", segIds: getSegIds(lengthTypes), n: issues.filter(i => lengthTypes.includes(i.type)).length,
      desc: "Перевод заметно длиннее или короче оригинала.", tip: "Перевод существенно длиннее/короче оригинала (>3×). Может указывать на пропуск или добавление информации." },
  ];
  const sevMeta = { critical: ["badge-failed", "Критично"], major: ["badge-qa", "Major"], high: ["badge-qa", "Высокий"], medium: ["badge-review", "Средний"], minor: ["badge-soft", "Minor"] };

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Контроль качества",
        React.createElement(InfoTip, { title: "Контроль качества (QA)", body: "6-этапный pipeline QA: локальные проверки (8) → консистентность → адаптивное планирование → проверка чисел → back-check → финальное решение." })),
      React.createElement("p", { className: "lead" }, "Открытые QA-замечания по неподтверждённым сегментам. После подтверждения сегмент исчезает из этого списка.")),

    React.createElement("div", { className: "grid grid-3 section" },
      React.createElement(QAStat, { icon: "checkCircle", color: "var(--c-success)", n: passed, label: "Прошли QA" }),
      React.createElement(QAStat, { icon: "warn", color: "var(--c-warning)", n: warnings, label: "Предупреждения" }),
      React.createElement(QAStat, { icon: "alert", color: "var(--c-error)", n: failed, label: "Ошибки" })),

    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Категории замечаний"),
      React.createElement("div", { className: "grid grid-2" },
        groups.map((g, i) => {
          const clickable = g.segIds.length > 0;
          return React.createElement("div", {
            key: i,
            className: "card card-pad row between card-hover",
            style: clickable ? { cursor: "pointer" } : {},
            onClick: clickable ? () => goCategory(g.segIds) : undefined,
            title: clickable ? "Открыть " + g.segIds.length + " сегм. в редакторе" : undefined,
          },
            React.createElement("div", { className: "row", style: { gap: 12 } },
              React.createElement("span", { style: { width: 40, height: 40, borderRadius: 10, background: "var(--bg-sunken)", color: "var(--c-primary)", display: "grid", placeItems: "center" } },
                React.createElement(Icon, { name: g.icon, size: 19 })),
              React.createElement("div", null,
                React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, g.title, React.createElement(InfoTip, { title: g.title, body: g.tip })),
                React.createElement("div", { className: "dim", style: { fontSize: 13, maxWidth: 280 } }, g.desc))),
            React.createElement("span", { className: "badge " + (g.n ? "badge-qa" : "badge-confirmed") }, g.n));
        }))),

    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "QA редактор"),
      openIssueSegments.length
        ? React.createElement("div", { className: "table-wrap" }, React.createElement("table", { className: "tbl" },
            React.createElement("thead", null, React.createElement("tr", null,
              React.createElement("th", { className: "col-id" }, "#"),
              React.createElement("th", null, "RU Оригинал"),
              React.createElement("th", null, "GB Перевод"),
              React.createElement("th", { style: { width: 132 } }, "Статус"),
              React.createElement("th", { style: { width: 360 } }, "QA комментарий"),
              React.createElement("th", { style: { width: 96 } }, ""))),
            React.createElement("tbody", null, openIssueSegments.map(row => {
              const s = row.seg;
              const topIssue = row.issues[0] || {};
              const [cls, lab] = sevMeta[issueSeverity(topIssue)] || sevMeta.medium;
              return React.createElement("tr", { key: s.id, className: "row-status-" + s.status, style: { cursor: "pointer" }, onClick: () => store.goToSegment(s.id) },
                React.createElement("td", { className: "col-id" }, s.id),
                React.createElement("td", { className: "src-cell" }, s.source),
                React.createElement("td", { className: s.target ? "tgt-cell" : "tgt-cell tgt-empty" }, s.target || "— не переведено —"),
                React.createElement("td", null, React.createElement(StatusBadge, { status: s.status })),
                React.createElement("td", { style: { lineHeight: 1.5 } },
                  React.createElement("div", { className: "row", style: { gap: 8, marginBottom: 6, flexWrap: "wrap" } },
                    React.createElement("span", { className: "badge " + cls }, lab),
                    React.createElement("span", { className: "dim", style: { fontSize: 12 } }, row.issues.length + " замеч."))
                  ,
                  row.issues.slice(0, 3).map((it, i) => React.createElement("div", { key: i, style: { marginTop: i ? 6 : 0 } },
                    React.createElement("span", { className: "dim" }, (it.type || "qa") + ": "),
                    issueText(it)
                  )),
                  row.issues.length > 3 && React.createElement("div", { className: "dim", style: { marginTop: 6 } }, "Ещё " + (row.issues.length - 3) + " замеч."))
                ,
                React.createElement("td", { onClick: (e) => e.stopPropagation() },
                  React.createElement(Btn, { variant: "secondary", size: "sm", icon: "edit",
                    onClick: () => store.goToSegment(s.id)
                  }, "Исправить")));
            }))))
        : React.createElement(EmptyState, { icon: "checkCircle", title: "Замечаний не найдено", sub: "Все проверенные сегменты соответствуют требованиям." })
    )
  );
}
function QAStat({ icon, color, n, label }) {
  return React.createElement("div", { className: "card card-pad row", style: { gap: 16 } },
    React.createElement("span", { style: { width: 52, height: 52, borderRadius: 13, background: "var(--bg-sunken)", color, display: "grid", placeItems: "center" } },
      React.createElement(Icon, { name: icon, size: 26 })),
    React.createElement("div", null,
      React.createElement("div", { style: { fontSize: 30, fontWeight: 750, lineHeight: 1, letterSpacing: "-1px" } }, n),
      React.createElement("div", { className: "muted", style: { fontSize: 14, marginTop: 4 } }, label)));
}
window.TabQA = TabQA;

/* ============================================================
   Tab: Backlog — kanban task board
   ============================================================ */
function TabBacklog({ store, toast }) {
  const project = store.activeProject;
  const [view, setView] = useState("board");
  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));

  const cols = [
    { key: "new", title: "Новые", icon: "file" },
    { key: "translated", title: "В работе", icon: "globe" },
    { key: "qa", title: "На проверке", icon: "shield" },
    { key: "confirmed", title: "Готово", icon: "checkCircle" },
  ];
  const prio = (s) => s.risk === "critical" ? "urgent" : s.risk === "high" ? "high" : s.risk === "medium" ? "medium" : "low";
  const prioLabel = { urgent: "Срочно", high: "Высокий", medium: "Средний", low: "Низкий" };
  const team = store.team;

  return React.createElement("div", { className: "page page-wide" },
    React.createElement("div", { className: "row between page-head", style: { alignItems: "flex-end" } },
      React.createElement("div", null,
        React.createElement("h1", null, "Бэклог",
          React.createElement(InfoTip, { title: "Бэклог задач", body: "Список сегментов, требующих внимания: HIGH/CRITICAL риск, failed QA, неконсистентная терминология. Приоритизация: CRITICAL > численные > семантические > глоссарий." })),
        React.createElement("p", { className: "lead", style: { marginBottom: 0 } }, "Задачи перевода по статусам. Перетаскивайте карточки между колонками.")),
      React.createElement("div", { className: "segmented" },
        React.createElement("button", { className: view === "board" ? "on" : "", onClick: () => setView("board") }, React.createElement(Icon, { name: "columns", size: 15 }), "Доска"),
        React.createElement("button", { className: view === "list" ? "on" : "", onClick: () => setView("list") }, React.createElement(Icon, { name: "list", size: 15 }), "Список"))),

    React.createElement("div", { className: "kanban" },
      cols.map(col => {
        const items = project.segments.filter(s => s.status === col.key || (col.key === "translated" && s.status === "review"));
        return React.createElement("div", { className: "kcol", key: col.key },
          React.createElement("div", { className: "kcol-head" },
            React.createElement("span", { className: "row", style: { gap: 8 } }, React.createElement(Icon, { name: col.icon, size: 16, style: { color: "var(--text-3)" } }), col.title),
            React.createElement("span", { className: "badge badge-soft" }, items.length)),
          items.map(s => { const p = prio(s); const member = team[s.id % team.length];
            return React.createElement("div", { className: "kcard", key: s.id, onClick: () => { store.go("editor"); } },
              React.createElement("div", { className: "row between", style: { marginBottom: 8 } },
                React.createElement("span", { className: "col-id", style: { fontSize: 12 } }, "#" + s.id),
                React.createElement("span", { className: "prio prio-" + p }, React.createElement("span", { className: "dot" }), prioLabel[p])),
              React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5, marginBottom: 10, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" } }, s.source),
              React.createElement("div", { className: "row between" },
                React.createElement(Avatar, { person: member, size: 26 }),
                s.comments.length ? React.createElement("span", { className: "dim row", style: { gap: 4, fontSize: 12 } }, React.createElement(Icon, { name: "message", size: 13 }), s.comments.length) : null));
          }),
          items.length === 0 && React.createElement("div", { className: "dim", style: { textAlign: "center", padding: 16, fontSize: 13 } }, "Пусто"));
      })
    )
  );
}
window.TabBacklog = TabBacklog;
