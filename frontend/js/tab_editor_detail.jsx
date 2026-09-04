/* ============================================================
   Segment detail panel (editor right sidebar)
   ============================================================ */
function SegDetail({ seg, project, store, toast, busy, onTranslate, onQA, onChecks, onConfirm, bcModels, bcModel, onBcModel, bcJudge, judgeModel, tcModel, rpModel,
                     // Уровни находок termcheck, по которым работает ремонт.
                     // Приходят сверху, а сверху — с сервера: список в двух
                     // местах литералом уже расходился с _repair_findings.
                     tcActionable = ["critical", "major", "minor"] }) {
  const [tab, setTab] = useState("context");
  const [draft, setDraft] = useState(seg.target || "");
  const [comment, setComment] = useState("");
  const [infoPanel, setInfoPanel] = useState(null); // 'tm'|'back'|'route'|'risk'|null
  const [backResult, setBackResult] = useState(null); // null|'loading'|string
  const [termBusy, setTermBusy] = useState(false);
  const [repairBusy, setRepairBusy] = useState(false);
  const [acceptBusy, setAcceptBusy] = useState(false);
  const idx = project.segments.findIndex(s => s.id === seg.id) + 1;
  const words = (draft.trim() ? draft.trim().split(/\s+/).length : 0);
  const dirty = draft !== (seg.target || "");

  useEffect(() => { setDraft(seg.target || ""); setInfoPanel(null); setBackResult(null); setTermBusy(false); setRepairBusy(false); }, [seg.id]);
  useEffect(() => { setDraft(seg.target || ""); }, [seg.target, seg.status]);

  /* Сегмент, пришедший из картинки, человеку нечем проверить: он видит строку
     текста и не может знать, то ли это, что нарисовано. Поэтому над оригиналом
     показываем сам кусок картинки. Кроп требует токен, поэтому тянется через
     fetch и живёт blob-ссылкой — <img src> заголовок не отправит. */
  const fromImage = !!(seg.origin && seg.origin.kind === "image");
  const [cropUrl, setCropUrl] = useState(null);
  const [overlayBusy, setOverlayBusy] = useState(false);
  const markOverlay = async () => {
    if (!window.API || !window.API.imageMarkOverlay) return;
    setOverlayBusy(true);
    const r = await window.API.safeCall(() => window.API.imageMarkOverlay(project.id, seg.id));
    setOverlayBusy(false);
    if (!r || !r.ok) { toast.error(TR("Не удалось"), TR("Сервер отказал или идёт разбор картинок.")); return; }
    const fresh = await window.API.safeCall(() => window.API.getProject(project.id));
    if (fresh && fresh.segments && store.replaceProjectSegments) {
      store.replaceProjectSegments(project.id, fresh.segments);
    }
    toast.success(TR("Убрано"), TR("Надпись помечена аппаратной — следующий разбор её не заведёт.")
      + (r.hadTarget ? TR(" Вместе с сегментом ушёл перевод: ") + r.hadTarget : ""));
  };
  useEffect(() => {
    /* Сбрасываем СРАЗУ: прежний blob отзывается уборкой этого же эффекта,
       и без сброса в <img src> до прихода нового кропа висит отозванная
       ссылка — на экране битая картинка вместо надписи. */
    setCropUrl(null);
    if (!fromImage || !window.API || !window.API.imageCropUrl) return;
    let dead = false, url = null;
    window.API.imageCropUrl(project.id, seg.id).then(u => {
      if (dead) { if (u) URL.revokeObjectURL(u); return; }
      url = u;
      setCropUrl(u);
    }).catch(() => {});
    return () => { dead = true; if (url) URL.revokeObjectURL(url); };
    /* project.id в зависимостях обязателен: номера сегментов в проектах
       свои, и при переключении на проект, где сегмент с тем же номером
       тоже из картинки, эффект без него не перезапустится — и человек
       увидит кусок чужого документа. */
  }, [seg.id, fromImage, project.id]);

  const saveDraft = () => {
    store.updateSegment(project.id, seg.id, { target: draft, status: seg.status === "new" ? "translated" : seg.status });
    toast.success(TR("Сохранено"), TR("Перевод сегмента #") + seg.id + TR(" обновлён."));
  };
  const copySrc = () => { navigator.clipboard && navigator.clipboard.writeText(seg.source); toast.info(TR("Скопировано"), TR("Оригинал в буфере обмена.")); };
  const addComment = () => {
    if (!comment.trim()) return;
    store.addComment(project.id, seg.id, comment.trim());
    setComment(""); toast.info(TR("Комментарий добавлен"));
  };

  const glossHits = store.glossary.filter(g => seg.source.toLowerCase().includes(g.src.toLowerCase()));
  const tmHit = seg.tm || store.tm.find(t => t.src === seg.source);

  // Cost estimate from source word count + route
  const srcWords = seg.source.trim() ? seg.source.trim().split(/\s+/).length : 0;
  // GOOGLE_SAFE — исторический маршрут: бесплатного движка нет, и переводить
  // такой сегмент заново будет та же модель. Считать его дешёвым — врать в 45 раз.
  const rate = (seg.route === "GPT_REQUIRED" || seg.route === "GOOGLE_SAFE") ? 0.0009 : 0;
  const estCost = srcWords * rate;
  const riskMeta = { low: ["badge-confirmed", "LOW"], medium: ["badge-review", "MEDIUM"], high: ["badge-qa", "HIGH"], critical: ["badge-failed", "CRITICAL"] };
  const riskColorMeta = { green: ["badge-confirmed", "GREEN"], yellow: ["badge-review", "YELLOW"], red: ["badge-failed", "RED"] };
  const qaIssues = seg.qa_issues || seg.qa || [];
  const qaResult = seg.qa_result || null;

  const toggleInfo = (k) => setInfoPanel(p => p === k ? null : k);

  // Проверка терминологии по одному сегменту. Готовый результат показываем без
  // нового вызова модели — платить второй раз за тот же текст незачем.
  const openTerms = () => {
    toggleInfo("terms");
    if (infoPanel === "terms") return;
    if (!seg.target || !seg.target.trim()) return;
    if (seg.termcheck && !seg.termcheck.stale) return;
    runTerms();
  };
  const runTerms = () => {
    if (termBusy || !window.API) return;
    setTermBusy(true);
    window.API.safeCall(() => window.API.termcheck(project.id, seg.id, tcModel)).then(res => {
      setTermBusy(false);
      if (!res || !res.ok) { toast.error(TR("Проверка не удалась"), TR("Модель не ответила или нет ключа OpenAI.")); return; }
      store.updateSegment(project.id, seg.id, { termcheck: { ...res.termcheck, stale: false } });
      const n = (res.termcheck.findings || []).length;
      if (res.skipped) toast.info(TR("Проверять нечего"), res.skipped);
      else if (n) toast.warning(TR("Замечания по терминам"), n + TR(" шт. · предложения замены ушли в «Глоссарий → Кандидаты»"));
      else toast.success(TR("Терминология в порядке"), TR("Замечаний нет."));
    });
  };

  // Ремонт одного сегмента: правка по находкам + перепроверка на сервере.
  const runRepair = () => {
    if (repairBusy || !window.API) return;
    setRepairBusy(true);
    window.API.safeCall(() => window.API.repair(project.id, seg.id, {
      model: rpModel || null, bc_model: bcModel || null, tc_model: tcModel || null,
      use_judge: !!bcJudge, judge_model: judgeModel || null })).then(res => {
      setRepairBusy(false);
      if (!res || !res.ok) { toast.error(TR("Ремонт не удался"), TR("Модель не ответила или нет ключа OpenAI.")); return; }
      if (!res.applied) {
        store.updateSegment(project.id, seg.id, { repair: { ...res.repair, tried: true } });
        toast.warning(TR("Правка откачена"), TRS((res.repair && res.repair.reason) || "") || TR("Не стало лучше — текст оставлен прежним."));
        return;
      }
      window.API.safeCall(() => window.API.getProject(project.id)).then(fresh => {
        if (fresh && fresh.segments) store.replaceProjectSegments(project.id, fresh.segments);
      });
      toast.success(TR("Сегмент исправлен"), TR("Статус «Требует проверки» — подтвердите вручную."));
    });
  };

  /* Принять текст, который ремонт написал и отменил падением балла.
     Вызова модели нет — подставляется уже оплаченный repair.candidate,
     поэтому и подтверждения не спрашиваем: сочинять тут нечего, а прежний
     текст уходит в repair.from и виден кнопкой «Вернуть прежний». */
  /* Совет арбитра одним нажатием. Признак `ctxAdvice` считает СЕРВЕР
     (`_ctx_advices`): кнопка стоит только там, где эндпоинт сработает.
     Подтверждения не спрашиваем — ничего не сочиняется, прежний текст
     уходит в termCtxApplied.from и виден в карточке. */
  const [ctxBusy, setCtxBusy] = useState(false);
  const applyAdvice = (a) => {
    if (ctxBusy || !window.API) return;
    setCtxBusy(true);
    window.API.safeCall(() => window.API.termContextApply(project.id,
      { src: a.src, tgt: a.tgt, use: a.use, dry_run: false, segment_ids: [seg.id], include_confirmed: true }))
      .then(res => {
        setCtxBusy(false);
        if (!res || !res.ok || !res.applied) { toast.error(TR("Не удалось применить"), (res && res.error) || TR("Сервер отказал — обновите страницу.")); return; }
        const now = draft.split(a.tgt).join(a.use);
        setDraft(now);
        store.updateSegment(project.id, seg.id, { target: now, status: "review", ctxAdvice: null,
          termCtxApplied: { src: a.src, tgt: a.tgt, use: a.use, from: seg.target, by: "human" } });
        toast.success(TR("Подставлено: ") + a.use,
          TR("Проверки устарели вместе с текстом — сегмент пойдёт в ближайший прогон. Запись глоссария не тронута."));
      });
  };

  const acceptRepair = () => {
    if (acceptBusy || !window.API) return;
    setAcceptBusy(true);
    window.API.safeCall(() => window.API.acceptRepair(project.id, seg.id)).then(res => {
      setAcceptBusy(false);
      if (!res || !res.ok) { toast.error(TR("Не удалось принять вариант"), TR("Сервер отказал — обновите страницу.")); return; }
      /* Кладём ОДИН сегмент, а не тянем проект: на 2670 строках это 5 МБ ради
         одной изменившейся строки (то же правило, что у /term-case). Сервер
         вернул его уже с производными stale/tried — считать их тут нечем. */
      if (res.segment) store.updateSegment(project.id, seg.id, res.segment);
      toast.success(TR("Вариант принят"),
        TR("Проверки устарели вместе с текстом — сегмент пойдёт в ближайший прогон."));
    });
  };

  // Что именно можно чинить в этом сегменте (критерий тот же, что на сервере)
  /* БЕЗ TR(): это не надписи, а КОДЫ ПРИЧИН, которые сравниваются
     с `backcheck.reasons` — русским текстом, пришедшим с сервера. Оберни их
     переводом, и в узбекском интерфейсе `indexOf` перестанет находить
     совпадения: кнопка «Починить» погаснет на сегментах, которые чинить
     МОЖНО, и понять почему будет неоткуда. Тот же закон, что у ключей
     объекта и операндов сравнения (CLAUDE.md, инвариант 17). */
  const REPAIR_REASONS = ["расхождение чисел", "расхождение единиц", "инверсия отрицания",
                          "подмена на противоположное", "обратный перевод про другое", "потерян термин"];
  const bcFresh = seg.backcheck && !seg.backcheck.stale ? seg.backcheck : null;
  const tcFresh = seg.termcheck && !seg.termcheck.stale ? seg.termcheck : null;
  const termFindings = (tcFresh && tcFresh.findings) || [];
  const hardFindings = termFindings.filter(f => tcActionable.indexOf(f.severity) !== -1);
  const canRepair = !!seg.target && !(seg.repair && seg.repair.tried) && (
    hardFindings.length > 0 ||
    (bcFresh && ((bcFresh.terms_lost || []).length > 0
      || (bcFresh.reasons || []).some(r => REPAIR_REASONS.some(h => r.indexOf(h) !== -1))
      // Текст написала ревизия — мнение судьи ремонту не отдаётся
      // (`_repair_findings`, `review.wrote` считает сервер).
      || (!(seg.review && seg.review.wrote) && bcFresh.judge
          && ["major", "critical"].indexOf(bcFresh.judge.severity) !== -1))));
  const runBack = (model) => {
    if (!seg.target) { setBackResult("no_target"); return; }
    setBackResult("loading");
    window.API && window.API.backcheck(project.id, seg.id, model, bcJudge, judgeModel).then(res => {
      if (res && res.ok) {
        setBackResult(res.back);
        // Подтягиваем оценку в локальный state, чтобы процент сразу встал в строке
        if (res.backcheck) store.updateSegment(project.id, seg.id, { backcheck: res.backcheck, backtranslated_ru: res.back });
      } else {
        setBackResult(TR("Ошибка: ") + (res && res.error ? res.error : TR("нет ответа")));
      }
    }).catch(e => setBackResult(TR("Ошибка: ") + e.message));
  };
  const openBack = () => {
    toggleInfo("back");
    // Уже посчитанный back-check показываем без нового вызова модели
    if (infoPanel !== "back" && backResult == null) {
      if (seg.backcheck && seg.backcheck.back) { setBackResult(seg.backcheck.back); return; }
      runBack(bcModel);
    }
  };

  const minitabs = [
    ["context", TR("Контекст")], ["tm", "TM" + (tmHit ? " (1)" : "")],
    ["qa", "QA" + (qaIssues.length ? " (" + qaIssues.length + ")" : "")], ["comments", TR("Чат") + (seg.comments.length ? " (" + seg.comments.length + ")" : "")],
  ];

  const STATUS_TIP = {
    new: [TR("Новый"), TR("Сегмент не переведён. Никаких операций не выполнялось.")],
    translated: [TR("Переведён"), TR("Перевод получен моделью или вписан вручную. Проверки ещё не запускались.")],
    qa: [TR("QA пройдено"), TR("Автоматическая проверка качества выполнена. Можно подтверждать.")],
    confirmed: [TR("Подтверждён"), TR("Финальный статус. Добавлен в TM. Будет в экспорте.")],
    review: [TR("Требует review"), TR("Обнаружены проблемы — необходим человеческий просмотр.")],
    failed: [TR("Ошибка"), TR("Перевод/QA завершились с ошибкой. См. логи.")],
  };

  return React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 16 } },
    React.createElement("div", { className: "row between" },
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 700, fontSize: 16 } }, TR("Сегмент #") + seg.id),
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, idx + TR(" из ") + project.segments.length)),
      React.createElement("div", { className: "row", style: { gap: 2 } },
        React.createElement(StatusBadge, { status: seg.status }),
        React.createElement(InfoTip, { title: (STATUS_TIP[seg.status] || STATUS_TIP.new)[0], body: (STATUS_TIP[seg.status] || STATUS_TIP.new)[1] }))
    ),

    // source
    React.createElement("div", null,
      React.createElement("div", { className: "row between", style: { marginBottom: 6 } },
        React.createElement("span", { className: "label" },
          fromImage ? TR("🖼 Оригинал (текст на картинке)") : TR("Оригинал · ") + (project.src || "")),
        React.createElement(Btn, { variant: "ghost", size: "sm", icon: "copy", onClick: copySrc }, TR("Копировать"))),
      fromImage && React.createElement("div", { className: "card col", style: { padding: 8, marginBottom: 6, gap: 8, background: "var(--bg-sunken)" } },
        cropUrl
          ? React.createElement("img", { src: cropUrl, alt: TR("Надпись на картинке"),
              style: { maxWidth: "100%", display: "block", borderRadius: 4 } })
          : React.createElement("div", { className: "dim", style: { fontSize: 12 } },
              TR("Кусок картинки не загрузился — проверить распознанное нечем.")),
        /* Модель ошибается в обе стороны, и дальше машиной это не отсеять:
           правило «на картинке большинство — надпечатка» убивает законную
           подпись, а «нет букв языка оригинала» — латинское название вида.
           Значит решает человек, а система обязана слушаться и помнить. */
        React.createElement("div", { className: "row between", style: { gap: 8 } },
          React.createElement("span", { className: "dim", style: { fontSize: 11.5 } },
            TR("не текст документа?")),
          React.createElement(Btn, { variant: "ghost", size: "sm", disabled: overlayBusy,
            onClick: markOverlay },
            overlayBusy ? TR("Убираем…") : TR("Это надпись аппарата")))),
      React.createElement("div", { className: "card", style: { padding: 12, background: "var(--bg-sunken)", lineHeight: 1.55, fontSize: 14 } }, seg.source)
    ),

    // translation
    React.createElement("div", null,
      React.createElement("div", { className: "label", style: { marginBottom: 6 } }, TR("Перевод · ") + (project.tgt || "")),
      /* dir="auto": направление письма браузер берёт из самого текста — арабский
         и иврит выравниваются справа без каталога языков в браузере. */
      React.createElement(Textarea, { value: draft, onChange: (e) => setDraft(e.target.value), placeholder: TR("Введите перевод…"), dir: "auto", style: { minHeight: 120 } }),
      React.createElement("div", { className: "row between", style: { marginTop: 8 } },
        React.createElement("span", { className: "dim", style: { fontSize: 12 } }, words + TR(" слов · ") + draft.length + TR(" симв.")),
        dirty && React.createElement(Btn, { variant: "secondary", size: "sm", icon: "check", onClick: saveDraft }, TR("Сохранить")))
    ),

    // actions
    React.createElement("div", { className: "grid grid-2", style: { gap: 8 } },
      // Кнопка одна: движок один — выбранная модель. Раньше рядом стояла
      // «Google», и половина сегментов уходила в бесплатный переводчик.
      React.createElement(Btn, { variant: "primary", size: "sm", icon: "cpu", disabled: busy, onClick: () => onTranslate(), style: { background: "var(--c-purple)" } }, TR("Перевести")),
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "shield", disabled: busy, onClick: onChecks, style: { color: "var(--c-info)", boxShadow: "inset 0 0 0 1.5px var(--c-info)" } }, TR("Проверки")),
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "shield", disabled: busy, onClick: onQA }, "Quick QA"),
      React.createElement(Btn, { variant: "success", size: "sm", icon: "check", disabled: busy, onClick: () => onConfirm(draft) }, TR("Подтвердить"))
    ),

    // compact secondary actions (MemSource-style)
    React.createElement("div", { className: "mini-actions" },
      React.createElement("button", { className: "mini-btn" + (infoPanel === "tm" ? " on" : ""), onClick: () => toggleInfo("tm") },
        React.createElement(Icon, { name: "search", size: 14 }), "Find TM"),
      React.createElement("button", { className: "mini-btn" + (infoPanel === "back" ? " on" : ""), onClick: openBack },
        React.createElement(Icon, { name: "repeat", size: 14 }), "Back check"),
      React.createElement("button", { className: "mini-btn" + (infoPanel === "terms" ? " on" : ""), onClick: openTerms,
        title: TR("Проверка терминологии: нормальные ли термины целевого языка") },
        React.createElement(Icon, { name: "book", size: 14 }), TR("Термины"),
        termFindings.length > 0 && React.createElement("span", { className: "mb-val", style: { color: "var(--c-warning)" } }, termFindings.length)),
      canRepair && React.createElement("button", { className: "mini-btn", onClick: runRepair, disabled: repairBusy,
        title: TR("Переписать перевод по найденным замечаниям и перепроверить") },
        React.createElement(Icon, { name: "repeat", size: 14 }), repairBusy ? TR("Чиним…") : TR("Починить")),
      React.createElement("button", { className: "mini-btn" + (infoPanel === "route" ? " on" : ""), onClick: () => toggleInfo("route") },
        React.createElement(Icon, { name: "target", size: 14 }), "Route"),
      React.createElement("button", { className: "mini-btn" + (infoPanel === "risk" ? " on" : ""), onClick: () => toggleInfo("risk") },
        React.createElement(Icon, { name: "warn", size: 14 }), "Risk"),
      React.createElement("span", { className: "mini-btn readonly", title: TR("Оценка стоимости перевода") },
        React.createElement(Icon, { name: "zap", size: 14 }), "Est: ", React.createElement("span", { className: "mb-val" }, fmtCost(estCost)))
    ),

    infoPanel === "terms" && React.createElement("div", { className: "tm-pop" },
      React.createElement("div", { className: "row between" },
        React.createElement("span", { className: "label", style: { margin: 0 } }, TR("Терминология перевода")),
        React.createElement(Btn, { variant: "ghost", size: "sm", icon: "repeat", disabled: termBusy, onClick: runTerms },
          termBusy ? TR("Проверяем…") : TR("Проверить заново"))),
      termBusy && !seg.termcheck
        ? React.createElement("div", { className: "row", style: { gap: 10 } },
            React.createElement(Spinner, null),
            React.createElement("span", { className: "dim", style: { fontSize: 13 } }, TR("Модель разбирает термины…")))
        : !seg.termcheck
          ? React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, TR("Ещё не проверялось."))
          : React.createElement("div", { className: "col", style: { gap: 8 } },
              seg.termcheck.stale && React.createElement("div", { style: { fontSize: 12, color: "var(--c-warning)" } },
                TR("Перевод менялся после проверки — данные устарели.")),
              seg.termcheck.note && React.createElement("div", { className: "dim", style: { fontSize: 12.5 } }, seg.termcheck.note),
              termFindings.length === 0 && !seg.termcheck.note && React.createElement("div", { style: { fontSize: 13, color: "var(--c-success)" } }, TR("Замечаний нет.")),
              termFindings.map((f, i) => React.createElement("div", { key: i, className: "tmrow", style: { display: "flex", flexDirection: "column", gap: 4 } },
                React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
                  React.createElement("span", { className: "badge " + (f.severity === "critical" ? "badge-failed" : f.severity === "major" ? "badge-qa" : "badge-soft") }, f.severity),
                  React.createElement("s", { style: { color: "var(--c-error)" } }, f.tgt_term),
                  f.suggestion && React.createElement(React.Fragment, null,
                    React.createElement(Icon, { name: "chevR", size: 13 }),
                    React.createElement("b", { style: { color: "var(--c-success)" } }, f.suggestion))),
                f.why && React.createElement("div", { className: "dim", style: { fontSize: 12, lineHeight: 1.5 } }, TRS(f.why)),
                f.suggestion && React.createElement(Btn, { variant: "secondary", size: "sm", icon: "check",
                  onClick: () => { setDraft(draft.split(f.tgt_term).join(f.suggestion)); toast.info(TR("Подставлено в черновик"), TR("Проверьте и сохраните.")); } }, TR("Заменить в тексте")))),
              React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
                (seg.termcheck.model === "skip" ? TR("без вызова модели") : seg.termcheck.model || "")
                + (seg.termcheck.at ? " · " + seg.termcheck.at : "")))),

    /* Совет арбитра, который есть чем исполнить. Стоит ОТДЕЛЬНОЙ карточкой,
       а не подсказкой при наведении: подсказку не видно и не нажать, а тут
       готовое решение в один клик. Жёлтая полоса — это спор с глоссарием,
       и человеку сказано, что запись не трогается. */
    (seg.ctxAdvice || []).length > 0 && React.createElement("div",
      { className: "tm-pop", style: { marginTop: 8, borderLeft: "3px solid var(--c-warning)" } },
      React.createElement("span", { className: "label", style: { margin: 0, color: "var(--c-warning)" } },
        TR("Арбитр: термин здесь передан неверно")),
      seg.ctxAdvice.map((a, i) => React.createElement("div", { key: i, style: { marginTop: 6 } },
        React.createElement("div", { style: { fontSize: 13, lineHeight: 1.6 } },
          a.src + TR(" · в тексте: "), React.createElement("b", null, a.tgt),
          TR(" → здесь верно: "), React.createElement("b", { style: { color: "var(--c-success)" } }, a.use)),
        a.why && React.createElement("div", { className: "dim", style: { fontSize: 12, lineHeight: 1.5 } }, TRS(a.why)),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "check", style: { marginTop: 4 },
          disabled: ctxBusy, onClick: () => applyAdvice(a) },
          ctxBusy ? TR("Подставляем…") : TR("Применить в этом сегменте")))),
      React.createElement("div", { className: "dim", style: { fontSize: 11.5, marginTop: 6 } },
        TR("Меняется только эта строка; запись глоссария остаётся. Все сегменты с тем же советом — на «Анализе»."))),
    seg.termCtxApplied && React.createElement("div",
      { style: { fontSize: 12.5, color: "var(--c-success)", marginTop: 6 } },
      TR("Совет арбитра применён: ") + seg.termCtxApplied.tgt + " → " + seg.termCtxApplied.use
      + (seg.termCtxApplied.at ? " · " + seg.termCtxApplied.at : "")),

    /* Вердикт ревизии. Единственный шаг, который читает пару целиком и сразу
       правит текст, — и до этой карточки его вердикт не было видно НИГДЕ:
       человек получал переписанный сегмент без объяснения, за что.
       Красная полоса — «повреждён сам оригинал»: там машина бессильна
       по построению, и решать человеку. */
    seg.review && React.createElement("div",
      { className: "tm-pop", style: { marginTop: 8,
        borderLeft: "3px solid " + (seg.review.stale ? "var(--border)"
          : seg.review.sourceSuspect ? "var(--c-error)"
          : seg.review.applied ? "var(--c-success)" : "var(--c-warning)") } },
      React.createElement("div", { className: "row between", style: { gap: 10, flexWrap: "wrap" } },
        React.createElement("span", { className: "label", style: { margin: 0 } },
          seg.review.sourceSuspect ? TR("Ревизия: похоже, повреждён сам оригинал")
            : seg.review.applied ? TR("Ревизия исправила перевод") : TR("Ревизия прочитала пару")),
        React.createElement("span", { className: "dim", style: { fontSize: 11.5 } },
          TR("оценка ") + seg.review.score + "/10"
          + (seg.review.model ? " · " + seg.review.model : "")
          + (seg.review.at ? " · " + seg.review.at : ""))),
      seg.review.stale && React.createElement("div",
        { className: "dim", style: { fontSize: 12, marginTop: 4, lineHeight: 1.5 } },
        TR("Текст менялся после ревизии — сказанное ниже относится к прежней версии.")),
      (seg.review.issues || []).length > 0 && React.createElement("ul",
        { style: { margin: "6px 0 0", paddingLeft: 18, fontSize: 12.5, lineHeight: 1.5 } },
        seg.review.issues.map((x, i) => React.createElement("li", { key: i }, TRS(x)))),
      /* Прежний текст: правку видно, только если есть с чем сравнить. */
      seg.review.from && React.createElement("div",
        { className: "dim", style: { fontSize: 12, marginTop: 6, lineHeight: 1.5 } },
        TR("Было: "), React.createElement("s", null, seg.review.from)),
      /* Почему НЕ применили — причина приходит с сервера, браузер её не
         вычисляет: правило одно и живёт там же, где решение. */
      /* Совет, который машина не рискнула поставить. Ради него человека сюда
         и зовёт строка «Ревизия нашла проблему, но текст не тронула»: сервер
         отдаёт `candidate` только у НЕприменённой правки. */
      seg.review.candidate && !seg.review.applied && React.createElement("div",
        { style: { fontSize: 12.5, marginTop: 6, lineHeight: 1.5 } },
        React.createElement("span", { className: "dim" }, TR("Предлагалось: ")),
        seg.review.candidate),
      seg.review.skipped && React.createElement("div",
        { className: "dim", style: { fontSize: 12, marginTop: 6 } },
        TR("Правка не поставлена: ") + TRS(seg.review.skipped)
        + ((seg.review.vetoLabels || []).length
            ? " (" + seg.review.vetoLabels.map(TRS).join(", ") + ")" : "")),
      seg.review.undone && React.createElement("div",
        { style: { fontSize: 12, marginTop: 6, color: "var(--c-warning)" } },
        TR("Правка откачена человеком — повторно предлагаться не будет."))),

    /* Доказательство отмены заверения. Стоит ВЫШЕ карточки ремонта и красным:
       машина отменила решение человека, и он должен увидеть, за что именно,
       не разыскивая это по журналам. */
    seg.confirmWithdrawn && React.createElement("div",
      { className: "tm-pop", style: { marginTop: 8, borderLeft: "3px solid var(--c-danger)" } },
      React.createElement("span", { className: "label", style: { margin: 0, color: "var(--c-danger)" } },
        TR("Подтверждение снято машиной")),
      React.createElement("div", { style: { fontSize: 12.5, lineHeight: 1.6, marginTop: 4 } },
        (seg.confirmWithdrawn.evidence || []).map(TRS).join("; ")),
      React.createElement("div", { className: "dim", style: { fontSize: 12, marginTop: 4 } },
        TR("заверил: ") + (seg.confirmWithdrawn.by || "—")
        + (seg.confirmWithdrawn.at ? " · " + seg.confirmWithdrawn.at : "")
        + TR(" · снято ") + (seg.confirmWithdrawn.withdrawnAt || "")),
      seg.confirmWithdrawn.was && React.createElement("div", { style: { marginTop: 6 } },
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, TR("Заверенный текст был:")),
        React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, seg.confirmWithdrawn.was))),

    seg.repair && React.createElement("div", { className: "tm-pop", style: { marginTop: 8 } },
      React.createElement("span", { className: "label", style: { margin: 0 } },
        seg.repair.applied ? TR("Автоматический ремонт применён") : TR("Автоматический ремонт откачен")),
      /* TRS(), а не TR(): объяснение собрано СЕРВЕРОМ вместе с числами
         и именами терминов («балл back-check упал 70 → 45»), точного ключа
         у него нет. Переводится на выходе — сама строка в данных остаётся
         русской, потому что по ней сравнивает и сервер (`_repair_score_vetoed`),
         и браузер (`REPAIR_REASONS`). Свободный текст модели словарь не знает
         и вернёт как есть: русский оригинал честнее пустоты. */
      React.createElement("div", { className: "dim", style: { fontSize: 12, lineHeight: 1.6, marginTop: 4 } },
        (seg.repair.issues || []).map(TRS).join("; ")),
      /* Решения, принятые ВОПРЕКИ падению балла. Поле заведено ровно затем,
         чтобы человек не смотрел на принятую правку с упавшим баллом и не
         гадал, почему её оставили, — а значит его надо показывать. */
      (seg.repair.notes || []).length > 0 && React.createElement("div",
        { style: { fontSize: 12.5, color: "var(--text-2)", marginTop: 4, lineHeight: 1.5 } },
        (seg.repair.notes || []).map(TRS).join("; ")),
      /* Принятый человеком кандидат от машинной правки на экране неотличим,
         а это разные вещи: одну заверила оценка, другую — человек. */
      seg.repair.acceptedBy === "human" && React.createElement("div",
        { style: { fontSize: 12.5, color: "var(--c-success)", marginTop: 4 } },
        TR("Вариант принят человеком") + (seg.repair.acceptedAt ? " · " + seg.repair.acceptedAt : "")),
      !seg.repair.applied && seg.repair.reason && React.createElement("div", { style: { fontSize: 12.5, color: "var(--c-warning)", marginTop: 4 } },
        TR("Причина отката: ") + TRS(seg.repair.reason)),
      seg.repair.applied && seg.repair.from && React.createElement("div", { style: { marginTop: 6 } },
        React.createElement("div", { className: "dim", style: { fontSize: 12 } }, TR("Было:")),
        React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, seg.repair.from),
        React.createElement(Btn, { variant: "ghost", size: "sm", icon: "repeat", style: { marginTop: 6 },
          onClick: () => { setDraft(seg.repair.from); toast.info(TR("Прежний текст в черновике"), TR("Сохраните, чтобы вернуть.")); } }, TR("Вернуть прежний"))),
      !seg.repair.applied && seg.repair.candidate && React.createElement("div", { style: { marginTop: 6 } },
        React.createElement("div", { className: "dim", style: { fontSize: 12 } },
          seg.repair.acceptable
            ? TR("Вариант модели — термины он почистил, отменил его только упавший балл:")
            : TR("Вариант модели (отклонён проверкой):")),
        React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, seg.repair.candidate),
        /* Кнопка стоит, только когда её разрешил СЕРВЕР (repair.acceptable):
           правило «отмену держал один балл, а термины стали чище» живёт
           в _repair_score_vetoed, и повторять его здесь значит однажды
           предложить нажатие, на которое эндпоинт ответит 400. */
        seg.repair.acceptable && React.createElement(Btn, {
          variant: "ghost", size: "sm", icon: "check", style: { marginTop: 6 },
          disabled: acceptBusy, onClick: acceptRepair },
          acceptBusy ? TR("Принимаем…") : TR("Принять этот вариант")))),

    infoPanel === "route" && React.createElement("div", { className: "row", style: { gap: 8 } },
      React.createElement("span", { className: "badge badge-translated" }, seg.route),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } }, TR("маршрут обработки (инфо)"))),
    infoPanel === "risk" && React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
      React.createElement("span", { className: "badge " + (riskColorMeta[seg.risk_color] || riskMeta[seg.risk] || riskMeta.medium)[0] }, (riskColorMeta[seg.risk_color] || riskMeta[seg.risk] || riskMeta.medium)[1]),
      seg.risk_score != null && React.createElement("span", { className: "badge badge-soft" }, "Score " + seg.risk_score),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } }, TR("уровень риска (инфо)"))),
    // Процента совпадения здесь нет: он брался из seg.tmScore, который писался
    // единожды нулём при импорте и не обновлялся ничем. Показывать «0%» или
    // «100%» рядом с настоящей записью памяти значит подписывать её выдуманной
    // цифрой. Сама запись настоящая — она из store.tm, её и показываем.
    infoPanel === "tm" && React.createElement("div", { className: "tm-pop" },
      React.createElement("div", { className: "row between" },
        React.createElement("span", { className: "label", style: { margin: 0 } }, TR("Совпадения TM"))),
      tmHit
        ? React.createElement("div", { className: "tmrow" },
            React.createElement("div", { className: "row between", style: { marginBottom: 6 } },
              React.createElement(Badge, { variant: "confirmed", icon: "checkCircle" }, TR("точное совпадение")),
              React.createElement(Btn, { variant: "secondary", size: "sm", icon: "check", onClick: () => { setDraft(tmHit.target); toast.info(TR("Применено из TM")); } }, TR("Применить"))),
            React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, tmHit.target))
        : React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, TR("Точных совпадений в памяти переводов нет."))),
    infoPanel === "back" && React.createElement("div", { className: "tm-pop" },
      React.createElement("span", { className: "label", style: { margin: 0 } }, TR("Обратный перевод (EN → RU)")),

      // Процент соответствия и почему он такой
      seg.backcheck && seg.backcheck.score != null && React.createElement("div", {
        className: "row between", style: { marginBottom: 6, gap: 10, flexWrap: "wrap" } },
        React.createElement("span", { style: { fontSize: 18, fontWeight: 750,
          color: window.bcScoreColor(seg.backcheck.score) } },
          seg.backcheck.score + TR("% соответствия")),
        React.createElement("span", { className: "dim", style: { fontSize: 11.5 } },
          (seg.backcheck.model || "") + (seg.backcheck.at ? " · " + seg.backcheck.at : ""))),
      seg.backcheck && (seg.backcheck.reasons || []).length > 0 && React.createElement("div", {
        className: "dim", style: { fontSize: 12, marginBottom: 8, lineHeight: 1.5 } },
        TR("Причины: ") + seg.backcheck.reasons.map(TRS).join("; ")),

      backResult === "loading"
        ? React.createElement("div", { className: "row", style: { gap: 10 } }, React.createElement(Spinner, null), React.createElement("span", { className: "dim", style: { fontSize: 13 } }, TR("Переводим EN→RU…")))
        : backResult === "no_target"
          ? React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, TR("Сначала переведите сегмент."))
          : backResult
            ? React.createElement("div", { className: "tmrow", style: { fontSize: 13, lineHeight: 1.5 } }, backResult)
            : React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, TR("Нет перевода для проверки.")),

      // Выбор модели для штучной перепроверки
      bcModels && bcModels.length > 0 && React.createElement("div", {
        className: "row", style: { gap: 8, marginTop: 10, flexWrap: "wrap" } },
        React.createElement(Select, {
          value: bcModel || "", disabled: backResult === "loading", style: { flex: 1, minWidth: 150 },
          onChange: (e) => onBcModel && onBcModel(e.target.value),
        }, bcModels.map(m => React.createElement("option", { key: m.id, value: m.id }, m.label))),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat",
          disabled: backResult === "loading" || !seg.target,
          onClick: () => runBack(bcModel) }, TR("Проверить заново")))),

    React.createElement("div", { className: "divider" }),

    // minitabs
    React.createElement("div", { className: "minitabs" },
      minitabs.map(([v, l]) => React.createElement("button", { key: v, className: tab === v ? "on" : "", onClick: () => setTab(v) }, l))),

    React.createElement("div", { style: { minHeight: 80 } },
      tab === "context" && React.createElement(ContextPane, { seg, glossHits }),
      tab === "tm" && React.createElement(TMPane, { tmHit, onApply: (t) => { setDraft(t); toast.info(TR("Применено из TM")); } }),
      tab === "qa" && React.createElement(QAPane, { seg, qaResult }),
      tab === "comments" && React.createElement(CommentPane, { seg, store, comment, setComment, addComment })
    )
  );
}

function ContextPane({ seg, glossHits }) {
  return React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", null,
      React.createElement("div", { className: "label", style: { marginBottom: 8 } }, TR("Термины глоссария")),
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
        : React.createElement("p", { className: "dim", style: { fontSize: 13 } }, TR("Совпадений с глоссарием не найдено."))
    ),
    React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
      React.createElement(Badge, { variant: "soft", icon: "target" }, TR("Риск: ") + ({ low: TR("низкий"), medium: TR("средний"), high: TR("высокий"), critical: TR("критический") }[seg.risk])),
      React.createElement(Badge, { variant: "soft", icon: "zap" }, seg.route)
    )
  );
}

function TMPane({ tmHit, onApply }) {
  if (!tmHit) return React.createElement("p", { className: "dim", style: { fontSize: 13 } }, TR("Точных совпадений в памяти переводов нет."));
  return React.createElement("div", { className: "card", style: { padding: 12, display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "row between" },
      React.createElement(Badge, { variant: "confirmed", icon: "checkCircle" }, (tmHit.score || 100) + TR("% совпадение")),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "TM")),
    React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, tmHit.target),
    React.createElement(Btn, { variant: "secondary", size: "sm", icon: "check", onClick: () => onApply(tmHit.target) }, TR("Применить перевод"))
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
      const msg = TRS(q.explanation_ru || q.msg || "QA issue");
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
      : React.createElement("p", { className: "dim", style: { fontSize: 13 } }, TR("Комментариев пока нет.")),
    React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
      React.createElement(Textarea, { value: comment, onChange: (e) => setComment(e.target.value), placeholder: TR("Добавить комментарий…"), style: { minHeight: 70 } }),
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "send", onClick: addComment, disabled: !comment.trim() }, TR("Отправить")))
  );
}
window.SegDetail = SegDetail;

