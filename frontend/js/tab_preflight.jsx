/* ============================================================
   Tab: Preflight / Анализ проекта — Cost + Safety Planner
   Localized, with ⓘ tooltips and a transparent cost model.
   Drill-down: клик на любой блок/строку → редактор с активным фильтром сегментов.
   ============================================================ */
/* Итог работы по проекту. Читается сверху вниз как ответ на один вопрос:
   «что сейчас с переводом». Каждая строка кликается и открывает редактор
   с этими сегментами — цифра без возможности посмотреть на неё бесполезна. */
function WorkSummary({ summary, store, toast, onReload }) {
  const s = summary;
  /* Контекстный арбитр. Спор «проверка против утверждённого термина» машина
     не решает по построению: ремонт по такой находке всегда откатится, потому
     что нарушённых приказных терминов станет больше. Но человеку одного слова
     «спор» мало — ему нужен довод. Арбитр единственный смотрит на сегмент
     в ряду соседей и отвечает, верно ли термин передан ЗДЕСЬ.
     Вызов платный, поэтому только по кнопке и с числом на ней: сколько
     сегментов он ещё не видел. Вердикт кэшируется на сегменте, так что
     повторное нажатие не платит за уже отвеченное. */
  const [arbBusy, setArbBusy] = useState(false); 
  const go = (ids, label) => {
    if (!ids || !ids.length) return;
    store.setSegmentFilter(ids);
    store.go("editor");
    toast.info(label, ids.length + " сегментов");
  };
  const Row = ({ label, n, hint, ids, color, action }) =>
    React.createElement("div", {
      className: "row between", onClick: ids && ids.length ? () => go(ids, label) : null,
      style: { padding: "9px 0", borderTop: "1px solid var(--border)", gap: 12,
               cursor: ids && ids.length ? "pointer" : "default", alignItems: "baseline" } },
      React.createElement("div", { style: { minWidth: 0 } },
        React.createElement("span", { style: { fontWeight: 600, color: color || "var(--text-1)" } }, label),
        hint && React.createElement("span", { className: "dim", style: { fontSize: 12.5 } }, " — " + hint)),
      React.createElement("div", { className: "row", style: { gap: 10, alignItems: "center" } },
        /* Действие живёт СПРАВА от числа и гасит клик по строке: строка ведёт
           в редактор, кнопка меняет текст — путать их нельзя. */
        action && React.createElement("span", { onClick: (e) => e.stopPropagation() }, action),
        React.createElement("b", { style: { fontVariantNumeric: "tabular-nums", color: n ? (color || "var(--text-1)") : "var(--text-3)" } }, n)));

  // Считаем по РАЗНЫМ сегментам: один и тот же подтверждённый сегмент может
  // и спорить с глоссарием, и нести находку проверок — сумма длин списков
  // посчитала бы его дважды и завысила бы работу человека.
  // Один раз: ниже список режется по DISPUTE_CAP и считается остаток —
  // повторный доступ с дефолтом в четырёх местах легко рассинхронизировать.
  const disputes = s.human.termcheckDisputes || [];
  const disputeSegs = s.human.termcheckDisputesSegments || [];
  const DISPUTE_CAP = 6;

  /* Пакетное принятие отменённых правок. Вызовов модели нет — подставляется
     уже написанный repair.candidate. Порядок тот же, что у выноса глоссария
     и пересчёта баллов: сначала разбор, потом подтверждение, потом применение;
     копия для отката уходит в data/backups/. */
  const [accBusy, setAccBusy] = useState(false);
  const acceptAll = () => {
    if (!window.API || accBusy) return;
    setAccBusy(true);
    window.API.safeCall(() => window.API.acceptRepairBatch(store.activeProject.id, { dry_run: true }))
      .then(dry => {
        if (!dry || !dry.ok) { setAccBusy(false); toast.error("Не удалось посчитать", "Сервер не ответил."); return; }
        if (!dry.matched) { setAccBusy(false); toast.info("Принимать нечего", "Отменённых баллом правок не осталось."); return; }
        const skipped = (dry.skippedConfirmed || []).length;
        /* Многострочное сообщение шаблонным литералом: перенос строки берётся
           из самого исходника, экранировать нечего. */
        const ok = window.confirm(
          `Принять готовые тексты в ${dry.matched} сегментах?

Вызовов модели нет — подставляется вариант, который ремонт уже написал.
Проверки этих сегментов устареют вместе с текстом: перевод станет непроверенным
до ближайшего прогона.
${skipped ? `Заверенных человеком не тронем: ${skipped}.
` : ""}
Откат есть: копия уйдёт в data/backups/, метку скажу после применения.
Кнопки отката в интерфейсе пока нет — он делается запросом по метке.`);
        if (!ok) { setAccBusy(false); return; }
        window.API.safeCall(() => window.API.acceptRepairBatch(store.activeProject.id, { dry_run: false }))
          .then(async res => {
            setAccBusy(false);
            if (!res || !res.ok) { toast.error("Не удалось применить", "Сервер отказал."); return; }
            /* Подтянуть ПРАВЛЕНЫЕ сегменты обязательно, и это не косметика:
               без этого в браузере остаётся ПРЕЖНИЙ текст, а в карточке
               сегмента черновик берётся из него — первое же «Сохранить»
               вернуло бы старый перевод поверх принятого, молча и без
               единого счётчика. Сверка расхождения копии сюда не приходит:
               число сегментов не меняется, статус — тоже. Тянем по ids,
               а не весь проект: тот весит пять мегабайт (образец — /term-case). */
            const ids = res.ids || [];
            if (ids.length && window.API.fetchSegments) {
              const got = await window.API.safeCall(
                () => window.API.fetchSegments(store.activeProject.id, ids));
              (got && got.segments || []).forEach(
                sg => store.updateSegment(store.activeProject.id, sg.id, sg));
            }
            toast.success("Принято сегментов: " + res.accepted,
              "Откат — по метке " + (res.stamp || "—")
              + " · проверить их сможет ближайший прогон");
            if (onReload) onReload();
          });
      });
  };

  const arbPending = s.human.termContextPending || 0;
  const arbWrong = s.human.termContextWrong || [];
  const askArbiter = () => {
    if (!window.API || arbBusy) return;
    setArbBusy(true);
    window.API.safeCall(() => window.API.termContext(store.activeProject.id, {}))
      .then(r => {
        setArbBusy(false);
        if (!r || !r.ok) { toast.error("Арбитр не ответил", (r && r.error) || "попробуйте ещё раз"); return; }
        // Отвечаем словами всегда, в том числе при нуле: молчаливое нажатие
        // неотличимо от сломанной кнопки.
        toast.success("Спрошено сегментов: " + r.asked,
          "снято претензий: " + (r.settled || []).length
          + " · запись под вопросом: " + (r.wrong || []).length
          + (r.capped ? " · показан не весь список, нажмите ещё раз" : ""));
        if (onReload) onReload();
      });
  };

  /* revertedByScore — ПОДМНОЖЕСТВО reverted, поэтому в сумму отдельно
     не идёт: Set и так схлопнет повторы, но полагаться на это молча нельзя. */
  const humanSegs = new Set([].concat(s.human.confirmWithdrawn || [],
                                      s.human.reverted || [],
                                      s.human.glossaryConfirmed || [],
                                      s.human.confirmedFindings || []));
  const humanTotal = s.human.termsTotal + humanSegs.size;

  return React.createElement("div", { className: "section" },
    React.createElement("h2", { className: "section-title" }, "Что сейчас с переводом",
      React.createElement(InfoTip, { title: "Итог работы",
        body: "Считается по состоянию проекта, а не по последнему прогону: прогонов может быть несколько, а вопрос один — что сделано и что осталось. Ни одного вызова модели здесь нет, открывать можно свободно.\n\n«Проверено начисто» — сегмент прошёл back-check и проверку терминов, замечаний нет. Соответствие глоссарию сюда НЕ входит: оно считается отдельно и видно своей строкой. Только сегменты «начисто» система считает готовыми учить терминологии.\n\nЛюбая строка открывает редактор с этими сегментами." })),

    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column" } },
      React.createElement("div", { className: "row between", style: { paddingBottom: 4 } },
        React.createElement("span", { className: "dim", style: { fontSize: 12.5 } }, "Всего сегментов"),
        React.createElement("b", { style: { fontVariantNumeric: "tabular-nums" } }, s.total)),
      // «Глоссарий соблюдён» отсюда убрано: _machine_clean его не смотрит вовсе
      // (ни _gloss_misses, ни _verified_hits), и сегмент с нарушенным приказным
      // термином при чистых проверках попадал сюда — а рядом же лежал
      // в «Расходятся с глоссарием». Обещать соблюдение, которого никто
      // не проверял, нельзя: на этой строке человек закрывает вопрос.
      React.createElement(Row, { label: "Проверено начисто", n: s.clean.length, ids: s.clean,
        color: "var(--c-success)", hint: "обе проверки чисто" }),
      React.createElement(Row, { label: "Исправила машина", n: s.machine.repaired, ids: s.repaired,
        hint: "статус «требует проверки» — заверяет человек" }),
      React.createElement(Row, { label: "Ещё не переведено", n: s.todo.untranslated.length,
        ids: s.todo.untranslated, hint: "запустите «Перевести и проверить»" }),
      React.createElement(Row, { label: "Переведено, но не проверено", n: s.todo.unchecked.length,
        ids: s.todo.unchecked, hint: "back-check или проверка терминов не делались" }),
      // Без этой строки сегменты с замечаниями не попадали никуда: они не «чисто»
      // и не «не проверено», и экран показывал бы благополучие, которого нет.
      React.createElement(Row, { label: "С замечаниями проверок", n: s.todo.findings.length,
        ids: s.todo.findings, hint: "это чинит «Ремонт» внутри прогона" }),
      React.createElement(Row, { label: "Расходятся с глоссарием", n: s.todo.glossaryPending.length,
        ids: s.todo.glossaryPending, hint: "утверждённого термина нет в переводе" }),
      // Корзина «всё остальное». Починенные ремонтом сюда больше НЕ попадают:
      // у них back-check прошёл и termcheck чист, а отказ _machine_clean был
      // только про право учить глоссарий — на боевом проекте они составляли
      // 60% корзины и звали разбираться там, где разбираться не в чем. Своя
      // строка у них выше — «Исправила машина». Подпись берётся из разбора
      // причин, а не придумывается здесь: сервер знает состав, экран его
      // показывает.
      React.createElement(Row, { label: "Оценка ниже порога", n: (s.todo.weak || []).length,
        ids: s.todo.weak, hint: (s.todo.weakWhy || []).slice(0, 2).map(w => w.reason).join(" · ")
          || "проверки прошли, но чисто не получилось" })),

    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", marginTop: 14 } },
      React.createElement("div", { className: "row between", style: { paddingBottom: 4 } },
        React.createElement("span", { style: { fontWeight: 650 } }, "Машина предлагает"),
        React.createElement("span", { className: "dim", style: { fontSize: 12.5 } }, "одним нажатием")),
      React.createElement("div", { className: "row between", style: { padding: "9px 0", borderTop: "1px solid var(--border)", cursor: "pointer" },
        onClick: () => store.go("glossary") },
        React.createElement("span", null, "Терминов готовы к одобрению",
          React.createElement("span", { className: "dim", style: { fontSize: 12.5 } }, " — «Глоссарий» → «Автоодобрение однозначных»")),
        React.createElement("b", { style: { fontVariantNumeric: "tabular-nums", color: s.proposed.terms ? "var(--c-primary)" : "var(--text-3)" } }, s.proposed.terms))),

    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", marginTop: 14 } },
      React.createElement("div", { className: "row between", style: { paddingBottom: 4 } },
        React.createElement("span", { style: { fontWeight: 650 } }, "Нужен человек"),
        React.createElement("b", { style: { fontVariantNumeric: "tabular-nums", color: humanTotal ? "var(--c-warning)" : "var(--c-success)" } }, humanTotal)),
      React.createElement(Row, { label: "Терминов машина решать не берётся", n: s.human.termsTotal,
        color: "var(--c-warning)", hint: "спорные варианты и конфликты — в «Глоссарии»" }),
      React.createElement(Row, { label: "Правка откачена — не стало лучше",
        n: s.human.reverted.length - (s.human.revertedByScore || []).length,
        ids: (s.human.reverted || []).filter(i => !(s.human.revertedByScore || []).includes(i)),
        color: "var(--c-warning)", hint: "модель пробовала починить и не смогла" }),
      /* Подмножество откачённых, и своей строкой: отмену там держал ТОЛЬКО
         упавший балл back-check, а термины правка почистила. Балл меряет долю
         слов оригинала, вернувшихся через обратный перевод, то есть
         вознаграждает кальку, — и «sanguiferous bed» набирал по нему больше,
         чем верное «bloodstream». Нынешний ремонт так уже не откатывает,
         а прежние записи остались: текст написан, оплачен и лежит рядом.
         В общей корзине он выглядит безнадёжным и не разбирается никогда. */
      React.createElement(Row, { label: "Ремонт отменил верную правку — текст готов",
        n: (s.human.revertedByScore || []).length, ids: s.human.revertedByScore,
        color: "var(--c-warning)",
        hint: "балл back-check упал, но термины стали чище — текст уже написан и оплачен",
        action: (s.human.revertedByScore || []).length
          ? React.createElement(Btn, { variant: "ghost", size: "sm", icon: "check",
              disabled: accBusy, onClick: acceptAll },
              accBusy ? "Принимаем…" : "Принять все")
          : null }),
      /* Машина отменила решение человека. Это самая громкая строка экрана
         и стоит она выше остальных: отмену заверения человек обязан увидеть
         сам, а не обнаружить пропажу отметки случайно. Доказательство лежит
         на сегменте (`confirmWithdrawn.evidence`). */
      React.createElement(Row, { label: "Машина сняла ваше подтверждение",
        n: (s.human.confirmWithdrawn || []).length, ids: s.human.confirmWithdrawn,
        color: "var(--c-danger)",
        hint: "расхождение чисел, единиц или отрицания — это сильнее заверения; доказательство в карточке сегмента" }),
      React.createElement(Row, { label: "Подтверждено, но спорит с глоссарием", n: s.human.glossaryConfirmed.length,
        ids: s.human.glossaryConfirmed, color: "var(--c-warning)", hint: "переписать можно только по явной галочке" }),
      // Своя строка, а не «оценка ниже порога»: это заверенные человеком
      // сегменты, до которых прогон не дотянется без разрешения. В общей куче
      // они выглядели как машинные и ждали бы вечно.
      React.createElement(Row, { label: "Подтверждено, но есть находки проверок",
        n: (s.human.confirmedFindings || []).length, ids: s.human.confirmedFindings,
        color: "var(--c-warning)",
        hint: "починит «Ремонт» с галочкой «чинить подтверждённые»" }),
      // Спор проверки с утверждённой записью. Своя строка, потому что машина
      // здесь бессильна по построению: ремонт по такой находке всегда
      // откатится (нарушённых терминов станет больше), а termcheck переспорить
      // приказ не может. Считаем по СЕГМЕНТАМ — строка открывает редактор,
      // а список терминов показан ниже.
      React.createElement(Row, { label: "Проверка спорит с утверждённым термином",
        n: disputeSegs.length, ids: disputeSegs, color: "var(--c-warning)",
        hint: "ремонт это не починит — решать вам: неверна запись или проверка" }),
      disputes.length > 0 && React.createElement(
        "div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.7, paddingTop: 8 } },
        disputes.slice(0, DISPUTE_CAP).map((d, i) => React.createElement(
          "div", { key: i },
          d.src + " → ", React.createElement("b", { style: { color: "var(--c-primary)" } }, d.tgt),
          " · проверка предлагает: " + (d.suggests.join(", ") || "без замены")
            + " · сегментов: " + d.segments.length)),
        disputes.length > DISPUTE_CAP && React.createElement(
          "div", null, "и ещё " + (disputes.length - DISPUTE_CAP) + " записей")),
      // Кнопка рисуется и при нуле ожидающих: иначе, спросив арбитра один раз,
      // человек теряет и способ переспросить, и подтверждение, что ноль
      // настоящий, — та же беда, что была у «Пересчитать» в соответствии
      // глоссарию.
      (arbPending > 0 || arbWrong.length > 0) && React.createElement(
        "div", { className: "row between", style: { paddingTop: 10, gap: 10, flexWrap: "wrap",
                                                    borderTop: "1px solid var(--border)" } },
        React.createElement("span", { className: "dim", style: { fontSize: 12.5 } },
          arbPending
            ? "Арбитр ещё не смотрел " + arbPending + " сегм. — он читает соседние сегменты и говорит, верно ли термин передан здесь"
            : "Арбитр посмотрел все спорные сегменты"),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "search",
          disabled: arbBusy || !arbPending, onClick: askArbiter },
          arbBusy ? "Спрашиваю…" : "Спросить арбитра (" + arbPending + ")")),
      arbWrong.length > 0 && React.createElement(
        "div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.7, paddingTop: 8 } },
        React.createElement("div", { style: { fontWeight: 600, color: "var(--c-warning)" } },
          "Арбитр считает запись глоссария неверной для этого документа:"),
        arbWrong.slice(0, DISPUTE_CAP).map((d, i) => React.createElement(
          "div", { key: i },
          d.src + " → ", React.createElement("b", { style: { color: "var(--c-primary)" } }, d.tgt),
          d.use ? [" · здесь верно: ", React.createElement("b", { key: "u", style: { color: "var(--c-success)" } }, d.use)] : "",
          (d.why ? " · " + d.why : "") + " · сегментов: " + d.segments.length)),
        arbWrong.length > DISPUTE_CAP && React.createElement(
          "div", null, "и ещё " + (arbWrong.length - DISPUTE_CAP) + " записей"),
        React.createElement("div", { style: { paddingTop: 6 } },
          "Правьте саму запись в «Глоссарии» — расчёт соответствия сам приведёт в порядок все затронутые сегменты. "
          + "Ремонту это не отдаётся намеренно: подстановка варианта, отличного от утверждённого, нарушила бы приказ и была бы откачена.")),
      s.human.terms.length > 0 && React.createElement("div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.6, paddingTop: 10, borderTop: "1px solid var(--border)" } },
        "Почему термины остались человеку: ",
        s.human.terms.slice(0, 4).map(t => t.count + "× " + t.reason).join(" · "))));
}

/* «Анализ» — всё про состояние проекта в одном месте: смета до прогона, итог
   после, открытые замечания, доска задач и статистика. Раньше это были четыре
   вкладки, отвечавшие на один вопрос «что не так и во что обойдётся», и
   проверять приходилось четыре места. */
function TabAnalysis({ store, toast }) {
  const [view, setView] = useState("plan");
  const counts = store.activeProject ? store.statusCounts(store.activeProject) : null;
  const views = [
    ["plan", "Итог и смета", null],
    ["qa", "Замечания", counts ? (counts.failed + counts.qa) || null : null],
    ["backlog", "Доска", null],
    ["stats", "Статистика", null],
  ];
  const Body = { plan: TabPreflight, qa: window.TabQA, backlog: window.TabBacklog,
                 stats: window.TabStats }[view] || TabPreflight;
  return React.createElement("div", null,
    React.createElement("div", { className: "row row-wrap", style: { gap: 8, padding: "18px 24px 0" } },
      views.map(([key, label, n]) => React.createElement(Btn, {
        key, variant: view === key ? "primary" : "ghost", size: "sm",
        onClick: () => setView(key) }, label + (n ? " · " + n : "")))),
    React.createElement(Body, { store, toast }));
}

function TabPreflight({ store, toast }) {
  const project = store.activeProject;
  const [analyzing, setAnalyzing] = useState(false);
  // Итог работы: что чисто, что исправила машина, что осталось человеку.
  // Считает сервер тем же движком, что и сами прогоны, — иначе цифры на экране
  // разошлись бы с тем, что произойдёт по нажатию кнопки.
  const [summary, setSummary] = useState(null);
  // Счётчик перезагрузок: арбитр меняет состав корзин, и без обновления экран
  // показывал бы состояние до нажатия — то есть выглядел бы сломанной кнопкой.
  const [sumNonce, setSumNonce] = useState(0);
  useEffect(() => {
    if (!window.API || !window.API.analysis || !project) return;
    let dead = false;
    window.API.safeCall(() => window.API.analysis(project.id))
      .then(r => { if (!dead && r && r.ok) setSummary(r); });
    return () => { dead = true; };
  }, [project && project.id, sumNonce]);

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
  // google-строка осталась только ради истории: бесплатного движка в системе
  // нет, и считать по нему дешёвым будущий перевод — врать в смете на порядок.
  // Сегмент с маршрутом GOOGLE_SAFE переводится теперь той же моделью, что и все.
  const RATE = { t: 0.0009, qa: 0.0006, bc: 0.0005, sf: 0.0003, google: 0 };
  const isHi = (s) => s.risk === "high" || s.risk === "critical";
  const segCost = (s) => {
    const w = wordsOf(s);
    const baseline = { t: w * RATE.t, qa: w * RATE.qa, bc: w * RATE.bc, sf: w * RATE.sf, google: 0 };
    let opt = { t: 0, qa: 0, bc: 0, sf: 0, google: 0 };
    if (s.route === "GOOGLE_SAFE") { opt.t = w * RATE.t; opt.qa = w * RATE.qa; }
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

    // ---- Итог работы: что уже сделано и что осталось ----
    summary && React.createElement(WorkSummary, { summary, store, toast,
      onReload: () => setSumNonce(n => n + 1) }),

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
      React.createElement("h2", { className: "section-title" }, "Сложность исходных сегментов",
        T("Сложность исходных сегментов",
          "Считается по длине исходного текста: до 8 слов — низкая, 9–30 — средняя, больше 30 — высокая. Содержание сегмента при этом не разбирается.\n\nЭто характеристика ОРИГИНАЛА, а не перевода: она определяет, каким движком сегмент переводить, и не меняется от того, что вы перевели его заново.\n\nКачество самого перевода показывает блок «Соответствие обратного перевода» ниже.")),
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
          tip: ["Оптимизированная стоимость", "Прогноз с учётом того, что считается без вызова модели: дубликаты внутри порции и точные совпадения с памятью переводов."] }),
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
              ["google", "Бесплатный движок (убран)", ["Бесплатный движок убран из системы", "Строка осталась для истории: так переведены сегменты с маршрутом GOOGLE_SAFE. Новые переводы делает только выбранная модель."]],
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
    React.createElement(BackcheckBands, { segments: segs, project, onDrill: openDrill, T }),

    React.createElement(GlossaryImpact, { project, store, toast, onDrill: openDrill, T }),

    React.createElement(TermcheckSummary, { segments: segs, onDrill: openDrill, T }),

    React.createElement(RepairSummary, { segments: segs, onDrill: openDrill, T }),

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
// Границы полос и раскраску держит ui.jsx (window.BC_BANDS_FALLBACK,
// bcBandColor, setBcBands) — там же, где ими красят балл редактор и карточка
// сегмента. Дубликат списка здесь означал бы разные цвета у одного балла
// на соседних экранах.

function BackcheckBands({ segments, project, onDrill, T }) {
  const [bands, setBands] = useState(window.bcBands());
  // Пересчёт оценок по нынешним правилам. Кнопка нужна потому, что правила
  // подсчёта версионированы, а хеш перевода сторожит только ТЕКСТ: запись,
  // посчитанная прежними правилами, считается свежей вечно и сама
  // не пересчитается. Порядок как у выноса глоссария: сперва разбор (ничего
  // не меняет и показывает числа), потом решение человека.
  const [resc, setResc] = useState(null);
  const [rescBusy, setRescBusy] = useState(false);

  const rescore = (apply) => {
    if (!window.API || !window.API.rescoreBackchecks || !project) return;
    setRescBusy(true);
    window.API.safeCall(() => window.API.rescoreBackchecks(project.id, !apply)).then(r => {
      setRescBusy(false);
      if (r && r.ok) setResc(r);
    });
  };
  useEffect(() => {
    if (!window.API || !window.API.models) return;
    window.API.safeCall(() => window.API.models()).then(d => {
      if (!d || !d.backcheckBands || !d.backcheckBands.length) return;
      window.setBcBands(d.backcheckBands);
      setBands(d.backcheckBands);
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
                React.createElement("span", { className: "mono", style: { width: 72, fontSize: 13, fontWeight: 700, color: window.bcBandColor(b.color) } }, b.label),
                React.createElement("span", { className: "dim", style: { width: 190, fontSize: 12.5 } }, b.note),
                React.createElement("div", { style: { flex: 1, height: 10, background: "var(--bg-sunken)", borderRadius: 5, overflow: "hidden" } },
                  React.createElement("div", { style: { width: pct + "%", height: "100%", background: window.bcBandColor(b.color) } })),
                React.createElement("b", { className: "tnum", style: { width: 56, textAlign: "right", fontSize: 13 } }, list.length)
              );
            })
          ),

      React.createElement("div", {
        className: "row between", style: { borderTop: "1px solid var(--border)", paddingTop: 10, flexWrap: "wrap", gap: 10 } },
        React.createElement("div", { style: { minWidth: 0 } },
          React.createElement("div", { className: "row", style: { gap: 6 } },
            React.createElement("span", { style: { fontSize: 13, fontWeight: 600 } }, "Оценки по прежним правилам"),
            T("Пересчёт оценок back-check",
              "Правила подсчёта меняются, а хеш перевода сторожит только текст — запись, посчитанная по-старому, считается свежей вечно и сама не пересчитается.\n\nПересчёт бесплатный: обратный перевод, оригинал и вердикт судьи лежат в самой записи, ни одного вызова модели он не делает.\n\nСперва разбор — он ничего не меняет и показывает числа. Прежние записи уходят копией в data/backups и возвращаются откатом.")),
          React.createElement("p", { className: "muted", style: { marginTop: 4, fontSize: 13 } },
            rescBusy ? "Считаем…"
              : !resc ? "Нажмите «Разобрать», чтобы узнать, сколько оценок посчитано прежними правилами"
              : !resc.rescored ? "Все оценки посчитаны нынешними правилами"
              : (resc.dry_run ? "Посчитано прежними правилами: " : "Пересчитано: ") + resc.rescored
                + "; балл " + (resc.dry_run ? "изменится" : "изменился") + " у " + resc.changed
                + "; к судье " + (resc.dry_run ? "вернётся " : "вернулось ") + resc.freed_judge
                + "; машинно-чистых было " + resc.machine_clean.before + ", стало " + resc.machine_clean.after)),
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat", disabled: rescBusy,
            onClick: () => rescore(false) }, "Разобрать"),
          resc && resc.dry_run && resc.rescored > 0 && React.createElement(Btn, {
            variant: "primary", size: "sm", disabled: rescBusy, onClick: () => rescore(true) },
            "Пересчитать " + resc.rescored))),

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


/* ---------- Строка показателя с переходом в редактор ---------- */
// Клик по строке = «показать эти сегменты»: тот же drill-down, что у полос
// back-check, чтобы цифра из анализа всегда открывалась списком в редакторе.
function StatRow({ label, note, count, color, onDrill, bold }) {
  const clickable = count > 0 && !!onDrill;
  return React.createElement("div", {
    className: "row between",
    style: { gap: 10, padding: "5px 0", cursor: clickable ? "pointer" : "default", opacity: count ? 1 : 0.45 },
    onClick: clickable ? onDrill : undefined,
    title: clickable ? "Открыть эти сегменты в редакторе" : "Нет таких сегментов" },
    React.createElement("div", { className: "row", style: { gap: 8, minWidth: 0 } },
      React.createElement("span", { style: { fontSize: 13, fontWeight: bold ? 700 : 500, color: color || "var(--text)" } }, label),
      note && React.createElement("span", { className: "dim", style: { fontSize: 12 } }, note)),
    React.createElement("b", { className: "tnum", style: { fontSize: 13, color: color || "var(--text)" } }, count));
}

/* ============================================================
   Соответствие одобренным терминам глоссария
   ============================================================ */
// Одобрение термина не переписывает готовые переводы. Этот блок показывает,
// где они разошлись с глоссарием, и открывает такие сегменты в редакторе —
// сам переперевод запускается там, карточкой «Соответствие глоссарию».
function GlossaryImpact({ project, store, toast, onDrill, T }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [fixing, setFixing] = useState(false);

  const load = () => {
    if (!window.API || !window.API.glossaryImpact || !project) return;
    setBusy(true);
    window.API.safeCall(() => window.API.glossaryImpact(project.id)).then(r => {
      setBusy(false);
      if (r && r.ok) setData(r);
    });
  };
  useEffect(() => { setData(null); load(); }, [project && project.id]);

  const segsById = new Map((project ? project.segments : []).map(s => [s.id, s]));
  const pick = (ids) => (ids || []).map(id => segsById.get(id)).filter(Boolean);

  /* Начертание приказных терминов под оригинал. Вызовов модели тут НЕТ:
     меняются только заглавные и строчные, слова и порядок те же. Поэтому
     кнопка не спрашивает про модель и не считает цену — но спрашивает
     подтверждение: текст в проекте всё-таки меняется, и показать, ЧТО именно
     изменится, дешевле, чем объяснять потом. Отсюда два захода: разбор
     (dry_run) и, если человек согласился, сама правка. */
  const fixCase = async () => {
    if (!window.API || !window.API.termCase || !project) return;
    setFixing(true);
    const dry = await window.API.safeCall(() => window.API.termCase(project.id));
    if (!dry || !dry.ok) {
      setFixing(false);
      toast && toast.error("Не вышло разобрать начертание", (dry && dry.error) || "попробуйте ещё раз");
      return;
    }
    if (!dry.segments) {
      setFixing(false);
      toast && toast.info("Начертание терминов", "и так по оригиналу — менять нечего");
      return;
    }
    const sample = (dry.samples || []).slice(0, 5)
      .map(x => "  #" + x.id + ": " + (x.fixed || []).map(f => f.was + " → " + f.now).join(", "))
      .join("\n");
    const skipped = (dry.skippedConfirmed || []).length;
    const ok = window.confirm(
      "Привести начертание терминов к оригиналу: " + dry.segments + " сегм.\n"
      + "Меняются только заглавные и строчные — слова и порядок те же.\n\n"
      + sample + (dry.segments > 5 ? "\n  …" : "")
      + (skipped ? "\n\nЗаверенных человеком не трогаем: " + skipped : ""));
    if (!ok) { setFixing(false); return; }
    const res = await window.API.safeCall(() => window.API.termCase(project.id, { apply: true }));
    setFixing(false);
    if (!res || !res.ok) {
      toast && toast.error("Правка не выполнена", (res && res.error) || "попробуйте ещё раз");
      return;
    }
    /* Подтягиваем ТОЛЬКО правленые сегменты: проект на 2670 строк весит
       5 МБ, и тянуть его целиком ради десятка изменившихся — трафик впустую. */
    if ((res.ids || []).length && window.API.fetchSegments && store) {
      const got = await window.API.safeCall(() => window.API.fetchSegments(project.id, res.ids));
      (got && got.segments || []).forEach(sg => store.updateSegment(project.id, sg.id, sg));
    }
    toast && toast.success("Начертание приведено к оригиналу",
                           res.segments + " сегм. — без единого вызова модели");
    load();
  };

  return React.createElement("div", { className: "section" },
    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
      React.createElement("div", { className: "row between", style: { alignItems: "flex-end", flexWrap: "wrap", gap: 10 } },
        React.createElement("div", null,
          React.createElement("h3", { style: { fontSize: 18, fontWeight: 700 } }, "Соответствие глоссарию",
            T("Соответствие одобренным терминам",
              "Сегменты, где термин есть в оригинале, а утверждённого перевода в готовом тексте нет.\n\nОдобрение термина влияет только на будущие переводы — уже сделанные сами не меняются, поэтому после правок глоссария этот список и появляется.\n\nСчитается только по проверенным записям: автоимпорт модель вправе игнорировать.\n\nПереперевести пакетом можно в Редакторе, карточка «Соответствие глоссарию».")),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } },
            busy ? "Считаем…" : !data ? "—"
              : data.segments.length ? "Расходятся с глоссарием: " + data.segments.length + " сегм. по " + data.terms.length + " терминам"
              : "Все переводы соответствуют одобренным терминам")),
        React.createElement("div", { className: "row", style: { gap: 8 } },
          data && (data.caseSegments || []).length > 0 && React.createElement(Btn, {
            variant: "primary", size: "sm", icon: "edit", disabled: fixing || busy, onClick: fixCase },
            fixing ? "Правим…" : "Привести начертание"),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat", disabled: busy, onClick: load }, "Пересчитать"))),

      /* Отдельной строкой, а не вперемешку с расхождениями выше: там термина
         в переводе НЕТ вовсе и нужен платный переперевод, здесь он есть, но
         не в том начертании — и чинится бесплатно, одной кнопкой. */
      data && React.createElement(StatRow, {
        label: "Начертание не по оригиналу",
        note: (data.caseSegments || []).length ? "чинится без вызовов модели" : "всё по оригиналу",
        count: (data.caseSegments || []).length,
        color: (data.caseSegments || []).length ? "var(--c-warning)" : undefined,
        onDrill: () => onDrill("Начертание терминов не по оригиналу", pick(data.caseSegments)) }),

      data && data.terms.length > 0 && React.createElement("div", { style: { display: "flex", flexDirection: "column" } },
        React.createElement(StatRow, { label: "Всего расхождений", bold: true, count: data.segments.length,
          color: "var(--c-warning)", onDrill: () => onDrill("Расходятся с глоссарием", pick(data.segments)) }),
        React.createElement(StatRow, { label: "— не подтверждено", note: "можно переперевести сразу",
          count: data.pending.length, onDrill: () => onDrill("Расходятся с глоссарием (не подтверждено)", pick(data.pending)) }),
        React.createElement(StatRow, { label: "— подтверждено", note: "перезапись только по явной команде",
          count: data.confirmed.length, color: "var(--c-error)",
          onDrill: () => onDrill("Расходятся с глоссарием (подтверждено)", pick(data.confirmed)) })),

      data && data.terms.length > 0 && React.createElement("div", { style: { borderTop: "1px solid var(--border)", paddingTop: 10 } },
        React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, marginBottom: 6 } }, "По терминам"),
        data.terms.slice(0, 10).map((t, i) => React.createElement("div", {
          key: i, className: "row between", style: { padding: "3px 0", fontSize: 13, cursor: "pointer" },
          onClick: () => onDrill("Термин: " + t.src, pick(t.segments)),
          title: "Открыть сегменты с этим термином" },
          React.createElement("div", { className: "row", style: { gap: 8, minWidth: 0, flexWrap: "wrap" } },
            React.createElement("span", null, t.src),
            React.createElement("span", { style: { color: "var(--c-success)", fontWeight: 600 } }, "→ " + t.tgt),
            t.prevTgt && React.createElement("s", { className: "dim" }, t.prevTgt)),
          React.createElement("b", { className: "tnum" }, t.segments.length))))
    )
  );
}

/* ============================================================
   Проверка терминологии — сводка по проекту
   ============================================================ */
function TermcheckSummary({ segments, onDrill, T }) {
  const translated = segments.filter(s => (s.target || "").trim());
  const checked = translated.filter(s => s.termcheck);
  const fresh = checked.filter(s => !s.termcheck.stale);
  const stale = checked.filter(s => s.termcheck.stale);
  const skipped = fresh.filter(s => s.termcheck.model === "skip");
  const withFindings = fresh.filter(s => (s.termcheck.findings || []).length > 0);
  const clean = fresh.filter(s => s.termcheck.model !== "skip" && !(s.termcheck.findings || []).length);
  const bySev = (sev) => withFindings.filter(s => (s.termcheck.findings || []).some(f => f.severity === sev));

  // Самые частые замечания: один и тот же термин обычно тянется по всему документу,
  // и чинить его выгоднее один раз через глоссарий, а не по сегменту.
  const byTerm = new Map();
  withFindings.forEach(s => (s.termcheck.findings || []).forEach(f => {
    if (f.severity === "minor") return;
    const key = (f.tgt_term || "").toLowerCase();
    if (!key) return;
    const e = byTerm.get(key) || { term: f.tgt_term, suggestion: f.suggestion, segs: [] };
    if (!e.segs.some(x => x.id === s.id)) e.segs.push(s);
    byTerm.set(key, e);
  }));
  const topTerms = Array.from(byTerm.values()).sort((a, b) => b.segs.length - a.segs.length).slice(0, 6);

  return React.createElement("div", { className: "section" },
    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
      React.createElement("div", { className: "row between", style: { alignItems: "flex-end", flexWrap: "wrap", gap: 10 } },
        React.createElement("div", null,
          React.createElement("h3", { style: { fontSize: 18, fontWeight: 700 } }, "Проверка терминологии",
            T("Проверка терминологии",
              "Модель смотрит только на перевод и отвечает, нормальный ли это термин целевого языка: кальки, транслитерации, подмены понятия, склеенные обрывки.\n\nЭто не back-check: тот спрашивает, пережил ли смысл обратный перевод, и на кальке всегда отвечает «да». Запускается в Редакторе, карточка «Проверка терминологии».")),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } },
            "Проверено " + checked.length + " из " + translated.length + " переведённых сегментов")),
        withFindings.length > 0 && React.createElement("div", { className: "dim", style: { fontSize: 13 } },
          "Замечания в " + Math.round(withFindings.length / Math.max(1, fresh.length) * 100) + "% проверенного")),

      checked.length === 0
        ? React.createElement(EmptyState, { icon: "book", title: "Проверка терминологии ещё не запускалась",
            sub: "Запустите её в Редакторе — карточка «Проверка терминологии» в блоке пакетных прогонов." })
        : React.createElement("div", { style: { display: "flex", flexDirection: "column" } },
            React.createElement(StatRow, { label: "С замечаниями", note: "нужна правка или решение", bold: true,
              count: withFindings.length, color: "var(--c-warning)",
              onDrill: () => onDrill("Терминология: есть замечания", withFindings) }),
            React.createElement(StatRow, { label: "— критично", note: "другое понятие или нечитаемый фрагмент",
              count: bySev("critical").length, color: "var(--c-error)",
              onDrill: () => onDrill("Терминология: критичные замечания", bySev("critical")) }),
            React.createElement(StatRow, { label: "— серьёзно", note: "не термин целевого языка",
              count: bySev("major").length, color: "var(--c-warning)",
              onDrill: () => onDrill("Терминология: серьёзные замечания", bySev("major")) }),
            React.createElement(StatRow, { label: "Без замечаний", count: clean.length, color: "var(--c-success)",
              onDrill: () => onDrill("Терминология: без замечаний", clean) }),
            React.createElement(StatRow, { label: "Нечего проверять", note: "числа, обозначения — без вызова модели",
              count: skipped.length, onDrill: () => onDrill("Терминология: нечего проверять", skipped) }),
            React.createElement(StatRow, { label: "Проверка устарела", note: "перевод меняли после проверки",
              count: stale.length, onDrill: () => onDrill("Терминология: устаревшие проверки", stale) }),
            React.createElement(StatRow, { label: "Ещё не проверялись", count: translated.length - checked.length,
              onDrill: () => onDrill("Терминология: не проверялись", translated.filter(s => !s.termcheck)) })),

      topTerms.length > 0 && React.createElement("div", { style: { borderTop: "1px solid var(--border)", paddingTop: 10 } },
        React.createElement("div", { className: "row", style: { fontSize: 12.5, fontWeight: 600, marginBottom: 6 } },
          "Чаще всего повторяется",
          T("Повторяющиеся замечания",
            "Один и тот же неверный термин обычно тянется по всему документу. Выгоднее одобрить правильный вариант в «Глоссарий → Кандидаты» и перевести затронутые сегменты заново, чем чинить каждый по отдельности.")),
        topTerms.map((t, i) => React.createElement("div", {
          key: i, className: "row between",
          style: { padding: "3px 0", cursor: "pointer", fontSize: 13 },
          onClick: () => onDrill("Термин: " + t.term, t.segs),
          title: "Открыть сегменты с этим термином" },
          React.createElement("div", { className: "row", style: { gap: 8, minWidth: 0, flexWrap: "wrap" } },
            React.createElement("s", { style: { color: "var(--c-error)" } }, t.term),
            t.suggestion && React.createElement("span", { style: { color: "var(--c-success)", fontWeight: 600 } }, "→ " + t.suggestion)),
          React.createElement("b", { className: "tnum", style: { fontSize: 13 } }, t.segs.length))))
    )
  );
}

/* ============================================================
   Автоматический ремонт — сводка по проекту
   ============================================================ */
// Уровни находок termcheck, по которым работает ремонт. Значение приходит
// с сервера (/api/models → termcheckActionable, он же TERMCHECK_ACTIONABLE);
// здесь — только запас на случай, если ответ ещё не пришёл. Тем же порядком
// в этом файле берутся полосы back-check: держать такой список литералом
// значит однажды показать число, которого прогон не сделает.
const TC_ACTIONABLE_FALLBACK = ["critical", "major", "minor"];

function RepairSummary({ segments, onDrill, T }) {
  const [tcActionable, setTcActionable] = useState(TC_ACTIONABLE_FALLBACK);
  useEffect(() => {
    if (!window.API || !window.API.models) return;
    window.API.safeCall(() => window.API.models()).then(d => {
      if (d && d.termcheckActionable && d.termcheckActionable.length) setTcActionable(d.termcheckActionable);
    });
  }, []);
  const touched = segments.filter(s => s.repair);
  const applied = touched.filter(s => s.repair.applied);
  const reverted = touched.filter(s => !s.repair.applied);
  const needReview = applied.filter(s => s.status === "review");

  // Насколько ремонт поднял балл back-check — единственный объективный итог
  const withScores = applied.filter(s => s.repair.before && s.repair.after
    && s.repair.before.score != null && s.repair.after.score != null);
  const gain = withScores.length
    ? Math.round(withScores.reduce((a, s) => a + (s.repair.after.score - s.repair.before.score), 0) / withScores.length)
    : null;

  // Ждут ремонта: есть свежие находки, но через ремонт этот текст не проходил
  const REASONS = ["расхождение чисел", "расхождение единиц", "инверсия отрицания",
                   "подмена на противоположное", "обратный перевод про другое", "потерян термин"];
  const pending = segments.filter(s => {
    if (!(s.target || "").trim() || (s.repair && s.repair.tried)) return false;
    const bc = s.backcheck && !s.backcheck.stale ? s.backcheck : null;
    const tc = s.termcheck && !s.termcheck.stale ? s.termcheck : null;
    const bcHit = bc && ((bc.terms_lost || []).length > 0
      || (bc.reasons || []).some(r => REASONS.some(h => r.indexOf(h) !== -1))
      || (bc.judge && ["major", "critical"].indexOf(bc.judge.severity) !== -1));
    // Уровни — те же, что на сервере (TERMCHECK_ACTIONABLE): ремонт чинит и
    // minor, и без него счётчик «Ждут ремонта» занижен ровно на те сегменты,
    // ради которых ремонту это и разрешили.
    const tcHit = tc && (tc.findings || []).some(f => tcActionable.indexOf(f.severity) !== -1);
    return !!(bcHit || tcHit);
  });

  return React.createElement("div", { className: "section" },
    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
      React.createElement("div", { className: "row between", style: { alignItems: "flex-end", flexWrap: "wrap", gap: 10 } },
        React.createElement("div", null,
          React.createElement("h3", { style: { fontSize: 18, fontWeight: 700 } }, "Автоматический ремонт",
            T("Автоматический ремонт",
              "Переписывает перевод по конкретным находкам back-check и проверки терминологии, затем перепроверяет теми же проверками. Новый текст остаётся, только если оценка не упала.\n\nИсправленные сегменты получают статус «Требует проверки»: автоправка не заверяет сама себя, подтвердить должен человек.")),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } },
            touched.length ? "Ремонт применялся к " + touched.length + " сегментам" : "Ремонт ещё не запускался")),
        gain !== null && React.createElement("div", { className: "dim", style: { fontSize: 13 } },
          "Средний прирост back-check: " + (gain > 0 ? "+" : "") + gain + "%")),

      touched.length === 0 && pending.length === 0
        ? React.createElement(EmptyState, { icon: "repeat", title: "Чинить пока нечего",
            sub: "Сначала прогоните back-check или проверку терминологии — ремонт работает по их находкам." })
        : React.createElement("div", { style: { display: "flex", flexDirection: "column" } },
            React.createElement(StatRow, { label: "Исправлено", note: "текст заменён, проверка подтвердила улучшение", bold: true,
              count: applied.length, color: "var(--c-success)",
              onDrill: () => onDrill("Ремонт: исправлено", applied) }),
            React.createElement(StatRow, { label: "— ждут подтверждения", note: "статус «Требует проверки»",
              count: needReview.length, color: "var(--c-warning)",
              onDrill: () => onDrill("Ремонт: ждут подтверждения", needReview) }),
            React.createElement(StatRow, { label: "Откачено", note: "вариант модели не улучшил оценку",
              count: reverted.length, onDrill: () => onDrill("Ремонт: откачено", reverted) }),
            React.createElement(StatRow, { label: "Ждут ремонта", note: "есть находки, ремонт не запускался",
              count: pending.length, color: "var(--c-primary)",
              onDrill: () => onDrill("Ремонт: ждут ремонта", pending) }))
    )
  );
}

window.TabPreflight = TabPreflight;
window.TabAnalysis = TabAnalysis;
