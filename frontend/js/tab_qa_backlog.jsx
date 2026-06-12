/* ============================================================
   Tab: QA Dashboard
   ============================================================ */
function TabQA({ store, toast }) {
  const project = store.activeProject;
  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));

  const issues = [];
  project.segments.forEach(s => s.qa.forEach(q => issues.push({ ...q, seg: s.id })));
  const passed = project.segments.filter(s => s.status === "confirmed").length;
  const warnings = project.segments.filter(s => s.status === "qa" || s.status === "review").length;
  const failed = project.segments.filter(s => s.status === "failed").length;

  const groups = [
    { icon: "file", title: "Форматирование", n: 5, desc: "Несогласованная капитализация в 5 сегментах.", tip: "Несоответствие регистра, пунктуации, пробелов между оригиналом и переводом." },
    { icon: "target", title: "Числовые ошибки", n: issues.filter(i => i.type === "numeric").length, desc: "Несоответствие чисел или единиц измерения.", tip: "Несовпадение чисел, дозировок, единиц измерения между оригиналом и переводом (КРИТИЧНО для медицины)." },
    { icon: "book", title: "Терминология", n: issues.filter(i => i.type === "terminology").length, desc: "Обнаружены нежелательные или нестандартные термины.", tip: "Использованы запрещённые термины или термины не из утверждённого глоссария." },
    { icon: "list", title: "Длина перевода", n: 2, desc: "Перевод заметно длиннее или короче оригинала.", tip: "Перевод существенно длиннее/короче оригинала (>2×). Может указывать на пропуск или добавление информации." },
  ];
  const sevMeta = { critical: ["badge-failed", "Критично", "var(--c-error)"], high: ["badge-qa", "Высокий", "var(--c-warning)"], medium: ["badge-review", "Средний", "#ca8a04"] };

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Контроль качества",
        React.createElement(InfoTip, { title: "Контроль качества (QA)", body: "6-этапный pipeline QA: локальные проверки (8) → консистентность → адаптивное планирование → проверка чисел → back-check → финальное решение." })),
      React.createElement("p", { className: "lead" }, "Результаты автоматических проверок: терминология, числа, форматирование и длина перевода.")),

    React.createElement("div", { className: "grid grid-3 section" },
      React.createElement(QAStat, { icon: "checkCircle", color: "var(--c-success)", n: passed, label: "Прошли QA" }),
      React.createElement(QAStat, { icon: "warn", color: "var(--c-warning)", n: warnings, label: "Предупреждения" }),
      React.createElement(QAStat, { icon: "alert", color: "var(--c-error)", n: failed, label: "Ошибки" })),

    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Категории замечаний"),
      React.createElement("div", { className: "grid grid-2" },
        groups.map((g, i) => React.createElement("div", { key: i, className: "card card-pad row between card-hover" },
          React.createElement("div", { className: "row", style: { gap: 12 } },
            React.createElement("span", { style: { width: 40, height: 40, borderRadius: 10, background: "var(--bg-sunken)", color: "var(--c-primary)", display: "grid", placeItems: "center" } },
              React.createElement(Icon, { name: g.icon, size: 19 })),
            React.createElement("div", null,
              React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, g.title, React.createElement(InfoTip, { title: g.title, body: g.tip })),
              React.createElement("div", { className: "dim", style: { fontSize: 13, maxWidth: 280 } }, g.desc))),
          React.createElement("span", { className: "badge " + (g.n ? "badge-qa" : "badge-confirmed") }, g.n))))),

    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Детальный список"),
      issues.length
        ? React.createElement("div", { className: "table-wrap" }, React.createElement("table", { className: "tbl" },
            React.createElement("thead", null, React.createElement("tr", null,
              React.createElement("th", { style: { width: 120 } }, "Важность"), React.createElement("th", { style: { width: 80 } }, "Сегм."),
              React.createElement("th", { style: { width: 150 } }, "Тип"), React.createElement("th", null, "Описание"), React.createElement("th", { style: { width: 90 } }, ""))),
            React.createElement("tbody", null, issues.map((it, i) => { const [cls, lab] = sevMeta[it.sev] || sevMeta.medium;
              return React.createElement("tr", { key: i, onClick: () => { store.go("editor"); toast.info("Переход к сегменту #" + it.seg); } },
                React.createElement("td", null, React.createElement("span", { className: "badge " + cls }, lab)),
                React.createElement("td", { className: "col-id" }, "#" + it.seg),
                React.createElement("td", { className: "dim" }, it.type),
                React.createElement("td", { style: { lineHeight: 1.5 } }, it.msg),
                React.createElement("td", { onClick: (e) => e.stopPropagation() }, React.createElement(Btn, { variant: "secondary", size: "sm", icon: "edit", onClick: () => { store.go("editor"); } }, "Исправить")));
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
