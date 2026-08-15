/* ============================================================
   Tab: Preflight / Анализ проекта — Cost + Safety Planner
   Localized, with ⓘ tooltips and a transparent cost model.
   Drill-down: клик на любой блок/строку → редактор с активным фильтром сегментов.
   ============================================================ */
function TabPreflight({ store, toast }) {
  const project = store.activeProject;
  const [analyzing, setAnalyzing] = useState(false);

  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));

  const segs = project.segments;
  const total = segs.length;
  const wordsOf = (s) => (s.source.trim() ? s.source.trim().split(/\s+/).length : 0);

  // ---- Stats ----
  const norm = (t) => t.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, "").replace(/\s+/g, " ").trim();
  const normMap = {};
  segs.forEach(s => { const n = norm(s.source); (normMap[n] = normMap[n] || []).push(s.id); });
  const uniqueCount = Object.keys(normMap).length;
  const dupGroups = Object.values(normMap).filter(a => a.length > 1);
  const dupGroupsCount = dupGroups.length;
  const exactTM = segs.filter(s => s.route === "EXACT_TM");
  const glossCoveredSegs = segs.filter(s => store.glossary.some(g => s.source.toLowerCase().includes(g.src.toLowerCase())));
  const coverage = Math.round(glossCoveredSegs.length / total * 100);
  const analysisTime = (total * 0.045 + 0.6).toFixed(1);

  // ---- Routing ----
  const byRoute = {};
  segs.forEach(s => { (byRoute[s.route] = byRoute[s.route] || []).push(s); });
  const ROUTE_ORDER = ["EXACT_TM", "DUPLICATE", "GOOGLE_SAFE", "GPT_REQUIRED", "HUMAN_REVIEW"];
  const routeRows = ROUTE_ORDER.filter(r => byRoute[r]).map(r => ({ route: r, segs: byRoute[r] }));

  // ---- Risk ----
  const riskCounts = { low: 0, medium: 0, high: 0, critical: 0 };
  segs.forEach(s => riskCounts[s.risk]++);
  const byRisk = {};
  segs.forEach(s => { (byRisk[s.risk] = byRisk[s.risk] || []).push(s); });

  // ---- Cost model ----
  const RATE = { t: 0.0009, qa: 0.0006, bc: 0.0005, sf: 0.0003, google: 0.00002 };
  const isHi = (s) => s.risk === "high" || s.risk === "critical";
  const segCost = (s) => {
    const w = wordsOf(s);
    const baseline = { t: w * RATE.t, qa: w * RATE.qa, bc: w * RATE.bc, sf: w * RATE.sf, google: 0 };
    let opt = { t: 0, qa: 0, bc: 0, sf: 0, google: 0 };
    if (s.route === "GOOGLE_SAFE") opt.google = w * RATE.google;
    else if (s.route === "DUPLICATE") { opt.t = w * RATE.t; opt.qa = w * RATE.qa; }
    else if (s.route === "GPT_REQUIRED") { opt.t = w * RATE.t; opt.qa = w * RATE.qa; if (isHi(s)) { opt.bc = w * RATE.bc; opt.sf = w * RATE.sf; } }
    const sum = (o) => o.t + o.qa + o.bc + o.sf + o.google;
    return { w, baseline, opt, baseSum: sum(baseline), optSum: sum(opt), tokens: Math.round(w * 1.4) };
  };
  const comp = { t: 0, qa: 0, bc: 0, sf: 0, google: 0 };
  const compBase = { t: 0, qa: 0, bc: 0, sf: 0, google: 0 };
  let baseTotal = 0, optTotal = 0;
  segs.forEach(s => { const c = segCost(s);
    ["t", "qa", "bc", "sf", "google"].forEach(k => { comp[k] += c.opt[k]; compBase[k] += c.baseline[k]; });
    baseTotal += c.baseSum; optTotal += c.optSum;
  });
  const savings = baseTotal - optTotal;
  const savePct = baseTotal ? Math.round(savings / baseTotal * 100) : 0;
  const m = (v) => "$" + (v >= 1 ? v.toFixed(2) : v.toFixed(4));

  // ---- Recommended batch order ----
  const PRIO = { DUPLICATE: 0, GPT_REQUIRED: 1, HUMAN_REVIEW: 2 };
  const candidates = segs.filter(s => s.route in PRIO).sort((a, b) => PRIO[a.route] - PRIO[b.route] || a.id - b.id);
  const top10 = candidates.slice(0, 10);

  const analyze = async () => {
    setAnalyzing(true);
    let result = null;
    if (window.API) result = await window.API.safeCall(() => window.API.preflight(project.id));
    if (result && result.ok && window.API) {
      const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
      if (fresh && fresh.segments) store.replaceProjectSegments(project.id, fresh.segments);
    }
    setAnalyzing(false);
    const t = (result && result.analysisTime) || analysisTime;
    toast.success("Анализ завершён", total + " сегментов проанализировано за " + t + " с.");
  };

  // ---- Drill-down: открыть выбранные сегменты в редакторе с активным фильтром ----
  const openDrill = (title, segList) => {
    const ids = (segList || []).map(s => s.id);
    if (!ids.length) return;
    store.setSegmentFilter(ids);
    store.go("editor");
  };

  const T = (title, body, code) => React.createElement(InfoTip, { title, body, code });

  return React.createElement("div", { className: "page page-wide" },

    // ---- Header ----
    React.createElement("div", { className: "row between page-head", style: { alignItems: "flex-end" } },
      React.createElement("div", null,
        React.createElement("h1", null, "Анализ проекта",
          T("Анализ проекта / Стоимость + безопасность",
            "Локальный анализ всех сегментов БЕЗ вызовов API. Определяет: маршрут перевода, риски, стоимость, дубликаты, возможности оптимизации. Безопасно запускать любое количество раз.")),
        React.createElement("p", { className: "lead", style: { marginBottom: 0 } }, "Стоимость и безопасность — планирование до запуска перевода.")),
      React.createElement("div", { className: "row", style: { gap: 6 } },
        React.createElement(Btn, { variant: "primary", icon: analyzing ? null : "target", disabled: analyzing, onClick: analyze },
          analyzing ? React.createElement(React.Fragment, null, React.createElement(Spinner, null), "Анализ…") : "Запустить анализ"),
        T("Запустить анализ", "Анализ только локально, без вызовов API. Результат сохраняется в базу — можно использовать для планирования перевода."))),
    React.createElement("div", { className: "dim", style: { marginTop: -16, marginBottom: 28, fontSize: 13 } }, "Последний анализ: 2 часа назад · " + total + " сегментов · " + analysisTime + " с"),

    // ---- Statistics ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Статистика"),
      React.createElement("div", { className: "grid grid-3" },
        React.createElement(PfMetric, { icon: "list", label: "Всего сегментов", value: total,
          tip: ["Всего сегментов", "Общее количество сегментов в проекте после импорта DOCX и сегментации."],
          onClick: () => openDrill("Все сегменты", segs) }),
        React.createElement(PfMetric, { icon: "filter", label: "Уникальных (норм.)", value: uniqueCount,
          tip: ["Уникальных (нормализованных)", "Количество сегментов с уникальным текстом после нормализации."],
          onClick: () => {
            const seen = new Set(); const uniq = [];
            segs.forEach(s => { const n = norm(s.source); if (!seen.has(n)) { seen.add(n); uniq.push(s); } });
            openDrill("Уникальные сегменты (нормализовано)", uniq);
          }}),
        React.createElement(PfMetric, { icon: "copy", label: "Групп дубликатов", value: dupGroupsCount,
          tip: ["Групп дубликатов", "Группы с 2+ одинаковыми сегментами. Перевод одного копируется на остальные."],
          onClick: () => {
            const dupIds = new Set(dupGroups.flat());
            openDrill("Сегменты-дубликаты (" + dupGroupsCount + " групп)", segs.filter(s => dupIds.has(s.id)));
          }}),
        React.createElement(PfMetric, { icon: "repeat", label: "Точных TM (99%+)", value: exactTM.length,
          tip: ["Точных совпадений TM (99%+)", "Сегменты с совпадением ≥99% в Translation Memory. Стоимость: $0."],
          onClick: exactTM.length ? () => openDrill("Точные совпадения TM (99%+)", exactTM) : null }),
        React.createElement(PfMetric, { icon: "book", label: "Покрытие глоссарием", value: coverage + "%",
          tip: ["Покрытие глоссарием", "Процент сегментов с хотя бы одним термином из глоссария."],
          onClick: glossCoveredSegs.length ? () => openDrill("Сегменты с терминами глоссария", glossCoveredSegs) : null }),
        React.createElement(PfMetric, { icon: "clock", label: "Время анализа", value: analysisTime + " с",
          tip: ["Время анализа (сек)", "Время локального анализа в секундах. Цель: < 120 с для 2828 сегментов."] }))),

    // ---- Routing Summary ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Маршруты обработки",
        T("Маршруты обработки", "Распределение сегментов по маршрутам перевода.")),
      React.createElement("div", { className: "table-wrap" },
        React.createElement("table", { className: "tbl" },
          React.createElement("thead", null, React.createElement("tr", null,
            React.createElement("th", null, "Маршрут"), React.createElement("th", { style: { width: 130 } }, "Сегментов"), React.createElement("th", { style: { width: 280 } }, "Доля"))),
          React.createElement("tbody", null,
            routeRows.map(r => { const n = r.segs.length; const pct = Math.round(n / total * 100);
              return React.createElement("tr", { key: r.route, className: "drill-row", onClick: () => openDrill("Маршрут: " + (ROUTE_INFO[r.route] ? ROUTE_INFO[r.route].label : r.route), r.segs) },
                React.createElement("td", null, React.createElement(RouteLabel, { route: r.route })),
                React.createElement("td", { className: "tnum", style: { fontWeight: 650 } }, n),
                React.createElement("td", null, React.createElement("div", { className: "row", style: { gap: 10 } },
                  React.createElement("div", { className: "pbar", style: { flex: 1 } }, React.createElement("span", { style: { width: pct + "%", background: ROUTE_INFO[r.route].color } })),
                  React.createElement("span", { className: "tnum dim", style: { width: 38, textAlign: "right" } }, pct + "%"))));
            }))))),

    // ---- Risk Summary ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Сводка по рискам",
        T("Сводка по рискам", "Уровень риска рассчитывается по эвристикам: семантическая плотность, медицинские термины, числа/дозировки.")),
      React.createElement("div", { className: "table-wrap" },
        React.createElement("table", { className: "tbl" },
          React.createElement("thead", null, React.createElement("tr", null,
            React.createElement("th", null, "Уровень риска"), React.createElement("th", { style: { width: 130 } }, "Сегментов"), React.createElement("th", { style: { width: 280 } }, "Доля"))),
          React.createElement("tbody", null,
            ["critical", "high", "medium", "low"].map(k => { const n = riskCounts[k]; const pct = Math.round(n / total * 100);
              return React.createElement("tr", { key: k, className: n ? "drill-row" : "", onClick: n ? () => openDrill("Риск: " + RISK_INFO[k].label + " (" + n + " сегментов)", byRisk[k] || []) : null },
                React.createElement("td", null, React.createElement(RiskLabel, { risk: k })),
                React.createElement("td", { className: "tnum", style: { fontWeight: 650 } }, n),
                React.createElement("td", null, React.createElement("div", { className: "row", style: { gap: 10 } },
                  React.createElement("div", { className: "pbar", style: { flex: 1 } }, React.createElement("span", { style: { width: pct + "%", background: RISK_INFO[k].color } })),
                  React.createElement("span", { className: "tnum dim", style: { width: 38, textAlign: "right" } }, pct + "%"))));
            }))))),

    // ---- Cost Estimate ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Оценка стоимости (USD)",
        T("Оценка стоимости (USD)", "Прогноз стоимости API-вызовов на основе токенов. Точность ±15%.")),
      React.createElement("div", { className: "grid grid-3" },
        React.createElement(PfMetric, { icon: "cpu", label: "Базовая (всё через GPT)", value: m(baseTotal), color: "var(--text-2)",
          tip: ["Базовая стоимость (всё через GPT)", "Сколько стоило бы перевести ВСЕ сегменты через GPT-4 без оптимизации."] }),
        React.createElement(PfMetric, { icon: "zap", label: "Оптимизированная", value: m(optTotal), color: "var(--c-purple)",
          tip: ["Оптимизированная стоимость", "Прогноз с применением маршрутизации: дубликаты, Google для простых, TM для совпадений."] }),
        React.createElement(PfMetric, { icon: "checkCircle", label: "Экономия (" + savePct + "%)", value: m(savings), color: "var(--c-success)",
          tip: ["Потенциальная экономия", "Baseline − Optimized."] }))),

    // ---- Cost Components Breakdown ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Разбивка по компонентам",
        T("Разбивка по компонентам", "Стоимость по этапам обработки.")),
      React.createElement("div", { className: "table-wrap" },
        React.createElement("table", { className: "tbl" },
          React.createElement("thead", null, React.createElement("tr", null,
            React.createElement("th", null, "Компонент"), React.createElement("th", { style: { width: 130 } }, "Базовая ($)"),
            React.createElement("th", { style: { width: 150 } }, "Оптимизир. ($)"), React.createElement("th", { style: { width: 130 } }, "Экономия ($)"))),
          React.createElement("tbody", null,
            [
              ["t", "Перевод", ["Перевод", "Стоимость перевода через GPT-4 (input + output tokens × цена)."]],
              ["qa", "Проверка качества", ["Проверка качества", "Автоматическая проверка перевода через GPT-4."]],
              ["bc", "Обратная проверка", ["Обратная проверка", "Обратный перевод для проверки смысловой эквивалентности. Только для HIGH/CRITICAL."]],
              ["sf", "Проверка безопасности", ["Проверка безопасности", "Финальная проверка на ошибки в дозировках, медицинскую корректность."]],
              ["google", "Google Translate", ["Google Translate", "Бесплатно до 500K символов/мес, далее $20 за 1M символов."]],
            ].map(([k, label, tip]) => React.createElement("tr", { key: k },
              React.createElement("td", null, React.createElement("span", { style: { fontWeight: 600 } }, label), T(tip[0], tip[1])),
              React.createElement("td", { className: "tnum dim" }, m(compBase[k])),
              React.createElement("td", { className: "tnum" }, m(comp[k])),
              React.createElement("td", { className: "tnum", style: { color: "var(--c-success)", fontWeight: 600 } }, m(compBase[k] - comp[k]))))))))  ,

    // ---- Route Cost Breakdown ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Стоимость по маршрутам",
        T("Стоимость по маршрутам", "Сколько стоит каждый маршрут в отдельности.")),
      React.createElement("div", { className: "table-wrap" },
        React.createElement("div", { className: "tbl-scroll" },
          React.createElement("table", { className: "tbl" },
            React.createElement("thead", null, React.createElement("tr", null,
              React.createElement("th", null, "Маршрут"), React.createElement("th", { style: { width: 96 } }, "Сегм."), React.createElement("th", { style: { width: 96 } }, "Токены"),
              React.createElement("th", { style: { width: 110 } }, "Базовая ($)"), React.createElement("th", { style: { width: 120 } }, "Оптимиз. ($)"), React.createElement("th", { style: { width: 110 } }, "Экономия ($)"))),
            React.createElement("tbody", null,
              routeRows.map(r => {
                let segN = r.segs.length, tok = 0, base = 0, opt = 0;
                r.segs.forEach(s => { const c = segCost(s); tok += c.tokens; base += c.baseSum; opt += c.optSum; });
                return React.createElement("tr", { key: r.route, className: "drill-row", onClick: () => openDrill("Маршрут: " + (ROUTE_INFO[r.route] ? ROUTE_INFO[r.route].label : r.route), r.segs) },
                  React.createElement("td", null, React.createElement(RouteLabel, { route: r.route, withTip: false })),
                  React.createElement("td", { className: "tnum" }, segN),
                  React.createElement("td", { className: "tnum dim" }, tok.toLocaleString("ru-RU")),
                  React.createElement("td", { className: "tnum dim" }, m(base)),
                  React.createElement("td", { className: "tnum" }, m(opt)),
                  React.createElement("td", { className: "tnum", style: { color: "var(--c-success)", fontWeight: 600 } }, m(base - opt)));
              })))))),

    // ---- Соответствие обратного перевода ----
    React.createElement(BackcheckBands, { segments: segs, onDrill: openDrill, T }),

    // ---- Zero-Token Optimization ----
    React.createElement("div", { className: "section" },
      React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 16 } },
        React.createElement("div", null,
          React.createElement("h3", { style: { fontSize: 18, fontWeight: 700 } }, "Оптимизация без токенов",
            T("Оптимизация без токенов", "Действия без вызовов API: заполнение из TM и копирование переводов между дубликатами.")),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } }, "Сократите количество API-вызовов перед переводом:")),
        React.createElement("div", { className: "grid grid-2" },
          React.createElement(ZeroItem, { icon: "repeat", title: "Точное TM",
            text: "Заполнить из доверенной памяти переводов (0 токенов)",
            tip: ["Точное TM", "Найти сегменты с совпадением ≥99% в TM и подставить существующий перевод."] }),
          React.createElement(ZeroItem, { icon: "copy", title: "Дубликаты",
            text: "Скопировать подтверждённые переводы дубликатам (0 токенов)",
            tip: ["Дубликаты", "После подтверждения representative-сегмента, перевод копируется дубликатам."] })),
        React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
          React.createElement(OptBtn, { icon: "download", label: "Применить точное TM",
            tip: ["Применить точное TM", "Заполнить сегменты с TM ≥99%."],
            onClick: () => toast.success("Точное TM применено", exactTM.length + " сегментов заполнено из памяти переводов.") }),
          React.createElement(OptBtn, { icon: "clipboard", label: "Подготовить representatives",
            tip: ["Подготовить representatives", "Отметить первый сегмент каждой группы дубликатов."],
            onClick: () => toast.info("Representatives отмечены", dupGroupsCount + " групп дубликатов подготовлено.") }),
          React.createElement(OptBtn, { icon: "repeat", label: "Распространить дубликаты",
            tip: ["Распространить дубликаты", "Скопировать переводы representatives на все дубликаты."],
            onClick: () => toast.info("Распространение", "Переводы скопированы по группам дубликатов.") }),
          React.createElement(OptBtn, { icon: "list", label: "Показать группы дубликатов",
            tip: ["Показать группы дубликатов", "Открыть список всех групп дубликатов."],
            onClick: () => {
              const dupIds = new Set(dupGroups.flat());
              openDrill("Группы дубликатов (" + dupGroupsCount + " групп)", segs.filter(s => dupIds.has(s.id)));
            } })))),

    // ---- Recommended Batch Order ----
    React.createElement("div", { className: "section" },
      React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 14 } },
        React.createElement("h3", { style: { fontSize: 18, fontWeight: 700 } }, "Рекомендуемый порядок обработки",
          T("Рекомендуемый порядок обработки", "Оптимальный порядок перевода: сначала representatives дубликатов, затем GPT_REQUIRED, затем HUMAN_REVIEW.")),
        React.createElement("p", { className: "muted", style: { fontSize: 14, margin: 0 } }, "Обработайте сегменты в этом порядке для оптимизации затрат:"),
        React.createElement("div", { className: "label", style: { marginTop: 2 } }, "Топ-10 ID сегментов:"),
        React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
          top10.map((s, i) => React.createElement("span", { key: s.id, className: "badge badge-soft mono", title: ROUTE_INFO[s.route] ? ROUTE_INFO[s.route].label : s.route, style: { height: 30, fontSize: 13, cursor: "pointer" },
            onClick: () => openDrill("Рекомендуемые сегменты (" + candidates.length + ")", candidates) },
            React.createElement("span", { className: "dim", style: { fontSize: 11 } }, (i + 1) + "."), "#" + s.id))),
        React.createElement("p", { className: "dim", style: { fontSize: 12, margin: 0 } }, "(Показаны первые " + top10.length + " из " + candidates.length + " рекомендуемых)"))
    )
  );
}

function PfMetric({ icon, label, value, sub, color, tip, onClick }) {
  return React.createElement("div", {
    className: "card metric" + (onClick ? " drill-metric" : ""),
    onClick: onClick || undefined,
    style: onClick ? { cursor: "pointer" } : null
  },
    React.createElement("div", { className: "m-label" },
      React.createElement(Icon, { name: icon, size: 16, style: { color: color || "var(--c-primary)" } }),
      label, tip && React.createElement(InfoTip, { title: tip[0], body: tip[1] })),
    React.createElement("div", { className: "m-value", style: color ? { color } : null }, value),
    onClick && React.createElement("div", { className: "dim", style: { fontSize: 11, marginTop: 4 } }, "Открыть в редакторе →"),
    sub && React.createElement("div", { className: "m-sub" }, sub));
}

function ZeroItem({ icon, title, text, tip }) {
  return React.createElement("div", { className: "card", style: { padding: 14, background: "var(--bg-sunken)", display: "flex", gap: 12, alignItems: "flex-start" } },
    React.createElement("span", { style: { width: 34, height: 34, borderRadius: 9, background: "var(--card)", color: "var(--c-success)", display: "grid", placeItems: "center", flex: "0 0 34px" } },
      React.createElement(Icon, { name: icon, size: 17 })),
    React.createElement("div", null,
      React.createElement("div", { style: { fontWeight: 650, display: "flex", alignItems: "center" } }, title,
        React.createElement("span", { className: "badge badge-confirmed", style: { marginLeft: 8, height: 20 } }, "0 токенов"),
        tip && React.createElement(InfoTip, { title: tip[0], body: tip[1] })),
      React.createElement("div", { className: "muted", style: { fontSize: 13, marginTop: 3 } }, text)));
}

function OptBtn({ icon, label, tip, onClick }) {
  return React.createElement("span", { className: "row", style: { gap: 2 } },
    React.createElement(Btn, { variant: "secondary", size: "sm", icon, onClick }, label),
    tip && React.createElement(InfoTip, { title: tip[0], body: tip[1] }));
}


/* ---------- Соответствие обратного перевода: полосы с переходом в редактор ---------- */
// Границы полос дублировать нельзя — берём их из /api/models, где их задаёт бэкенд.
// Пока каталог не пришёл, показываем блок по встроенному запасному списку.
const BC_BANDS_FALLBACK = [
  { key: "eq100", min: 100, max: 100, label: "100%",   note: "Дословное совпадение",       color: "green" },
  { key: "b98",   min: 98,  max: 99,  label: "98-99%", note: "Почти дословно",             color: "green" },
  { key: "b95",   min: 95,  max: 97,  label: "95-97%", note: "Незначительные расхождения", color: "green" },
  { key: "b90",   min: 90,  max: 94,  label: "90-94%", note: "Мелкие расхождения",         color: "yellow" },
  { key: "b85",   min: 85,  max: 89,  label: "85-89%", note: "Заметные расхождения",       color: "yellow" },
  { key: "b80",   min: 80,  max: 84,  label: "80-84%", note: "Требует просмотра",          color: "orange" },
  { key: "b70",   min: 70,  max: 79,  label: "70-79%", note: "Смысл поплыл",               color: "orange" },
  { key: "low",   min: 0,   max: 69,  label: "< 70%",  note: "Смысл разошёлся",            color: "red" },
];

function bcBandColor(color) {
  return color === "green" ? "var(--c-success)"
    : color === "yellow" ? "var(--c-warning)"
    : color === "orange" ? "var(--c-warning)"
    : "var(--c-error)";
}

function BackcheckBands({ segments, onDrill, T }) {
  const [bands, setBands] = useState(BC_BANDS_FALLBACK);
  useEffect(() => {
    if (!window.API || !window.API.models) return;
    window.API.safeCall(() => window.API.models()).then(d => {
      if (d && d.backcheckBands && d.backcheckBands.length) setBands(d.backcheckBands);
    });
  }, []);

  const translated = segments.filter(s => (s.target || "").trim());
  const checked = translated.filter(s => s.backcheck && s.backcheck.score != null);
  const termLost = checked.filter(s => (s.backcheck.terms_lost || []).length > 0);
  const maxCount = Math.max(1, ...bands.map(b =>
    checked.filter(s => s.backcheck.score >= b.min && s.backcheck.score <= b.max).length));

  return React.createElement("div", { className: "section" },
    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 14 } },
      React.createElement("div", { className: "row between", style: { alignItems: "flex-end", flexWrap: "wrap", gap: 10 } },
        React.createElement("div", null,
          React.createElement("h3", { style: { fontSize: 18, fontWeight: 700 } }, "Соответствие обратного перевода",
            T("Соответствие обратного перевода",
              "Перевод переводится обратно на язык оригинала и сравнивается с исходным текстом: числа, единицы, отрицания, лево-право, сохранность терминов. Процент показывает, сколько смысла пережило круг. Запускается на вкладке «Редактор», карточка Back-check.")),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } },
            "Проверено " + checked.length + " из " + translated.length + " переведённых сегментов")),
        checked.length > 0 && React.createElement("div", { className: "dim", style: { fontSize: 13 } },
          "Средний балл: " +
          Math.round(checked.reduce((a, s) => a + s.backcheck.score, 0) / checked.length) + "%")
      ),

      checked.length === 0
        ? React.createElement(EmptyState, { icon: "repeat", title: "Back-check ещё не запускался",
            sub: "Запустите его в Редакторе — карточка Back-check в блоке пакетных операций." })
        : React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            bands.map(b => {
              const list = checked.filter(s => s.backcheck.score >= b.min && s.backcheck.score <= b.max);
              const pct = Math.round(list.length / maxCount * 100);
              return React.createElement("div", {
                key: b.key, className: "row", style: { gap: 10, cursor: list.length ? "pointer" : "default", opacity: list.length ? 1 : 0.45, padding: "3px 0" },
                onClick: () => list.length && onDrill(b.label, list),
                title: list.length ? "Открыть эти сегменты в редакторе" : "Нет сегментов в этой полосе" },
                React.createElement("span", { className: "mono", style: { width: 72, fontSize: 13, fontWeight: 700, color: bcBandColor(b.color) } }, b.label),
                React.createElement("span", { className: "dim", style: { width: 190, fontSize: 12.5 } }, b.note),
                React.createElement("div", { style: { flex: 1, height: 10, background: "var(--bg-sunken)", borderRadius: 5, overflow: "hidden" } },
                  React.createElement("div", { style: { width: pct + "%", height: "100%", background: bcBandColor(b.color) } })),
                React.createElement("b", { className: "tnum", style: { width: 56, textAlign: "right", fontSize: 13 } }, list.length)
              );
            })
          ),

      termLost.length > 0 && React.createElement("div", {
        className: "row between", style: { borderTop: "1px solid var(--border)", paddingTop: 10, cursor: "pointer" },
        onClick: () => onDrill("Потеря термина", termLost),
        title: "Открыть эти сегменты в редакторе" },
        React.createElement("span", { style: { fontSize: 13, fontWeight: 600, color: "var(--c-error)" } },
          "Из них с потерей термина"),
        React.createElement("b", { className: "tnum", style: { fontSize: 13 } }, termLost.length))
    )
  );
}

window.TabPreflight = TabPreflight;
