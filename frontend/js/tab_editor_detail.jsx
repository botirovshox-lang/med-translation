/* ============================================================
   Segment detail panel (editor right sidebar)
   ============================================================ */
function SegDetail({ seg, project, store, toast, busy, onTranslate, onQA, onConfirm }) {
  const [tab, setTab] = useState("context");
  const [draft, setDraft] = useState(seg.target || "");
  const [comment, setComment] = useState("");
  const [infoPanel, setInfoPanel] = useState(null); // 'tm'|'back'|'route'|'risk'|null
  const [backResult, setBackResult] = useState(null); // null|'loading'|string
  const idx = project.segments.findIndex(s => s.id === seg.id) + 1;
  const words = (draft.trim() ? draft.trim().split(/\s+/).length : 0);
  const dirty = draft !== (seg.target || "");

  useEffect(() => { setDraft(seg.target || ""); setInfoPanel(null); setBackResult(null); }, [seg.id]);
  useEffect(() => { setDraft(seg.target || ""); }, [seg.target]);

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

  const toggleInfo = (k) => setInfoPanel(p => p === k ? null : k);
  const openBack = () => {
    toggleInfo("back");
    if (infoPanel !== "back" && backResult == null) {
      setBackResult("loading");
      setTimeout(() => setBackResult(seg.source), 1100);
    }
  };

  const minitabs = [
    ["context", "Контекст"], ["tm", "TM" + (tmHit ? " (1)" : "")],
    ["qa", "QA" + (seg.qa.length ? " (" + seg.qa.length + ")" : "")], ["comments", "Чат" + (seg.comments.length ? " (" + seg.comments.length + ")" : "")],
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
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "shield", disabled: busy, onClick: onQA }, "QA"),
      React.createElement(Btn, { variant: "success", size: "sm", icon: "check", disabled: busy, onClick: onConfirm }, "Подтвердить")
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
    infoPanel === "risk" && React.createElement("div", { className: "row", style: { gap: 8 } },
      React.createElement("span", { className: "badge " + riskMeta[seg.risk][0] }, riskMeta[seg.risk][1]),
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
      React.createElement("span", { className: "label", style: { margin: 0 } }, "Обратный перевод (RU ← EN)"),
      backResult === "loading"
        ? React.createElement("div", { className: "row", style: { gap: 10 } }, React.createElement(Spinner, null), React.createElement("span", { className: "dim", style: { fontSize: 13 } }, "Выполняется…"))
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
      tab === "qa" && React.createElement(QAPane, { seg }),
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

function QAPane({ seg }) {
  if (!seg.qa.length) return React.createElement("p", { className: "dim", style: { fontSize: 13 } }, "Проверка QA не запускалась или замечаний нет.");
  const sevMeta = { critical: ["badge-failed", "Критично"], high: ["badge-qa", "Высокий"], medium: ["badge-review", "Средний"] };
  return React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
    seg.qa.map((q, i) => { const [cls, lab] = sevMeta[q.sev] || sevMeta.medium;
      return React.createElement("div", { key: i, className: "card", style: { padding: 12 } },
        React.createElement("div", { className: "row", style: { gap: 8, marginBottom: 6 } },
          React.createElement("span", { className: "badge " + cls }, lab),
          React.createElement("span", { className: "dim", style: { fontSize: 12 } }, q.type)),
        React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, q.msg));
    })
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
