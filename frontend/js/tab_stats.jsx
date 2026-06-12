/* ============================================================
   Tab: Statistics — project overview & metrics
   ============================================================ */
function TabStats({ store }) {
  const project = store.activeProject;
  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));

  const total = project.segments.length;
  const c = store.statusCounts(project);
  const translated = c.translated + c.qa + c.confirmed + c.review;
  const qaDone = c.qa + c.confirmed;
  const confirmed = c.confirmed;
  const pct = (n) => Math.round(n / total * 100);
  const team = store.team;
  const totalEdits = team.reduce((a, t) => a + t.edits, 0);

  // simple activity sparkline data
  const activity = [4, 9, 7, 12, 8, 15, 11, 18, 14, 9, 16, 13];
  const maxA = Math.max(...activity);

  const cost = [
    { l: "Память переводов", v: 0, c: "var(--route-tm)" },
    { l: "Google Translate", v: 3.20, c: "var(--route-google)" },
    { l: "GPT-4", v: 8.75, c: "var(--route-gpt)" },
  ];
  const totalCost = cost.reduce((a, x) => a + x.v, 0);
  const budget = 50;

  return React.createElement("div", { className: "page page-wide" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Статистика проекта",
        React.createElement(InfoTip, { title: "Статистика проекта", body: "Обзор прогресса, скорости, качества и затрат по проекту." })),
      React.createElement("p", { className: "lead" }, "Обзор прогресса, активности команды и затрат по проекту «" + project.title + "».")),

    React.createElement("div", { className: "grid", style: { gridTemplateColumns: "320px 1fr", gap: 24, alignItems: "start" } },
      // progress ring
      React.createElement("div", { className: "card card-pad col", style: { gap: 18, alignItems: "center" } },
        React.createElement("h2", { className: "section-title", style: { margin: 0, alignSelf: "flex-start" } }, "Прогресс"),
        React.createElement(Ring, { value: pct(confirmed), size: 168, stroke: 14, label: "завершено" }),
        React.createElement("div", { className: "col", style: { gap: 12, width: "100%" } },
          React.createElement(StatLine, { label: "Переведено", n: translated, pct: pct(translated), color: "var(--c-primary)" }),
          React.createElement(StatLine, { label: "Проверено (QA)", n: qaDone, pct: pct(qaDone), color: "var(--c-warning)" }),
          React.createElement(StatLine, { label: "Подтверждено", n: confirmed, pct: pct(confirmed), color: "var(--c-success)" }))),

      React.createElement("div", { className: "col", style: { gap: 24 } },
        // timeline
        React.createElement("div", { className: "card card-pad" },
          React.createElement("div", { className: "row between", style: { marginBottom: 12 } },
            React.createElement("h3", { style: { fontSize: 16, fontWeight: 650 } }, "Сроки проекта"),
            React.createElement("span", { className: "dim", style: { fontSize: 13 } }, "2 из 4 недель · 50%")),
          React.createElement("div", { className: "pbar", style: { height: 12, position: "relative" } },
            React.createElement("span", { style: { width: "50%" } })),
          React.createElement("div", { className: "row between", style: { marginTop: 8, fontSize: 12 } },
            React.createElement("span", { className: "dim" }, "Старт: " + project.created),
            React.createElement("span", { className: "dim" }, "Дедлайн: " + project.deadline))),

        // metrics row
        React.createElement("div", { className: "grid grid-4" },
          React.createElement(Metric, { icon: "clock", label: "Среднее на сегмент", value: "4:23" }),
          React.createElement(PfMetric, { icon: "zap", label: "Скорость", value: "23/ч", color: "var(--c-purple)",
            tip: ["Скорость", "Сегментов переведено в час. Помогает планировать сроки."] }),
          React.createElement(Metric, { icon: "calendar", label: "Всего часов", value: "12.5" }),
          React.createElement(Metric, { icon: "target", label: "Прогноз", value: "Завтра", sub: "≈ 15:00" })),

        // activity chart
        React.createElement("div", { className: "card card-pad" },
          React.createElement("h3", { style: { fontSize: 16, fontWeight: 650, marginBottom: 14 } }, "Активность — сегментов в день"),
          React.createElement("div", { className: "row", style: { gap: 6, alignItems: "flex-end", height: 110 } },
            activity.map((a, i) => React.createElement("div", { key: i, style: { flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 } },
              React.createElement("div", { title: a + " сегм.", style: { width: "100%", maxWidth: 34, height: (a / maxA * 90) + "px", background: i === activity.length - 1 ? "var(--c-primary)" : "var(--c-primary-soft)", borderRadius: "5px 5px 0 0", transition: "height .4s ease" } }),
              React.createElement("span", { className: "dim", style: { fontSize: 10 } }, i + 1)))))
      )
    ),

    React.createElement("div", { className: "grid grid-2 section", style: { marginTop: 24 } },
      // team
      React.createElement("div", { className: "card card-pad" },
        React.createElement("div", { className: "row between", style: { marginBottom: 16 } },
          React.createElement("h3", { style: { fontSize: 16, fontWeight: 650 } }, "Команда"),
          React.createElement("div", { className: "facepile" }, team.slice(0, 5).map((t, i) => React.createElement(Avatar, { key: i, person: t })))),
        React.createElement("div", { className: "col", style: { gap: 10 } },
          team.map((t, i) => React.createElement("div", { key: i, className: "row between" },
            React.createElement("div", { className: "row", style: { gap: 10 } }, React.createElement(Avatar, { person: t, size: 28 }), React.createElement("span", { style: { fontSize: 14 } }, t.name)),
            React.createElement("div", { className: "row", style: { gap: 10, minWidth: 120, justifyContent: "flex-end" } },
              React.createElement("div", { className: "pbar", style: { width: 70 } }, React.createElement("span", { style: { width: (t.edits / team[0].edits * 100) + "%", background: t.color } })),
              React.createElement("span", { className: "dim tnum", style: { fontSize: 13, width: 28, textAlign: "right" } }, t.edits))))),
        React.createElement("div", { className: "dim", style: { fontSize: 13, marginTop: 14 } }, "Всего правок: " + totalEdits + " · самый активный: " + team[0].name)),

      // cost
      React.createElement("div", { className: "card card-pad" },
        React.createElement("h3", { style: { fontSize: 16, fontWeight: 650, marginBottom: 16 } }, "Затраты"),
        React.createElement("div", { className: "row", style: { gap: 8, height: 18, borderRadius: 6, overflow: "hidden", marginBottom: 16 } },
          cost.filter(x => x.v > 0).map((x, i) => React.createElement("div", { key: i, title: x.l, style: { width: (x.v / totalCost * 100) + "%", background: x.c } }))),
        React.createElement("div", { className: "col", style: { gap: 10 } },
          cost.map((x, i) => React.createElement("div", { key: i, className: "row between" },
            React.createElement("div", { className: "row", style: { gap: 8 } }, React.createElement("span", { style: { width: 10, height: 10, borderRadius: 3, background: x.c } }), x.l),
            React.createElement("strong", { className: "tnum" }, "$" + x.v.toFixed(2))))),
        React.createElement("div", { className: "divider" }),
        React.createElement("div", { className: "row between" }, React.createElement("span", { style: { fontWeight: 600 } }, "Итого"), React.createElement("strong", { className: "tnum", style: { fontSize: 18 } }, "$" + totalCost.toFixed(2))),
        React.createElement("div", { className: "row between", style: { marginTop: 8 } },
          React.createElement("span", { className: "muted", style: { fontSize: 13 } }, "Остаток бюджета"),
          React.createElement("span", { className: "tnum", style: { fontSize: 13, color: "var(--c-success)", fontWeight: 600 } }, "$" + (budget - totalCost).toFixed(2) + " / $" + budget.toFixed(2))),
        React.createElement("div", { className: "pbar", style: { marginTop: 8 } }, React.createElement("span", { style: { width: (totalCost / budget * 100) + "%" } })))
    )
  );
}
function StatLine({ label, n, pct, color }) {
  return React.createElement("div", null,
    React.createElement("div", { className: "row between", style: { fontSize: 13, marginBottom: 5 } },
      React.createElement("span", { className: "muted" }, label),
      React.createElement("span", { style: { fontWeight: 700 } }, n + " · " + pct + "%")),
    React.createElement("div", { className: "pbar" }, React.createElement("span", { style: { width: pct + "%", background: color } })));
}
window.TabStats = TabStats;
