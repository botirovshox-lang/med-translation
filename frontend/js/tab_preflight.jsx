/* ============================================================
   Tab: Preflight / Анализ проекта — Cost + Safety Planner
   Localized, with ⓘ tooltips and a transparent cost model.
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
  const dupGroups = Object.values(normMap).filter(a => a.length > 1).length;
  const exactTM = segs.filter(s => s.route === "EXACT_TM").length;
  const glossCovered = segs.filter(s => store.glossary.some(g => s.source.toLowerCase().includes(g.src.toLowerCase()))).length;
  const coverage = Math.round(glossCovered / total * 100);
  const analysisTime = (total * 0.045 + 0.6).toFixed(1);

  // ---- Routing ----
  const byRoute = {};
  segs.forEach(s => { (byRoute[s.route] = byRoute[s.route] || []).push(s); });
  const ROUTE_ORDER = ["EXACT_TM", "DUPLICATE", "GOOGLE_SAFE", "GPT_REQUIRED", "HUMAN_REVIEW"];
  const routeRows = ROUTE_ORDER.filter(r => byRoute[r]).map(r => ({ route: r, segs: byRoute[r] }));

  // ---- Risk ----
  const riskCounts = { low: 0, medium: 0, high: 0, critical: 0 };
  segs.forEach(s => riskCounts[s.risk]++);

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
    // EXACT_TM and HUMAN_REVIEW => 0 (no API)
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
    setAnalyzing(false);
    const t = (result && result.analysisTime) || analysisTime;
    toast.success("Анализ завершён", total + " сегментов проанализировано за " + t + " с.");
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
          tip: ["Всего сегментов", "Общее количество сегментов в проекте после импорта DOCX и сегментации."] }),
        React.createElement(PfMetric, { icon: "filter", label: "Уникальных (норм.)", value: uniqueCount,
          tip: ["Уникальных (нормализованных)", "Количество сегментов с уникальным текстом после нормализации (нижний регистр, удаление пунктуации, тримминг пробелов). Меньше total — значит есть дубликаты."] }),
        React.createElement(PfMetric, { icon: "copy", label: "Групп дубликатов", value: dupGroups,
          tip: ["Групп дубликатов", "Количество групп, где 2+ сегментов имеют одинаковый нормализованный текст. Перевод одного representative-сегмента в группе автоматически копируется на все остальные → экономия токенов."] }),
        React.createElement(PfMetric, { icon: "repeat", label: "Точных TM (99%+)", value: exactTM,
          tip: ["Точных совпадений TM (99%+)", "Сегменты с совпадением ≥99% в Translation Memory. Перевод подтягивается из TM без вызова GPT → стоимость = $0."] }),
        React.createElement(PfMetric, { icon: "book", label: "Покрытие глоссарием", value: coverage + "%",
          tip: ["Покрытие глоссарием", "Процент сегментов, в которых найден хотя бы один термин из утверждённого медицинского глоссария. Высокое покрытие → лучше предсказуемость терминологии."] }),
        React.createElement(PfMetric, { icon: "clock", label: "Время анализа", value: analysisTime + " с",
          tip: ["Время анализа (сек)", "Время локального анализа в секундах. Цель: < 120 с для 2828 сегментов."] }))),

    // ---- Routing Summary ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Маршруты обработки",
        T("Маршруты обработки", "Распределение сегментов по маршрутам перевода. Каждый маршрут оптимизирован под тип контента для минимизации стоимости.")),
      React.createElement("div", { className: "table-wrap" },
        React.createElement("table", { className: "tbl" },
          React.createElement("thead", null, React.createElement("tr", null,
            React.createElement("th", null, "Маршрут"), React.createElement("th", { style: { width: 130 } }, "Сегментов"), React.createElement("th", { style: { width: 280 } }, "Доля"))),
          React.createElement("tbody", null,
            routeRows.map(r => { const n = r.segs.length; const pct = Math.round(n / total * 100);
              return React.createElement("tr", { key: r.route, style: { cursor: "default" } },
                React.createElement("td", null, React.createElement(RouteLabel, { route: r.route })),
                React.createElement("td", { className: "tnum", style: { fontWeight: 650 } }, n),
                React.createElement("td", null, React.createElement("div", { className: "row", style: { gap: 10 } },
                  React.createElement("div", { className: "pbar", style: { flex: 1 } }, React.createElement("span", { style: { width: pct + "%", background: ROUTE_INFO[r.route].color } })),
                  React.createElement("span", { className: "tnum dim", style: { width: 38, textAlign: "right" } }, pct + "%"))));
            }))))),

    // ---- Risk Summary ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Сводка по рискам",
        T("Сводка по рискам", "Уровень риска рассчитывается локально по эвристикам: семантическая плотность, медицинские термины, числа/дозировки, анатомия. Влияет на выбор маршрута и QA.")),
      React.createElement("div", { className: "table-wrap" },
        React.createElement("table", { className: "tbl" },
          React.createElement("thead", null, React.createElement("tr", null,
            React.createElement("th", null, "Уровень риска"), React.createElement("th", { style: { width: 130 } }, "Сегментов"), React.createElement("th", { style: { width: 280 } }, "Доля"))),
          React.createElement("tbody", null,
            ["critical", "high", "medium", "low"].map(k => { const n = riskCounts[k]; const pct = Math.round(n / total * 100);
              return React.createElement("tr", { key: k, style: { cursor: "default" } },
                React.createElement("td", null, React.createElement(RiskLabel, { risk: k })),
                React.createElement("td", { className: "tnum", style: { fontWeight: 650 } }, n),
                React.createElement("td", null, React.createElement("div", { className: "row", style: { gap: 10 } },
                  React.createElement("div", { className: "pbar", style: { flex: 1 } }, React.createElement("span", { style: { width: pct + "%", background: RISK_INFO[k].color } })),
                  React.createElement("span", { className: "tnum dim", style: { width: 38, textAlign: "right" } }, pct + "%"))));
            }))))),

    // ---- Cost Estimate ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Оценка стоимости (USD)",
        T("Оценка стоимости (USD)", "Прогноз стоимости API-вызовов на основе токенов. Точность ±15% — реальная стоимость может отличаться.")),
      React.createElement("div", { className: "grid grid-3" },
        React.createElement(PfMetric, { icon: "cpu", label: "Базовая (всё через GPT)", value: m(baseTotal), color: "var(--text-2)",
          tip: ["Базовая стоимость (всё через GPT)", "Сколько стоило бы перевести ВСЕ сегменты через GPT-4 без оптимизации (translate + QA + back-check + safety)."] }),
        React.createElement(PfMetric, { icon: "zap", label: "Оптимизированная", value: m(optTotal), color: "var(--c-purple)",
          tip: ["Оптимизированная стоимость (с маршрутизацией)", "Прогноз с применением маршрутизации: дубликаты, Google для простых, TM для совпадений, GPT только для сложных."] }),
        React.createElement(PfMetric, { icon: "checkCircle", label: "Экономия (" + savePct + "%)", value: m(savings), color: "var(--c-success)",
          tip: ["Потенциальная экономия", "Сколько сэкономите при использовании оптимизированного маршрута вместо базового. Формула: Baseline − Optimized."] }))),

    // ---- Cost Components Breakdown ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Разбивка по компонентам",
        T("Разбивка по компонентам", "Стоимость по этапам обработки. Видно где можно сэкономить больше всего (часто это Back-check и Safety).")),
      React.createElement("div", { className: "table-wrap" },
        React.createElement("table", { className: "tbl" },
          React.createElement("thead", null, React.createElement("tr", null,
            React.createElement("th", null, "Компонент"), React.createElement("th", { style: { width: 130 } }, "Базовая ($)"),
            React.createElement("th", { style: { width: 150 } }, "Оптимизир. ($)"), React.createElement("th", { style: { width: 130 } }, "Экономия ($)"))),
          React.createElement("tbody", null,
            [
              ["t", "Перевод", ["Перевод", "Стоимость перевода через GPT-4 (input + output tokens × цена)."]],
              ["qa", "Проверка качества", ["Проверка качества", "Автоматическая проверка перевода через GPT-4: 8 локальных проверок + консистентность + численные данные."]],
              ["bc", "Обратная проверка", ["Обратная проверка", "Обратный перевод (target→source) через GPT-4 для проверки смысловой эквивалентности. Запускается только для HIGH/CRITICAL."]],
              ["sf", "Проверка безопасности", ["Проверка безопасности", "Финальная проверка на запрещённые термины, ошибки в дозировках, медицинскую корректность."]],
              ["google", "Google Translate", ["Google Translate", "Стоимость Google Translate (бесплатно до 500K символов/мес, далее $20 за 1M символов)."]],
            ].map(([k, label, tip]) => React.createElement("tr", { key: k, style: { cursor: "default" } },
              React.createElement("td", null, React.createElement("span", { style: { fontWeight: 600 } }, label), T(tip[0], tip[1])),
              React.createElement("td", { className: "tnum dim" }, m(compBase[k])),
              React.createElement("td", { className: "tnum" }, m(comp[k])),
              React.createElement("td", { className: "tnum", style: { color: "var(--c-success)", fontWeight: 600 } }, m(compBase[k] - comp[k])))))))),

    // ---- Route Cost Breakdown ----
    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Стоимость по маршрутам",
        T("Стоимость по маршрутам", "Сколько стоит каждый маршрут в отдельности. Помогает понять основную статью расходов.")),
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
                return React.createElement("tr", { key: r.route, style: { cursor: "default" } },
                  React.createElement("td", null, React.createElement(RouteLabel, { route: r.route, withTip: false })),
                  React.createElement("td", { className: "tnum" }, segN),
                  React.createElement("td", { className: "tnum dim" }, tok.toLocaleString("ru-RU")),
                  React.createElement("td", { className: "tnum dim" }, m(base)),
                  React.createElement("td", { className: "tnum" }, m(opt)),
                  React.createElement("td", { className: "tnum", style: { color: "var(--c-success)", fontWeight: 600 } }, m(base - opt)));
              })))))),

    // ---- Zero-Token Optimization ----
    React.createElement("div", { className: "section" },
      React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 16 } },
        React.createElement("div", null,
          React.createElement("h3", { style: { fontSize: 18, fontWeight: 700 } }, "Оптимизация без токенов",
            T("Оптимизация без токенов", "Действия, которые НЕ требуют вызовов API: заполнение из TM (точные совпадения) и копирование переводов между дубликатами. Стоимость: $0.")),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } }, "Сократите количество API-вызовов перед переводом:")),
        React.createElement("div", { className: "grid grid-2" },
          React.createElement(ZeroItem, { icon: "repeat", title: "Точное TM",
            text: "Заполнить из доверенной памяти переводов (0 токенов)",
            tip: ["Точное TM", "Найти сегменты с совпадением ≥99% в TM и подставить существующий перевод. API не вызывается."] }),
          React.createElement(ZeroItem, { icon: "copy", title: "Дубликаты",
            text: "Скопировать подтверждённые переводы дубликатам (0 токенов)",
            tip: ["Дубликаты", "После подтверждения representative-сегмента, его перевод автоматически копируется всем дубликатам в группе."] })),
        React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
          React.createElement(OptBtn, { icon: "download", label: "Применить точное TM",
            tip: ["Применить точное TM", "Заполнить сегменты с TM ≥99%. Безопасно: переводы можно изменить вручную после."],
            onClick: () => toast.success("Точное TM применено", exactTM + " сегментов заполнено из памяти переводов.") }),
          React.createElement(OptBtn, { icon: "clipboard", label: "Подготовить representatives",
            tip: ["Подготовить representatives", "Отметить первый сегмент каждой группы дубликатов как 'representative'. Эти сегменты будут переводиться, остальные получат копию."],
            onClick: () => toast.info("Representatives отмечены", dupGroups + " групп дубликатов подготовлено.") }),
          React.createElement(OptBtn, { icon: "repeat", label: "Распространить дубликаты",
            tip: ["Распространить дубликаты", "Скопировать переводы representatives на все дубликаты в их группах. Запускать после подтверждения representatives."],
            onClick: () => toast.info("Распространение", "Переводы скопированы по группам дубликатов.") }),
          React.createElement(OptBtn, { icon: "list", label: "Показать группы дубликатов",
            tip: ["Показать группы дубликатов", "Открыть список всех групп дубликатов с возможностью просмотра сегментов в каждой группе."],
            onClick: () => toast.info("Группы дубликатов", dupGroups + " групп в проекте.") }))),
    ),

    // ---- Recommended Batch Order ----
    React.createElement("div", { className: "section" },
      React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 14 } },
        React.createElement("h3", { style: { fontSize: 18, fontWeight: 700 } }, "Рекомендуемый порядок обработки",
          T("Рекомендуемый порядок обработки", "Оптимальный порядок перевода сегментов: сначала representatives дубликатов, затем GPT_REQUIRED, затем HUMAN_REVIEW. Помогает максимизировать использование кэша и снизить затраты.")),
        React.createElement("p", { className: "muted", style: { fontSize: 14, margin: 0 } }, "Обработайте сегменты в этом порядке для оптимизации затрат:"),
        React.createElement("div", { className: "label", style: { marginTop: 2 } }, "Топ-10 ID сегментов:"),
        React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
          top10.map((s, i) => React.createElement("span", { key: s.id, className: "badge badge-soft mono", title: ROUTE_INFO[s.route].label, style: { height: 30, fontSize: 13 } },
            React.createElement("span", { className: "dim", style: { fontSize: 11 } }, (i + 1) + "."), "#" + s.id))),
        React.createElement("p", { className: "dim", style: { fontSize: 12, margin: 0 } }, "(Показаны первые " + top10.length + " из " + candidates.length + " рекомендуемых)"))
    )
  );
}

function PfMetric({ icon, label, value, sub, color, tip }) {
  return React.createElement("div", { className: "card metric" },
    React.createElement("div", { className: "m-label" },
      React.createElement(Icon, { name: icon, size: 16, style: { color: color || "var(--c-primary)" } }),
      label, tip && React.createElement(InfoTip, { title: tip[0], body: tip[1] })),
    React.createElement("div", { className: "m-value", style: color ? { color } : null }, value),
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

window.TabPreflight = TabPreflight;
