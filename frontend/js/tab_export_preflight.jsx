/* ============================================================
   Tab: Export — download translated document
   ============================================================ */
function TabExport({ store, toast }) {
  const project = store.activeProject;
  const [fmt, setFmt] = useState("docx");
  const [opts, setOpts] = useState({ source: true, notes: true, qa: false, glossary: true });
  const [busy, setBusy] = useState(false);
  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));

  const toggle = (k) => setOpts(o => ({ ...o, [k]: !o[k] }));
  const doExport = async () => {
    setBusy(true);
    let result = null;
    if (window.API) result = await window.API.safeCall(() => window.API.exportProject(project.id, fmt));
    setBusy(false);
    const fileName = (result && result.file) || (project.title + "." + fmt);
    // Prepend to history locally so user sees it without refresh
    if (store.setExportHistory) {
      store.setExportHistory(h => [{ file: fileName, when: new Date().toISOString().slice(0,16).replace("T"," "), size: "≈ 80 КБ" }, ...h]);
    }
    toast.success("Файл готов", fileName + " добавлен в историю экспортов.");
  };
  const formats = [
    ["docx", "DOCX", "Microsoft Word — сохраняет форматирование", "file"],
    ["pdf", "PDF", "Только для чтения — удобно для проверки", "file"],
    ["xlsx", "Excel", "Таблица: оригинал и перевод по столбцам", "columns"],
  ];

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Экспорт"),
      React.createElement("p", { className: "lead" }, "Соберите готовый документ из подтверждённых сегментов проекта «" + project.title + "».")),

    React.createElement("div", { className: "grid", style: { gridTemplateColumns: "1.4fr 1fr", gap: 24, alignItems: "start" } },
      React.createElement("div", { className: "col", style: { gap: 32 } },
        React.createElement("div", null,
          React.createElement("h2", { className: "section-title" }, "Формат файла"),
          React.createElement("div", { className: "col", style: { gap: 10 } },
            formats.map(([v, t, d, ic]) => React.createElement("label", {
              key: v, className: "card card-pad row", style: { gap: 14, cursor: "pointer", borderColor: fmt === v ? "var(--c-primary)" : "var(--border)", boxShadow: fmt === v ? "0 0 0 3px var(--ring)" : "var(--shadow-sm)" },
              onClick: () => setFmt(v) },
              React.createElement(Radio, { name: "fmt", checked: fmt === v, onChange: () => setFmt(v) }),
              React.createElement("span", { style: { width: 38, height: 38, borderRadius: 9, background: "var(--bg-sunken)", color: "var(--c-primary)", display: "grid", placeItems: "center" } },
                React.createElement(Icon, { name: ic, size: 19 })),
              React.createElement("div", null,
                React.createElement("div", { style: { fontWeight: 650 } }, t),
                React.createElement("div", { className: "dim", style: { fontSize: 13 } }, d))))),
          React.createElement("p", { className: "hint", style: { marginTop: 10 } }, "DOCX рекомендуется для большинства случаев.")
        ),
        React.createElement("div", null,
          React.createElement("h2", { className: "section-title" }, "Что включить"),
          React.createElement("div", { className: "card card-pad col", style: { gap: 16 } },
            React.createElement(Checkbox, { checked: opts.source, onChange: () => toggle("source") }, "Оригинал в примечаниях"),
            React.createElement(Checkbox, { checked: opts.notes, onChange: () => toggle("notes") }, "Заметки переводчика"),
            React.createElement(Checkbox, { checked: opts.qa, onChange: () => toggle("qa") }, "Результаты QA"),
            React.createElement(Checkbox, { checked: opts.glossary, onChange: () => toggle("glossary") }, "Ссылки на глоссарий"))
        )
      ),

      React.createElement("div", { className: "col", style: { gap: 24 } },
        React.createElement("div", { className: "card card-pad col", style: { gap: 14 } },
          React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, "Готово к экспорту"),
          React.createElement("div", { className: "row between" }, React.createElement("span", { className: "muted" }, "Сегментов"), React.createElement("strong", null, project.segments.length)),
          React.createElement("div", { className: "row between" }, React.createElement("span", { className: "muted" }, "Подтверждено"), React.createElement("strong", { style: { color: "var(--c-success)" } }, store.statusCounts(project).confirmed)),
          React.createElement("div", { className: "row between" }, React.createElement("span", { className: "muted" }, "Формат"), React.createElement("strong", null, fmt.toUpperCase())),
          React.createElement(Btn, { variant: "primary", size: "lg", className: "btn-block", icon: busy ? null : "download", disabled: busy, onClick: doExport },
            busy ? React.createElement(React.Fragment, null, React.createElement(Spinner, null), "Сборка файла…") : "Скачать файл")
        ),
        React.createElement("div", null,
          React.createElement("h2", { className: "section-title", style: { fontSize: 17 } }, "Недавние экспорты"),
          React.createElement("div", { className: "col", style: { gap: 8 } },
            store.exportHistory.map((e, i) => React.createElement("div", { key: i, className: "card row between", style: { padding: "12px 14px" } },
              React.createElement("div", { className: "row", style: { gap: 10, minWidth: 0 } },
                React.createElement(Icon, { name: "file", size: 17, style: { color: "var(--text-3)" } }),
                React.createElement("div", { style: { minWidth: 0 } },
                  React.createElement("div", { style: { fontSize: 13, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, e.file),
                  React.createElement("div", { className: "dim", style: { fontSize: 12 } }, e.when + " · " + e.size))),
              React.createElement(IconBtn, { icon: "repeat", label: "Повторить экспорт", sm: true, onClick: () => toast.info("Повторный экспорт", e.file) }))))
        )
      )
    )
  );
}
window.TabExport = TabExport;

/* ============================================================
   Tab: Preflight — pre-translation analysis
   ============================================================ */
function TabPreflightOld({ store, toast }) {
  const project = store.activeProject;
  const [analyzing, setAnalyzing] = useState(false);
  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));

  const total = project.segments.length;
  const byRoute = {};
  project.segments.forEach(s => { byRoute[s.route] = (byRoute[s.route] || 0) + 1; });
  const routes = [
    ["EXACT_TM", "Точное TM", "var(--route-tm)", 0],
    ["DUPLICATE", "Дубликаты", "var(--route-dup)", 0],
    ["GOOGLE_SAFE", "Google", "var(--route-google)", 0],
    ["GPT_REQUIRED", "GPT-4", "var(--route-gpt)", 0.19],
    ["HUMAN_REVIEW", "Проверка", "var(--route-human)", 0],
  ].map(([k, l, c, cost]) => ({ k, l, c, n: byRoute[k] || 0, cost: (byRoute[k] || 0) * cost }));
  const estCost = routes.reduce((a, r) => a + r.cost, 0);
  const tmMatches = byRoute["EXACT_TM"] || 0;
  const riskCounts = { low: 0, medium: 0, high: 0, critical: 0 };
  project.segments.forEach(s => riskCounts[s.risk]++);
  const glossCovered = project.segments.filter(s => store.glossary.some(g => s.source.toLowerCase().includes(g.src.toLowerCase()))).length;
  const coverage = Math.round(glossCovered / total * 100);

  const analyze = () => { setAnalyzing(true); setTimeout(() => { setAnalyzing(false); toast.success("Анализ завершён", total + " сегментов проанализировано."); }, 1500); };

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "row between page-head", style: { alignItems: "flex-end" } },
      React.createElement("div", null,
        React.createElement("h1", null, "Предполётный анализ"),
        React.createElement("p", { className: "lead", style: { marginBottom: 0 } }, "Маршрутизация, стоимость и риски до запуска перевода.")),
      React.createElement(Btn, { variant: "primary", icon: analyzing ? null : "target", disabled: analyzing, onClick: analyze },
        analyzing ? React.createElement(React.Fragment, null, React.createElement(Spinner, null), "Анализ…") : "Анализировать")),
    React.createElement("div", { className: "dim", style: { marginTop: -16, marginBottom: 24, fontSize: 13 } }, "Последний анализ: 2 часа назад · " + total + " сегментов"),

    React.createElement("div", { className: "grid grid-4 section" },
      React.createElement(Metric, { icon: "list", label: "Всего сегментов", value: total }),
      React.createElement(Metric, { icon: "repeat", label: "Точные TM", value: tmMatches, sub: Math.round(tmMatches / total * 100) + "% покрытия" }),
      React.createElement(Metric, { icon: "zap", label: "Оценка стоимости", value: "$" + estCost.toFixed(2), color: "var(--c-purple)" }),
      React.createElement(Metric, { icon: "target", label: "Сложность", value: "Средняя", sub: riskCounts.high + riskCounts.critical + " высокого риска" })),

    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Маршрутизация сегментов"),
      React.createElement("div", { className: "card card-pad" },
        routes.map(r => React.createElement("div", { key: r.k, className: "hbar-row" },
          React.createElement("div", { className: "row", style: { gap: 8 } },
            React.createElement("span", { style: { width: 10, height: 10, borderRadius: 3, background: r.c } }),
            React.createElement("span", { style: { fontWeight: 600, fontSize: 13 } }, r.l)),
          React.createElement("div", { className: "hbar-track" },
            React.createElement("div", { className: "hbar-fill", style: { width: Math.max(6, r.n / total * 100) + "%", background: r.c } }, r.n + " сегм.")),
          React.createElement("div", { className: "hbar-cost dim", style: { textAlign: "right", fontWeight: 600 } }, r.cost ? "$" + r.cost.toFixed(2) : "$0"))))),

    React.createElement("div", { className: "grid grid-2 section" },
      React.createElement(Expander, { title: "Сводка по рискам", icon: "shield", right: total + " сегментов", defaultOpen: true },
        React.createElement("div", { className: "col", style: { gap: 12 } },
          [["low", "Низкий", "var(--c-success)"], ["medium", "Средний", "#ca8a04"], ["high", "Высокий", "var(--c-warning)"], ["critical", "Критический", "var(--c-error)"]]
            .map(([k, l, c]) => React.createElement("div", { key: k, className: "row between" },
              React.createElement("div", { className: "row", style: { gap: 8 } }, React.createElement("span", { style: { width: 9, height: 9, borderRadius: "50%", background: c } }), l),
              React.createElement("strong", null, riskCounts[k]))))),
      React.createElement("div", { className: "card card-pad col", style: { gap: 14 } },
        React.createElement("h3", { style: { fontSize: 17, fontWeight: 650 } }, "Покрытие глоссарием"),
        React.createElement(Ring, { value: coverage, size: 120, label: "покрыто" }),
        React.createElement("div", { className: "col", style: { gap: 6, width: "100%" } },
          React.createElement("div", { className: "row between" }, React.createElement("span", { className: "muted" }, "Сегментов с терминами"), React.createElement("strong", null, glossCovered)),
          React.createElement("div", { className: "row between" }, React.createElement("span", { className: "muted" }, "Отсутствующих терминов"), React.createElement("strong", { style: { color: "var(--c-warning)" } }, "15"))),
        React.createElement("div", { className: "card", style: { padding: "10px 12px", background: "var(--st-qa-bg)", color: "var(--st-qa-fg)", fontSize: 13 } },
          "Рекомендуется добавить 5 ключевых терминов в глоссарий."))
    )
  );
}

function Metric({ icon, label, value, sub, color }) {
  return React.createElement("div", { className: "card metric" },
    React.createElement("div", { className: "m-label" }, React.createElement(Icon, { name: icon, size: 16, style: { color: color || "var(--c-primary)" } }), label),
    React.createElement("div", { className: "m-value", style: color ? { color } : null }, value),
    sub && React.createElement("div", { className: "m-sub" }, sub));
}
window.Metric = Metric;
