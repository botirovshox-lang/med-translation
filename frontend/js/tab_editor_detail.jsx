/* ============================================================
   Segment detail panel (editor right sidebar)
   ============================================================ */
function SegDetail({ seg, project, store, toast, busy, onTranslate, onQA, onMedicalQA, onConfirm }) {
  const [tab, setTab] = useState("context");
  const [draft, setDraft] = useState(seg.target || "");
  const [comment, setComment] = useState("");
  const [infoPanel, setInfoPanel] = useState(null); // 'tm'|'back'|'route'|'risk'|null
  const [backResult, setBackResult] = useState(null); // null|'loading'|string
  const idx = project.segments.findIndex(s => s.id === seg.id) + 1;
  const words = (draft.trim() ? draft.trim().split(/\s+/).length : 0);
  const dirty = draft !== (seg.target || "");

  useEffect(() => { setDraft(seg.target || ""); setInfoPanel(null); setBackResult(null); }, [seg.id]);
  useEffect(() => { setDraft(seg.target || ""); }, [seg.target, seg.status]);

  const saveDraft = () => {
    store.updateSegment(project.id, seg.id, { target: draft, status: seg.status === "new" ? "translated" : seg.status });
    toast.success("Сохранено", "Перевод сегмента #" + seg.id + " обновлён.");
  };
  const copySrc = () => { navigator.clipboard && navigator.clipboard.writeText(seg.source); toast.info("Скопировано", "Оригинал в буфере обмена."); };
  const addComment = () => {
    if (!comment.trim()) return;
    store.addComment(project.id, seg.id, comment.trim());
    setComment(""); toast.info("Комментарий добавлен");
  };

  const glossHits = store.glossary.filter(g => seg.source.toLowerCase().includes(g.src.toLowerCase()));
  const tmHit = seg.tm || store.tm.find(t => t.src === seg.source);

  // Cost estimate from source word count + route
  const srcWords = seg.source.trim() ? seg.source.trim().split(/\s+/).length : 0;
  const rate = seg.route === "GPT_REQUIRED" ? 0.0009 : seg.route === "GOOGLE_SAFE" ? 0.00002 : 0;
  const estCost = srcWords * rate;
  const riskMeta = { low: ["badge-confirmed", "LOW"], medium: ["badge-review", "MEDIUM"], high: ["badge-qa", "HIGH"], critical: ["badge-failed", "CRITICAL"] };
  const riskColorMeta = { green: ["badge-confirmed", "GREEN"], yellow: ["badge-review", "YELLOW"], red: ["badge-failed", "RED"] };
  const qaIssues = seg.qa_issues || seg.qa || [];
  const qaResult = seg.qa_result || null;

  const toggleInfo = (k) => setInfoPanel(p => p === k ? null : k);
  const openBack = () => {
    toggleInfo("back");
    if (infoPanel !== "back" && backResult == null) {
      if (!seg.target) { setBackResult("no_target"); return; }
      setBackResult("loading");
      window.API && window.API.backcheck(project.id, seg.id).then(res => {
        setBackResult(res && res.ok ? res.back : ("Ошибка: " + (res && res.error ? res.error : "нет ответа")));
      }).catch(e => setBackResult("Ошибка: " + e.message));
    }
  };

  const minitabs = [
    ["context", "Контекст"], ["tm", "TM" + (tmHit ? " (1)" : "")],
    ["qa", "QA" + (qaIssues.length ? " (" + qaIssues.length + ")" : "")], ["comments", "Чат" + (seg.comments.length ? " (" + seg.comments.length + ")" : "")],
  ];

  const STATUS_TIP = {
    new: ["Новый", "Сегмент не переведён. Никаких операций не выполнялось."],
    translated: ["Переведён", "Перевод получен (Google/GPT/вручную). QA ещё не запускалось."],
    qa: ["QA пройдено", "Автоматическая проверка качества выполнена. Можно подтверждать."],
    confirmed: ["Подтверждён", "Финальный статус. Добавлен в TM. Будет в экспорте."],
    review: ["Требует review", "Обнаружены проблемы — необходим человеческий просмотр."],
    failed: ["Ошибка", "Перевод/QA завершились с ошибкой. См. логи."],
  };

  return React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 16 } },
    React.createElement("div", { className: "row between" },
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 700, fontSize: 16 } }, "Сегмент #" + seg.id),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, idx + " из " + project.segments.length)),
      React.createElement("div", { className: "row", style: { gap: 2 } },
        React.createElement(StatusBadge, { status: seg.status }),
        React.createElement(InfoTip, { title: (STATUS_TIP[seg.status] || STATUS_TIP.new)[0], body: (STATUS_TIP[seg.status] || STATUS_TIP.new)[1] }))
    ),

    // source
    React.createElement("div", null,
      React.createElement("div", { className: "row between", style: { marginBottom: 6 } },
        React.createElement("span", { className: "label" }, "🇷🇺 Оригинал"),
        React.createElement(Btn, { variant: "ghost", size: "sm", icon: "copy", onClick: copySrc }, "Копировать")),
      React.createElement("div", { className: "card", style: { padding: 12, background: "var(--bg-sunken)", lineHeight: 1.55, fontSize: 14 } }, seg.source)
    ),

    // translation
    React.createElement("div", null,
      React.createElement("div", { className: "label", style: { marginBottom: 6 } }, "🇬🇧 Перевод"),
      React.createElement(Textarea, { value: draft, onChange: (e) => setDraft(e.target.value), placeholder: "Введите перевод…", style: { minHeight: 120 } }),
      React.createElement("div", { className: "row between", style: { marginTop: 8 } },
        React.createElement("span", { className: "dim", style: { fontSize: 12 } }, words + " слов · " + draft.length + " симв."),
        dirty && React.createElement(Btn, { variant: "secondary", size: "sm", icon: "check", onClick: saveDraft }, "Сохранить"))
    ),

    // actions
    React.createElement("div", { className: "grid grid-2", style: { gap: 8 } },
      React.createElement(Btn, { variant: "primary", size: "sm", icon: "globe", disabled: busy, onClick: () => onTranslate("google") }, "Google"),
      React.createElement(Btn, { variant: "primary", size: "sm", icon: "cpu", disabled: busy, onClick: () => onTranslate("gpt"), style: { background: "var(--c-purple)" } }, "GPT"),
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "shield", disabled: busy, onClick: onMedicalQA, style: { color: "var(--c-info)", boxShadow: "inset 0 0 0 1.5px var(--c-info)" } }, "Medical QA"),
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "shield", disabled: busy, onClick: onQA }, "Quick QA"),
      React.createElement(Btn, { variant: "success", size: "sm", icon: "check", disabled: busy, onClick: () => onConfirm(draft) }, "Подтвердить")
    ),

    // compact secondary actions (MemSource-style)
    React.createElement("div", { className: "mini-actions" },
      React.createElement("button", { className: "mini-btn" + (infoPanel === "tm" ? " on" : ""), onClick: () => toggleInfo("tm") },
        React.createElement(Icon, { name: "search", size: 14 }), "Find TM"),
      React.createElement("button", { className: "mini-btn" + (infoPanel === "back" ? " on" : ""), onClick: openBack },
        React.createElement(Icon, { name: "repeat", size: 14 }), "Back check"),
      React.createElement("button", { className: "mini-btn" + (infoPanel === "route" ? " on" : ""), onClick: () => toggleInfo("route") },
        React.createElement(Icon, { name: "target", size: 14 }), "Route"),
      React.createElement("button", { className: "mini-btn" + (infoPanel === "risk" ? " on" : ""), onClick: () => toggleInfo("risk") },
        React.createElement(Icon, { name: "warn", size: 14 }), "Risk"),
      React.createElement("span", { className: "mini-btn readonly", title: "Оценка стоимости перевода" },
        React.createElement(Icon, { name: "zap", size: 14 }), "Est: ", React.createElement("span", { className: "mb-val" }, fmtCost(estCost)))
    ),

    infoPanel === "route" && React.createElement("div", { className: "row", style: { gap: 8 } },
      React.createElement("span", { className: "badge badge-translated" }, seg.route),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "маршрут обработки (инфо)")),
    infoPanel === "risk" && React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
      React.createElement("span", { className: "badge " + (riskColorMeta[seg.risk_color] || riskMeta[seg.risk] || riskMeta.medium)[0] }, (riskColorMeta[seg.risk_color] || riskMeta[seg.risk] || riskMeta.medium)[1]),
      seg.risk_score != null && React.createElement("span", { className: "badge badge-soft" }, "Score " + seg.risk_score),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "уровень риска (инфо)")),
    infoPanel === "tm" && React.createElement("div", { className: "tm-pop" },
      React.createElement("div", { className: "row between" },
        React.createElement("span", { className: "label", style: { margin: 0 } }, "Совпадения TM"),
        React.createElement(TMChip, { score: seg.tmScore })),
      tmHit
        ? React.createElement("div", { className: "tmrow" },
            React.createElement("div", { className: "row between", style: { marginBottom: 6 } },
              React.createElement(Badge, { variant: "confirmed", icon: "checkCircle" }, (seg.tmScore || 100) + "%"),
              React.createElement(Btn, { variant: "secondary", size: "sm", icon: "check", onClick: () => { setDraft(tmHit.target); toast.info("Применено из TM"); } }, "Применить")),
            React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, tmHit.target))
        : React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, "Точных совпадений в памяти переводов нет.")),
    infoPanel === "back" && React.createElement("div", { className: "tm-pop" },
      React.createElement("span", { className: "label", style: { margin: 0 } }, "Обратный перевод (EN → RU)"),
      backResult === "loading"
        ? React.createElement("div", { className: "row", style: { gap: 10 } }, React.createElement(Spinner, null), React.createElement("span", { className: "dim", style: { fontSize: 13 } }, "Переводим EN→RU…"))
        : backResult === "no_target"
          ? React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, "Сначала переведите сегмент.")
          : backResult
            ? React.createElement("div", { className: "tmrow", style: { fontSize: 13, lineHeight: 1.5 } }, backResult)
            : React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, "Нет перевода для проверки.")),

    React.createElement("div", { className: "divider" }),

    // minitabs
    React.createElement("div", { className: "minitabs" },
      minitabs.map(([v, l]) => React.createElement("button", { key: v, className: tab === v ? "on" : "", onClick: () => setTab(v) }, l))),

    React.createElement("div", { style: { minHeight: 80 } },
      tab === "context" && React.createElement(ContextPane, { seg, glossHits }),
      tab === "tm" && React.createElement(TMPane, { tmHit, onApply: (t) => { setDraft(t); toast.info("Применено из TM"); } }),
      tab === "qa" && React.createElement(QAPane, { seg, qaResult }),
      tab === "comments" && React.createElement(CommentPane, { seg, store, comment, setComment, addComment })
    )
  );
}

function ContextPane({ seg, glossHits }) {
  return React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", null,
      React.createElement("div", { className: "label", style: { marginBottom: 8 } }, "Термины глоссария"),
      glossHits.length
        ? React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
            glossHits.map((g, i) => React.createElement("div", { key: i, className: "card", style: { padding: "10px 12px" } },
              React.createElement("div", { className: "row between" },
                React.createElement("span", { style: { fontWeight: 600, fontSize: 13 } }, g.src),
                React.createElement(Badge, { variant: "soft" }, g.cat)),
              React.createElement("div", { className: "row", style: { gap: 6, marginTop: 4, fontSize: 13 } },
                React.createElement(Icon, { name: "arrowR", size: 13, style: { color: "var(--text-3)" } }),
                React.createElement("span", { style: { color: "var(--c-primary)", fontWeight: 600 } }, g.tgt))
            )))
        : React.createElement("p", { className: "dim", style: { fontSize: 13 } }, "Совпадений с глоссарием не найдено.")
    ),
    React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
      React.createElement(Badge, { variant: "soft", icon: "target" }, "Риск: " + ({ low: "низкий", medium: "средний", high: "высокий", critical: "критический" }[seg.risk])),
      React.createElement(Badge, { variant: "soft", icon: "zap" }, seg.route)
    )
  );
}

function TMPane({ tmHit, onApply }) {
  if (!tmHit) return React.createElement("p", { className: "dim", style: { fontSize: 13 } }, "Точных совпадений в памяти переводов нет.");
  return React.createElement("div", { className: "card", style: { padding: 12, display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "row between" },
      React.createElement(Badge, { variant: "confirmed", icon: "checkCircle" }, (tmHit.score || 100) + "% совпадение"),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "TM")),
    React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, tmHit.target),
    React.createElement(Btn, { variant: "secondary", size: "sm", icon: "check", onClick: () => onApply(tmHit.target) }, "Применить перевод")
  );
}

function QAPane({ seg, qaResult }) {
  const legacyIssues = seg.qa || [];
  const structuredIssues = seg.qa_issues || [];
  const issues = structuredIssues.length ? structuredIssues : legacyIssues;
  if (!issues.length && !qaResult) return React.createElement("p", { className: "dim", style: { fontSize: 13 } }, "QA has not run yet.");
  const sevMeta = { critical: ["badge-failed", "CRITICAL"], major: ["badge-qa", "MAJOR"], high: ["badge-qa", "HIGH"], medium: ["badge-review", "MEDIUM"], minor: ["badge-soft", "MINOR"] };
  const colorMeta = { green: ["badge-confirmed", "GREEN"], yellow: ["badge-review", "YELLOW"], red: ["badge-failed", "RED"] };
  const result = qaResult || {};
  const routing = result.routing || {};
  const style = result.medical_style_qa || {};
  const back = result.literal_backcheck || {};
  return React.createElement("div", { className: "qa-pipeline", style: { display: "flex", flexDirection: "column", gap: 10 } },
    qaResult && React.createElement("div", { className: "card", style: { padding: 12, background: "var(--bg-sunken)" } },
      React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap", marginBottom: 8 } },
        React.createElement("span", { className: "badge " + (colorMeta[result.risk_color] || colorMeta.green)[0] }, (colorMeta[result.risk_color] || colorMeta.green)[1]),
        React.createElement("span", { className: "badge badge-soft" }, "Score " + (result.risk_score || 0)),
        React.createElement("span", { className: "badge badge-soft" }, routing.route || "not routed")),
      style.corrected_translation && React.createElement("div", { className: "tmrow", style: { fontSize: 13, lineHeight: 1.5 } },
        React.createElement("div", { className: "label", style: { marginBottom: 4 } }, "Suggested correction"),
        style.corrected_translation),
      back.backtranslated_ru && React.createElement("div", { className: "tmrow", style: { fontSize: 13, lineHeight: 1.5, marginTop: 8 } },
        React.createElement("div", { className: "label", style: { marginBottom: 4 } }, "Literal back-check"),
        back.backtranslated_ru)),
    issues.map((q, i) => {
      const sev = q.severity || q.sev || "medium";
      const [cls, lab] = sevMeta[sev] || sevMeta.medium;
      const msg = q.explanation_ru || q.msg || "QA issue";
      const suggestion = q.suggested_fragment || "";
      const fragment = q.bad_fragment || q.target_fragment || q.source_fragment || "";
      return React.createElement("div", { key: i, className: "card", style: { padding: 12 } },
        React.createElement("div", { className: "row", style: { gap: 8, marginBottom: 6, flexWrap: "wrap" } },
          React.createElement("span", { className: "badge " + cls }, lab),
          React.createElement("span", { className: "dim", style: { fontSize: 12 } }, q.type || "medical_qa"),
          q.detected_by && React.createElement("span", { className: "badge badge-soft" }, q.detected_by)),
        fragment && React.createElement("div", { className: "mono", style: { fontSize: 12, marginBottom: 5, color: "var(--text-2)" } }, fragment),
        React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, msg),
        suggestion && React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5, marginTop: 6, color: "var(--c-primary)", fontWeight: 650 } }, "Use: " + suggestion));
    }),
    (seg.term_candidates || []).length > 0 && React.createElement("div", { className: "card", style: { padding: 12, background: "var(--bg-sunken)" } },
      React.createElement("div", { className: "label", style: { marginBottom: 8 } }, "Pending term candidates"),
      seg.term_candidates.map((c, i) => React.createElement("div", { key: i, className: "row between", style: { gap: 8, fontSize: 13, padding: "6px 0", borderTop: i ? "1px solid var(--border)" : "none" } },
        React.createElement("span", null, c.bad_en || c.source_phrase || "candidate"),
        React.createElement("span", { style: { color: "var(--c-primary)", fontWeight: 650 } }, c.preferred_en || "review"))))
  );
}

function CommentPane({ seg, store, comment, setComment, addComment }) {
  return React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12 } },
    seg.comments.length
      ? React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12, maxHeight: 220, overflow: "auto" } },
          seg.comments.map((c, i) => React.createElement("div", { key: i, className: "row", style: { gap: 10, alignItems: "flex-start" } },
            React.createElement(Avatar, { person: c.author, size: 28 }),
            React.createElement("div", { style: { minWidth: 0 } },
              React.createElement("div", { className: "row", style: { gap: 6 } },
                React.createElement("span", { style: { fontWeight: 600, fontSize: 13 } }, c.author.name),
                React.createElement("span", { className: "dim", style: { fontSize: 11 } }, c.when)),
              React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5, marginTop: 2 } }, c.text)))))
      : React.createElement("p", { className: "dim", style: { fontSize: 13 } }, "Комментариев пока нет."),
    React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
      React.createElement(Textarea, { value: comment, onChange: (e) => setComment(e.target.value), placeholder: "Добавить комментарий…", style: { minHeight: 70 } }),
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "send", onClick: addComment, disabled: !comment.trim() }, "Отправить"))
  );
}
window.SegDetail = SegDetail;

