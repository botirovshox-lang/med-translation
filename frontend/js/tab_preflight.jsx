/* ============================================================
   Tab: Preflight / Анализ проекта — Cost + Safety Planner
   Localized, with ⓘ tooltips and a transparent cost model.
   Drill-down: клик на любой блок/строку → редактор с активным фильтром сегментов.
   ============================================================ */
/* Итог работы по проекту. Читается сверху вниз как ответ на один вопрос:
   «что сейчас с переводом». Каждая строка кликается и открывает редактор
   с этими сегментами — цифра без возможности посмотреть на неё бесполезна. */
/* Ручная работа — по ДЕЙСТВИЮ, а не по проверке. Три группы: править
   перевод, править оригинал, решить про записи глоссария (там счёт идёт
   записями и парами — одно решение закрывает все затронутые сегменты).
   Один расчёт на «Подробности» и на карточку «Перевод под ключ»: два
   расчёта одного числа разошлись бы. Нулевые строки выбрасываются здесь,
   внутри группы — по убыванию числа. Чистая функция без JSX: кнопки
   привязывает по `key` тот, кто рисует. Старый сервер без `human.weak`
   переживается — поля читаются с запасом. */
const HUMAN_GROUP_TOP = 3;
function analysisHumanGroups(s) {
  const h = (s && s.human) || {}, t = (s && s.todo) || {};
  const sub = (a, b) => (a || []).filter(i => (b || []).indexOf(i) === -1);
  const flat = (arr, k) => [].concat.apply([], (arr || []).map(c => c[k] || []));
  /* Сегменты — только из корзины «нужен человек» (`turnkey.human`), если
     сервер её отдал: confirmWithdrawn он отдаёт целиком (и уже закрытые),
     confirmedFindings — с объективными, которые берёт машина, а «из них»
     обязано быть подмножеством «Нужно ваше решение». Старый сервер без
     turnkey — без фильтра. */
  const within = s && s.turnkey && Array.isArray(s.turnkey.human) ? new Set(s.turnkey.human) : null;
  const inside = ids => within ? (ids || []).filter(i => within.has(i)) : (ids || []);
  const row = (key, label, hint, ids, color, n) => {
    const got = inside(ids);
    return { key, label, hint, ids: got, color, n: n != null ? n : got.length };
  };
  const byScore = h.revertedByScore || [];
  const ctxWrong = h.termContextWrong || [];
  /* Запись, про которую уже ответил арбитр, в спорах termcheck второй раз
     не считается: арбитра спрашивают ровно про спорные записи, и одна
     запись иначе давала два решения. */
  const rkey = d => ((d.src || "") + "→" + (d.tgt || "")).toLowerCase();
  const ctxKeys = new Set(ctxWrong.map(rkey));
  const disputes = (h.termcheckDisputes || []).filter(d => !ctxKeys.has(rkey(d)));
  const fix = [
    /* Ревизия НАСТАИВАЕТ: готовый вариант прошёл все объективные сверки,
       и держит его только подпись человека. Стоит первой строкой намеренно —
       это единственная строка, где работа уже сделана и оплачена, а нужно
       ровно одно нажатие. */
    row("reviewConfirmed", TR("Ревизия предлагает правку заверенного"),
      TR("вариант прошёл объективные сверки, но текст заверил человек — прочтите и примените, подпись снимется"),
      h.reviewConfirmed, "var(--c-warning)"),
    row("reviewFlagged", TR("Ревизия нашла проблему, но текст не тронула"),
      TR("сверка не пустила правку либо модель не дала варианта — оценка, замечания и предложенный текст в карточке сегмента"),
      h.reviewFlagged, "var(--c-warning)"),
    row("weak", TR("Оценка ниже порога после судьи"),
      TR("судья смотрел или не придёт — балл читать глазами"), h.weak, "var(--c-warning)"),
    row("reverted", TR("Правка откачена — не стало лучше"),
      TR("модель пробовала починить и не смогла"), sub(h.reverted, byScore), "var(--c-warning)"),
    row("revertedByScore", TR("Ремонт отменил верную правку — текст готов"),
      TR("балл back-check упал, но термины стали чище — текст уже написан и оплачен"), byScore, "var(--c-warning)"),
    row("staleFindings", TR("Забракованное слово осталось в тексте"),
      TR("termcheck отверг эту формулировку, а потом передумал — а слово на месте"), h.staleFindings, "var(--c-warning)"),
    row("confirmWithdrawn", TR("Машина сняла ваше подтверждение"),
      TR("расхождение чисел, единиц или отрицания — это сильнее заверения; доказательство в карточке сегмента"),
      h.confirmWithdrawn, "var(--c-error)"),
    row("glossaryConfirmed", TR("Подтверждено, но спорит с глоссарием"),
      TR("переписать можно только по явной галочке"), h.glossaryConfirmed, "var(--c-warning)"),
    row("confirmedFindings", TR("Подтверждено, но есть находки проверок"),
      TR("починит «Ремонт» с галочкой «чинить подтверждённые»"), h.confirmedFindings, "var(--c-warning)"),
    row("qaCritical", TR("Подтверждено, но проверки нашли критичное"),
      TR("числа, дозировки или структура — проверка статус не меняет, решает человек"), h.qaCritical, "var(--c-error)"),
  ];
  const source = [
    row("sourceSuspect", TR("Похоже, повреждён сам оригинал"),
      TR("обрывок, ошибка распознавания или бессвязная фраза — перевод чинить нечем, пока не выправлен исходник"),
      h.sourceSuspect, "var(--c-error)"),
  ];
  const records = [
    row("disputes", TR("Проверка спорит с утверждённым термином"),
      TR("ремонт это не починит — решать вам: неверна запись или проверка"),
      h.termcheckDisputesSegments, "var(--c-warning)", disputes.length),
    row("ctxWrong", TR("Арбитр считает запись неверной для документа"),
      TR("довод и готовый вариант — ниже"), flat(ctxWrong, "segments"), "var(--c-warning)", ctxWrong.length),
    /* Разнобоя здесь НЕТ: сервер кладёт его в корзину МАШИНЫ (к человеку
       уходят только заверенные), и в итог «нужен человек» он не входит —
       строка с парами живёт ниже групп, как и раньше. */
    row("terms", TR("Терминов машина решать не берётся"),
      TR("спорные варианты и конфликты — в «Глоссарии»"), [], "var(--c-warning)", h.termsTotal || 0),
  ];
  const group = (key, label, hint, rows, byRecords) => {
    /* Громкие строки (снятое заверение, критика QA — `c-error`) и единственная
       точка входа к «Принять все» не уезжают под свёртку за большим числом:
       сперва по весу, затем по числу. */
    const rank = r => (r.color === "var(--c-error)" ? 2 : 0) + (r.key === "revertedByScore" ? 1 : 0);
    const live = rows.filter(r => r.n > 0).sort((a, b) => (rank(b) - rank(a)) || (b.n - a.n));
    const seen = new Set();
    live.forEach(r => r.ids.forEach(i => seen.add(i)));
    const ids = Array.from(seen);
    return { key, label, hint, rows: live, ids, color: "var(--c-warning)",
             n: byRecords ? live.reduce((a, r) => a + r.n, 0) : ids.length };
  };
  return [
    group("fix", TR("Править перевод"), TR("текст неверен или сомнителен — открыть и вычитать"), fix, false),
    group("source", TR("Править оригинал"), TR("перевод сделан, насколько позволяет исходник"), source, false),
    group("records", TR("Решить про записи глоссария"), TR("одно решение закрывает все затронутые сегменты"), records, true),
  ];
}

/* Команды по вопросам экрана «Проверка» — ОДНИ на экспертный итог
   (WorkSummary) и на список вопросов человеку (CheckQuestions). Две копии
   одной команды разошлись бы в предпросмотре и подтверждении, а у каждой
   из них обязательны dry_run → подтверждение → применение → подтянуть
   правленые сегменты. Хук, а не набор функций: у команд своё «занято». */
function useAnalysisCommands(store, toast, onReload) {
  /* Пакетное принятие отменённых правок. Вызовов модели нет — подставляется
     уже написанный repair.candidate. Порядок тот же, что у выноса глоссария
     и пересчёта баллов: сначала разбор, потом подтверждение, потом применение;
     копия для отката уходит в data/backups/. */
  const [accBusy, setAccBusy] = useState(false);
  const [rvBusy, setRvBusy] = useState(false);

  /* Применить советы ревизии, которые держит ЗАВЕРЕНИЕ. Вызовов модели нет:
     вердикты уже оплачены и лежат на сегментах, сверки пересчитываются
     бесплатно на сервере. Дверь своя (`/review/apply`), а не общий `/review`:
     тот в `_PAID`, и на исчерпанном лимите подстановка готового текста
     отвечала бы 402 — прямо против правила «лимит режет деньги, а не работу».
     Подпись человека при этом СНИМАЕТСЯ, поэтому спрашиваем прямо. */
  const applyHeldReview = (ids) => {
    if (!window.API || rvBusy || !(ids || []).length) return;
    setRvBusy(true);
    window.API.safeCall(() => window.API.applyReview(store.activeProject.id,
        { segment_ids: ids, dry_run: true, include_confirmed: true }))
      .then(dry => {
        if (!dry || !dry.ok) { setRvBusy(false); toast.error(TR("Не удалось посчитать"), TR("Сервер не ответил.")); return; }
        if (!dry.wouldApply) { setRvBusy(false); toast.info(TR("Применять нечего"), TR("Советы устарели или уже применены.")); return; }
        /* Потолок называется числом: за один запрос сервер берёт не больше
           REVIEW_LIMIT_MAX, и молчаливое усечение неотличимо от «работа
           кончилась» — тот же закон, что у `capped` в остальных пачках. */
        const rest = dry.capped || 0;
        const ok = window.confirm(
          TR("Поставить готовые варианты ревизии в ") + dry.wouldApply + TR(" сегментах?") + "\n\n"
          + TR("Вызовов модели нет — текст уже написан и прошёл объективные сверки.") + "\n"
          + TR("Это ЗАВЕРЕННЫЕ сегменты: прежний текст уйдёт в «прошлый перевод», статус станет «требует проверки», а отметка «подтвердил человек» снимется.") + "\n"
          + (rest ? TR("За один раз применяется не больше ") + dry.wouldApply
                    + TR(", остальные ") + rest + TR(" — следующим нажатием.") + "\n" : "")
          + "\n" + TR("Откат есть: копия уйдёт в data/backups/, метку скажу после применения."));
        if (!ok) { setRvBusy(false); return; }
        window.API.safeCall(() => window.API.applyReview(store.activeProject.id,
            { segment_ids: ids, dry_run: false, include_confirmed: true }))
          .then(async res => {
            setRvBusy(false);
            if (!res || !res.ok) { toast.error(TR("Не удалось применить"), TR("Сервер отказал.")); return; }
            /* Тянем ТОЛЬКО правленые сегменты: проект весит мегабайты,
               а в браузере иначе останется прежний текст — и первое же
               «Сохранить» в карточке вернуло бы его поверх принятого. */
            if (ids.length && window.API.fetchSegments) {
              const got = await window.API.safeCall(
                () => window.API.fetchSegments(store.activeProject.id, ids));
              store.mergeServerSegments(store.activeProject.id, got && got.segments);
            }
            toast.success(TR("Применено советов: ") + res.applied,
              TR("Откат — по метке ") + (res.stamp || "—"));
            if (onReload) onReload();
          });
      });
  };
  const acceptAll = () => {
    if (!window.API || accBusy) return;
    setAccBusy(true);
    window.API.safeCall(() => window.API.acceptRepairBatch(store.activeProject.id, { dry_run: true }))
      .then(dry => {
        if (!dry || !dry.ok) { setAccBusy(false); toast.error(TR("Не удалось посчитать"), TR("Сервер не ответил.")); return; }
        if (!dry.matched) { setAccBusy(false); toast.info(TR("Принимать нечего"), TR("Отменённых баллом правок не осталось.")); return; }
        const skipped = (dry.skippedConfirmed || []).length;
        /* Собрано КУСКАМИ, а не одним шаблонным литералом: в шаблоне с
           подстановкой нет постоянного текста, значит нет и ключа словаря —
           такое сообщение не перевести. Куски переводятся каждый сам. */
        const ok = window.confirm(
          TR("Принять готовые тексты в ") + dry.matched + TR(" сегментах?") + "\n\n"
          + TR("Вызовов модели нет — подставляется вариант, который ремонт уже написал.") + "\n"
          + TR("Проверки этих сегментов устареют вместе с текстом: перевод станет непроверенным до ближайшего прогона.") + "\n"
          + (skipped ? TR("Заверенных человеком не тронем: ") + skipped + ".\n" : "")
          + "\n" + TR("Откат есть: копия уйдёт в data/backups/, метку скажу после применения.") + "\n"
          + TR("Кнопки отката в интерфейсе пока нет — он делается запросом по метке."));
        if (!ok) { setAccBusy(false); return; }
        window.API.safeCall(() => window.API.acceptRepairBatch(store.activeProject.id, { dry_run: false }))
          .then(async res => {
            setAccBusy(false);
            if (!res || !res.ok) { toast.error(TR("Не удалось применить"), TR("Сервер отказал.")); return; }
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
              store.mergeServerSegments(store.activeProject.id, got && got.segments);
            }
            toast.success(TR("Принято сегментов: ") + res.accepted,
              TR("Откат — по метке ") + (res.stamp || "—")
              + TR(" · проверить их сможет ближайший прогон"));
            if (onReload) onReload();
          });
      });
  };

  /* «Применить к N сегм.» — по строке, а не по записи: глоссарий не трогается.
     Сначала dry_run — сервер называет число и заверенных, потом применяем. */
  const [ctxBusy, setCtxBusy] = useState(false);
  const applyAdvice = (d) => {
    if (!window.API || ctxBusy) return;
    setCtxBusy(true);
    const body = { src: d.src, tgt: d.tgt, use: d.use };
    window.API.safeCall(() => window.API.termContextApply(store.activeProject.id, { ...body, dry_run: true }))
      .then(r => {
        if (!r || !r.ok) { setCtxBusy(false); toast.error(TR("Не удалось посчитать"), (r && r.error) || ""); return null; }
        if (!r.matched) { setCtxBusy(false); toast.info(TR("Применять нечего"), TR("в ") + r.skippedConfirmed.length + TR(" заверенных сегм. не трогаем")); return null; }
        const ok = window.confirm(TR("Подставить «") + d.use + TR("» вместо «") + d.tgt + TR("» в ") + r.matched + TR(" сегм.?\n")
          + (r.skippedConfirmed.length ? TR("Заверенных человеком не трогаем: ") + r.skippedConfirmed.length + "\n" : "")
          + TR("Запись глоссария не меняется. Проверки этих сегментов устареют до ближайшего прогона. Откат — по метке."));
        if (!ok) { setCtxBusy(false); return null; }
        return window.API.safeCall(() => window.API.termContextApply(store.activeProject.id, { ...body, dry_run: false }));
      })
      .then(r => {
        if (!r) return;
        setCtxBusy(false);
        if (!r.ok) { toast.error(TR("Не удалось применить"), r.error || ""); return; }
        toast.success(TR("Подставлено в ") + r.applied + TR(" сегм."), TR("Откат — по метке ") + (r.stamp || "—"));
        if (onReload) onReload();
      });
  };

  /* Спор про ЗАПИСЬ решается той же дверью, что у сверки смысла:
     `/glossary/demote` — приказ становится подсказкой, перевод остаётся.
     Без кнопки здесь человек шёл искать запись в «Глоссарии» руками. */
  const demoteAdvised = (d) => {
    if (!window.API || ctxBusy) return;
    if (!window.confirm(TR("Понизить запись «") + d.src + " → " + d.tgt + TR("» до подсказки?\n")
      + TR("Модель перестанет быть обязана этим вариантом, ремонт перестанет его вписывать. ")
      + TR("Готовые переводы не меняются; вернуть приказ можно в «Глоссарии»."))) return;
    setCtxBusy(true);
    const p = store.activeProject;
    window.API.safeCall(() => window.API.demoteTerm(d.src, p.src + "→" + p.tgt, p.domain || ""))
      .then(r => {
        setCtxBusy(false);
        if (!r || !r.ok) { toast.error(TR("Не понижено"), (r && r.error) || TR("Сервер отказал")); return; }
        toast.success(r.already ? TR("Запись уже подсказка") : TR("Запись понижена до подсказки"),
          r.repairedCount ? TR("Ремонт уже вписал её в ") + r.repairedCount + TR(" сегм. — вернуть их можно в «Глоссарии»") : "");
        if (onReload) onReload();
      });
  };

  return { acceptAll, accBusy, applyHeldReview, rvBusy, applyAdvice, demoteAdvised, ctxBusy };
}

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
  const [groupOpen, setGroupOpen] = useState({});
  /* Строка итога — тот же AnalysisRow, что и у корзин «под ключ»: две копии одной
     строки на ОДНОМ экране разъезжаются молча (см. комментарий у AnalysisRow).
     Здесь `n` передаётся отдельно от `ids`: часть строк считает не сегменты,
     а термины («Терминов машина решать не берётся»), и списка у них нет. */
  const Row = (p) => React.createElement(AnalysisRow, Object.assign({ store, toast }, p));

  // Считаем по РАЗНЫМ сегментам: один и тот же подтверждённый сегмент может
  // и спорить с глоссарием, и нести находку проверок — сумма длин списков
  // посчитала бы его дважды и завысила бы работу человека.
  // Один раз: ниже список режется по DISPUTE_CAP и считается остаток —
  // повторный доступ с дефолтом в четырёх местах легко рассинхронизировать.
  const disputes = s.human.termcheckDisputes || [];
  const disputeSegs = s.human.termcheckDisputesSegments || [];
  const DISPUTE_CAP = 6;

  const { acceptAll, accBusy, applyHeldReview, rvBusy, applyAdvice, demoteAdvised, ctxBusy } =
    useAnalysisCommands(store, toast, onReload);

  const arbPending = s.human.termContextPending || 0;
  const arbWrong = s.human.termContextWrong || [];
  const askArbiter = () => {
    if (!window.API || arbBusy) return;
    setArbBusy(true);
    window.API.safeCall(() => window.API.termContext(store.activeProject.id, {}))
      .then(r => {
        setArbBusy(false);
        if (!r || !r.ok) { toast.error(TR("Арбитр не ответил"), (r && r.error) || TR("попробуйте ещё раз")); return; }
        // Отвечаем словами всегда, в том числе при нуле: молчаливое нажатие
        // неотличимо от сломанной кнопки.
        toast.success(TR("Спрошено сегментов: ") + r.asked,
          TR("снято претензий: ") + (r.settled || []).length
          + TR(" · запись под вопросом: ") + (r.wrong || []).length
          + (r.capped ? TR(" · показан не весь список, нажмите ещё раз") : ""));
        if (onReload) onReload();
      });
  };

  /* Группы по ДЕЙСТВИЮ — один расчёт на этот экран и на «Перевод под ключ»
     (analysisHumanGroups). Итог карточки — сегменты первых двух групп без
     повторов плюс записи третьей: один сегмент может и спорить с глоссарием,
     и нести находку, и считать его дважды нельзя. */
  const groups = analysisHumanGroups(s);
  const humanSegs = new Set();
  groups.filter(g => g.key !== "records").forEach(g => g.ids.forEach(i => humanSegs.add(i)));
  const humanTotal = humanSegs.size + (groups.find(g => g.key === "records") || { n: 0 }).n;

  return React.createElement("div", { className: "section" },
    React.createElement("h2", { className: "section-title" }, TR("Что сейчас с переводом"),
      React.createElement(InfoTip, { title: TR("Итог работы"),
        body: TR("Считается по состоянию проекта, а не по последнему прогону: прогонов может быть несколько, а вопрос один — что сделано и что осталось. Ни одного вызова модели здесь нет, открывать можно свободно.\n\n«Проверено начисто» — сегмент прошёл back-check и проверку терминов, замечаний нет. Соответствие глоссарию сюда НЕ входит: оно считается отдельно и видно своей строкой. Только сегменты «начисто» система считает готовыми учить терминологии.\n\nЛюбая строка открывает редактор с этими сегментами.") })),

    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column" } },
      React.createElement("div", { className: "row between", style: { paddingBottom: 4 } },
        React.createElement("span", { className: "dim", style: { fontSize: 12.5 } }, TR("Всего сегментов")),
        React.createElement("b", { style: { fontVariantNumeric: "tabular-nums" } }, s.total)),
      // «Глоссарий соблюдён» отсюда убрано: _machine_clean его не смотрит вовсе
      // (ни _gloss_misses, ни _verified_hits), и сегмент с нарушенным приказным
      // термином при чистых проверках попадал сюда — а рядом же лежал
      // в «Расходятся с глоссарием». Обещать соблюдение, которого никто
      // не проверял, нельзя: на этой строке человек закрывает вопрос.
      React.createElement(Row, { label: TR("Проверено начисто"), n: s.clean.length, ids: s.clean,
        color: "var(--c-success)", hint: TR("обе проверки чисто") }),
      React.createElement(Row, { label: TR("Исправила машина"), n: s.machine.repaired, ids: s.repaired,
        hint: TR("статус «требует проверки» — заверяет человек") }),
      React.createElement(Row, { label: TR("Ещё не переведено"), n: s.todo.untranslated.length,
        ids: s.todo.untranslated, hint: TR("запустите «Перевести и проверить»") }),
      React.createElement(Row, { label: TR("Переведено, но не проверено"), n: s.todo.unchecked.length,
        ids: s.todo.unchecked, hint: TR("back-check или проверка терминов не делались") }),
      // Без этой строки сегменты с замечаниями не попадали никуда: они не «чисто»
      // и не «не проверено», и экран показывал бы благополучие, которого нет.
      React.createElement(Row, { label: TR("С замечаниями проверок"), n: s.todo.findings.length,
        ids: s.todo.findings, hint: TR("это чинит «Ремонт» внутри прогона") }),
      React.createElement(Row, { label: TR("Расходятся с глоссарием"), n: s.todo.glossaryPending.length,
        ids: s.todo.glossaryPending, hint: TR("утверждённого термина нет в переводе") }),
      // Корзина «всё остальное». Починенные ремонтом сюда больше НЕ попадают:
      // у них back-check прошёл и termcheck чист, а отказ _machine_clean был
      // только про право учить глоссарий — на боевом проекте они составляли
      // 60% корзины и звали разбираться там, где разбираться не в чем. Своя
      // строка у них выше — «Исправила машина». Подпись берётся из разбора
      // причин, а не придумывается здесь: сервер знает состав, экран его
      // показывает.
      /* Не «плохо», а «никто не смотрел» — и это разные вещи. Тут прячется
         «беглое неверное слово»: monostable, cusps, actinoid — нормальные
         английские слова не из той области, балл у них 100, и все проверки
         довольны. Показываем ЧИСЛОМ: разбирать 845 сегментов руками никто
         не станет, лечится это одной кнопкой — судьёй. */
      /* «Нечего проверять» — не работа. Сегмент «40%» или строка прибора
         из корзины «не проверено» не уйдёт никогда: текст не изменится,
         и проверять в нём по-прежнему нечего. Своя строка снимает половину
         корзины, которая звала человека к несуществующей работе. */
      React.createElement(Row, { label: TR("Проверять нечего — цифры, коды, строки приборов"),
        n: (s.todo.nothingToCheck || []).length, ids: s.todo.nothingToCheck,
        hint: TR("перевод совпадает с оригиналом или в нём нет слов — работой это не станет") }),
      /* Подсказка не зовёт «включить Судью»: тумблер выше потолка зоны
         не действует — туда судью пускает только разовое разрешение
         judge_all, которое даёт кнопка «Перевести и доделать». Прежняя
         формулировка обещала лекарство, которое не работало. */
      React.createElement(Row, { label: TR("Никто не проверял: балл выше зоны судьи"),
        n: (s.todo.unverified || []).length, ids: s.todo.unverified,
        color: "var(--c-warning)",
        hint: TR("смысл не читал никто — их спросит судья кнопки «Перевести и доделать»") }),
      React.createElement(Row, { label: TR("Балл не измерить, судья не смотрел"),
        n: (s.todo.unjudgedBlind || []).length, ids: s.todo.unjudgedBlind,
        color: "var(--c-warning)",
        hint: TR("оригинал короче трёх содержательных слов — судья тут единственная мера") }),
      React.createElement(Row, { label: TR("Оценка ниже порога"), n: (s.todo.weak || []).length,
        ids: s.todo.weak, hint: (s.todo.weakWhy || []).slice(0, 2).map(w => w.reason).join(" · ")
          || TR("проверки прошли, но чисто не получилось") })),

    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", marginTop: 14 } },
      React.createElement("div", { className: "row between", style: { paddingBottom: 4 } },
        React.createElement("span", { style: { fontWeight: 500 } }, TR("Машина предлагает")),
        React.createElement("span", { className: "dim", style: { fontSize: 12.5 } }, TR("одним нажатием"))),
      React.createElement("div", { className: "row between", style: { padding: "9px 0", borderTop: "1px solid var(--border)", cursor: "pointer" },
        onClick: () => store.go("glossary") },
        React.createElement("span", null, TR("Терминов готовы к одобрению"),
          React.createElement("span", { className: "dim", style: { fontSize: 12.5 } }, TR(" — «Глоссарий» → «Автоодобрение однозначных»"))),
        React.createElement("b", { style: { fontVariantNumeric: "tabular-nums", color: s.proposed.terms ? "var(--c-primary)" : "var(--text-3)" } }, s.proposed.terms))),

    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", marginTop: 14 } },
      React.createElement("div", { className: "row between", style: { paddingBottom: 4 } },
        React.createElement("span", { style: { fontWeight: 500 } }, TR("Нужен человек")),
        React.createElement("b", { style: { fontVariantNumeric: "tabular-nums", color: humanTotal ? "var(--c-warning)" : "var(--c-success)" } }, humanTotal)),
      /* Группы по ДЕЙСТВИЮ (analysisHumanGroups): нулевые строки спрятаны,
         внутри группы — по убыванию числа, сверху HUMAN_GROUP_TOP строк,
         остальное под «ещё N». Прежде карточка рисовала все четырнадцать
         строк всегда, половина из них нули, и на что смотреть, было
         не понять. Заголовок группы открывает редактор с объединением её
         сегментов; у строки — свой клик. Кнопка «Принять все» привязана
         по ключу строки: сама функция групп без JSX. */
      humanTotal === 0 && React.createElement("div", { className: "dim",
          style: { padding: "9px 0", fontSize: 12.5, borderTop: "1px solid var(--border)" } },
        TR("Открытых вопросов нет")),
      groups.filter(g => g.n > 0).map(g => {
        const open = !!groupOpen[g.key];
        const shown = open ? g.rows : g.rows.slice(0, HUMAN_GROUP_TOP);
        const go = () => {
          store.setSegmentFilter(g.ids); store.go("editor");
          toast.info(g.label, g.ids.length + TR(" сегментов"));
        };
        return React.createElement(React.Fragment, { key: g.key },
          React.createElement("div", { className: "row between",
              style: { padding: "12px 0 2px", borderTop: "1px solid var(--border)", gap: 12, alignItems: "baseline" } },
            React.createElement("div", { style: { minWidth: 0 } },
              React.createElement("span", { style: { fontWeight: 600, color: g.color } }, g.label),
              React.createElement("span", { className: "dim", style: { fontSize: 12.5 } }, " — " + g.hint)),
            React.createElement("div", { className: "row", style: { gap: 10, alignItems: "center" } },
              g.ids.length > 0 && React.createElement(Btn, { variant: "ghost", size: "sm", icon: "search", onClick: go }, TR("Открыть")),
              React.createElement("b", { style: { fontVariantNumeric: "tabular-nums", color: g.color } }, g.n))),
          shown.map(r => React.createElement(Row, {
            key: r.key, label: r.label, hint: r.hint, ids: r.ids, n: r.n, color: r.color,
            action: r.key === "revertedByScore"
              ? React.createElement(Btn, { variant: "ghost", size: "sm", icon: "check",
                  disabled: accBusy, onClick: acceptAll },
                  accBusy ? TR("Принимаем…") : TR("Принять все"))
              : r.key === "reviewConfirmed"
              ? React.createElement(Btn, { variant: "ghost", size: "sm", icon: "check",
                  disabled: rvBusy, onClick: () => applyHeldReview(r.ids) },
                  rvBusy ? TR("Применяем…") : TR("Применить советы"))
              : null })),
          g.rows.length > HUMAN_GROUP_TOP && React.createElement("div", { className: "dim",
              style: { fontSize: 12.5, padding: "4px 0 6px", cursor: "pointer" },
              onClick: () => setGroupOpen(o => Object.assign({}, o, { [g.key]: !open })) },
            open ? TR("Свернуть") : TR("Ещё строк: ") + (g.rows.length - HUMAN_GROUP_TOP)));
      }),
      /* Ждут ДАННЫХ, а не решения: доноров приносят следующие чистые прогоны,
         и дорешает их автоматика. Раньше они шли в строку выше и пугали числом:
         на боевом проекте 412 из 684 «ждущих человека» человека не ждали. */
      (s.human.termsWaitingTotal || 0) > 0 && React.createElement(Row, {
        label: TR("Терминов ждут новых данных — дорешается само"), n: s.human.termsWaitingTotal,
        hint: TR("не хватает сегментов-доноров или чистых проверок; следующие прогоны добирают их сами") }),
      /* Разнобой — корзина МАШИНЫ (сервер кладёт его в machine_set, человеку
         остаются только заверенные), поэтому в группы и в итог не входит.
         Строка ведёт СПИСОК ПАР: решение одно на пару. */
      (s.todo.consistency || []).length > 0 && React.createElement(Row, {
        label: TR("Один оборот переведён по-разному"),
        n: (s.todo.consistency || []).length,
        ids: [].concat.apply([], (s.todo.consistency || []).map(c => c.segments || [])),
        color: "var(--c-warning)",
        hint: TR("termcheck забраковал вариант в одном месте — остальные места видны только так") }),
      (s.todo.consistency || []).length > 0 && React.createElement(
        "div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.7, paddingTop: 4 } },
        (s.todo.consistency || []).slice(0, 6).map((c, i) => React.createElement("div", { key: i },
          "«" + c.was + "» → «" + c.want + TR("» · мест: ") + (c.segments || []).length
          + (c.already ? TR(" · уже верно: ") + c.already : "")))),
      (s.human.staleFindingWords || []).length > 0 && React.createElement(
        "div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.7, paddingTop: 4 } },
        (s.human.staleFindingWords || []).slice(0, 5).map((w, i) =>
          React.createElement("div", { key: i },
            "#" + w.id + ": " + (w.words || []).join(", ")))),
      disputes.length > 0 && React.createElement(
        "div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.7, paddingTop: 8 } },
        disputes.slice(0, DISPUTE_CAP).map((d, i) => React.createElement(
          "div", { key: i },
          d.src + " → ", React.createElement("b", { style: { color: "var(--c-primary)" } }, d.tgt),
          TR(" · проверка предлагает: ") + (d.suggests.join(", ") || TR("без замены"))
            + TR(" · сегментов: ") + d.segments.length)),
        disputes.length > DISPUTE_CAP && React.createElement(
          "div", null, TR("и ещё ") + (disputes.length - DISPUTE_CAP) + TR(" записей"))),
      // Кнопка рисуется и при нуле ожидающих: иначе, спросив арбитра один раз,
      // человек теряет и способ переспросить, и подтверждение, что ноль
      // настоящий, — та же беда, что была у «Пересчитать» в соответствии
      // глоссарию.
      (arbPending > 0 || arbWrong.length > 0) && React.createElement(
        "div", { className: "row between", style: { paddingTop: 10, gap: 10, flexWrap: "wrap",
                                                    borderTop: "1px solid var(--border)" } },
        React.createElement("span", { className: "dim", style: { fontSize: 12.5 } },
          arbPending
            ? TR("Арбитр ещё не смотрел ") + arbPending + TR(" сегм. — он читает соседние сегменты и говорит, верно ли термин передан здесь")
            : TR("Арбитр посмотрел все спорные сегменты")),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "search",
          disabled: arbBusy || !arbPending, onClick: askArbiter },
          arbBusy ? TR("Спрашиваю…") : TR("Спросить арбитра (") + arbPending + ")")),
      arbWrong.length > 0 && React.createElement(
        "div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.7, paddingTop: 8 } },
        React.createElement("div", { style: { fontWeight: 600, color: "var(--c-warning)" } },
          TR("Арбитр считает запись глоссария неверной для этого документа:")),
        arbWrong.slice(0, DISPUTE_CAP).map((d, i) => React.createElement(
          "div", { key: i },
          d.src + " → ", React.createElement("b", { style: { color: "var(--c-primary)" } }, d.tgt),
          d.use ? [TR(" · здесь верно: "), React.createElement("b", { key: "u", style: { color: "var(--c-success)" } }, d.use)] : "",
          (d.why ? " · " + TRS(d.why) : "") + TR(" · сегментов: ") + d.segments.length,
          d.use && React.createElement(Btn, { variant: "secondary", size: "sm", icon: "check",
            style: { marginLeft: 8 }, disabled: ctxBusy, onClick: () => applyAdvice(d) },
            TR("Применить к ") + d.segments.length + TR(" сегм.")),
          React.createElement(Btn, { variant: "ghost", size: "sm", icon: "warn",
            style: { marginLeft: 4 }, disabled: ctxBusy, onClick: () => demoteAdvised(d) },
            TR("Понизить запись")))),
        arbWrong.length > DISPUTE_CAP && React.createElement(
          "div", null, TR("и ещё ") + (arbWrong.length - DISPUTE_CAP) + TR(" записей")),
        React.createElement("div", { style: { paddingTop: 6 } },
          TR("«Применить» подставляет вариант арбитра только в эти строки — запись глоссария остаётся, и в остальных местах документа она продолжает действовать. ")
          + TR("Если неверна сама запись — правьте её в «Глоссарии», расчёт соответствия приведёт в порядок все затронутые сегменты."))),
      s.human.terms.length > 0 && React.createElement("div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.6, paddingTop: 10, borderTop: "1px solid var(--border)" } },
        TR("Почему термины остались человеку: "),
        s.human.terms.slice(0, 4).map(t => t.count + "× " + t.reason).join(" · "))));
}

/* «Анализ» — экран для того, кому нужен перевод под ключ. Один вопрос, три
   числа и две кнопки: сколько готово, что возьмёт прогон и что требует
   решения человека. Корзины считает СЕРВЕР (/analysis → turnkey) теми же
   предикатами, что и сам прогон, — второй расчёт в браузере однажды
   разошёлся бы с работой. Прежние подвкладки («Замечания», «Доска»,
   «Статистика») убраны: доска раскрашивала длину сегмента как приоритет
   задач, а критичные находки Medical QA на подтверждённых теперь живут
   корзиной human.qaCritical и строкой в «Подробностях». Экспертные карточки
   и ручные команды никуда не делись — они в свёрнутых «Подробностях». */

/* Доля от целого для строк корзин. Один знак после запятой, «100%» без
   хвоста: 2314 из 2670 — это 86.7%, а не 87. */

/* Строка с числом сегментов — ОДНА на весь экран: и корзины «под ключ»,
   и подробный итог ниже. Клик открывает редактор с этими сегментами: цифра,
   на которую нельзя посмотреть, бесполезна. Две копии этой строки жили бы
   на одном экране рядом и разъехались бы молча — а правило «действие справа
   от числа гасит клик по строке» правится только в одном месте.

   `total` — необязателен: с ним строка показывает ещё и долю (корзины «под
   ключ»), без него только число (подробный итог, где часть строк считает
   термины, а не сегменты). `n` можно передать отдельно от `ids` — ровно для
   таких строк без списка. */
function AnalysisRow({ label, hint, ids, n, total, color, action, store, toast, dim }) {
  const count = n != null ? n : (ids || []).length;
  const clickable = !!(ids && ids.length);
  const go = () => {
    if (!clickable) return;
    store.setSegmentFilter(ids);
    store.go("editor");
    toast.info(label, ids.length + TR(" сегментов"));
  };
  return React.createElement("div", {
    className: "row between" + (dim ? " dim" : ""),
    onClick: clickable ? go : null,
    style: { padding: dim ? "8px 0 0" : "10px 0",
             borderTop: dim ? undefined : "1px solid var(--border)", gap: 12,
             fontSize: dim ? 12.5 : undefined,
             cursor: clickable ? "pointer" : "default", alignItems: "baseline" } },
    React.createElement("div", { style: { minWidth: 0 } },
      React.createElement("span", { style: { fontWeight: dim ? 500 : 650, color: color || "var(--text-1)" } }, label),
      hint && React.createElement("span", { className: "dim", style: { fontSize: 12.5 } }, " — " + hint)),
    React.createElement("div", { className: "row", style: { gap: 10, alignItems: "center" } },
      /* Действие живёт СПРАВА от числа и гасит клик по строке: строка ведёт
         в редактор, кнопка меняет текст — путать их нельзя. */
      action && React.createElement("span", { onClick: (e) => e.stopPropagation() }, action),
      React.createElement("b", { style: { fontVariantNumeric: "tabular-nums",
                                          color: count ? (color || "var(--text-1)") : "var(--text-3)" } }, count),
      /* Доля — только там, где целое известно и осмысленно. У строк
         подробного итога `total` не передаётся, и колонки просто нет:
         процент от числа, которое строка не считает, был бы выдумкой. */
      total != null && React.createElement("span", { className: "dim",
        style: { fontSize: 12.5, fontVariantNumeric: "tabular-nums", minWidth: 48, textAlign: "right" } },
        tkPct(count, total))));
}

/* Панель запуска «Перевести и доделать». Состав и параметры — СЕРВЕРНЫЕ:
   run-plan с turnkey.params из /analysis, то есть ровно те, под которые
   посчитана корзина «возьмёт прогон» (судья с разрешением judge_all).
   Смета — тем же estimateRun, что у главной кнопки редактора: второй
   прайс-лист в этом файле означал бы два разных числа под соседними
   кнопками. Модель каждого шага называет сервер (plan.steps[].model).

   Бесплатные правки — именованными галочками, а не молча внутри кнопки:
   «посчитали, показали числа, человек нажал» — закон массовых команд.
   Начертание включено по умолчанию (меняются только заглавные и строчные,
   сочинять там нечему), принятие отменённых баллом правок — выключено:
   оно подменяет текст, и такое решение человек принимает явно. */
/* Тело запроса run-plan: серверные turnkey.params + выбранные модели.
   ОДНО место сборки на оба потребителя (разбор в TurnkeySummary и запуск
   в RunPanel): собери их порознь — и смета считалась бы под одни модели,
   а задача уходила бы под другие. Пустой выбор не отправляется вовсе:
   незаполненная модель шага означает «возьми свою по умолчанию». */
function tkPlanBody(tkParams, mods) {
  const body = Object.assign({}, tkParams);
  Object.keys(mods || {}).forEach(k => { if (mods[k]) body[k] = mods[k]; });
  return body;
}

/* Галочка бесплатной правки. МОДУЛЬНАЯ, а не внутри RunPanel: объявленная
   в теле компонента, она заново рождается на каждый рендер — React считает
   это ДРУГИМ типом и пересоздаёт узел, то есть нажатая галочка теряет фокус
   на собственном клике. */
function FreeFixCheck({ on, setOn, label, note }) {
  return React.createElement("label", {
    className: "row", style: { gap: 8, alignItems: "flex-start", cursor: "pointer", fontSize: 13 } },
    React.createElement("input", { type: "checkbox", checked: on,
      onChange: (e) => setOn(e.target.checked), style: { marginTop: 3 } }),
    React.createElement("span", null, label,
      React.createElement("span", { className: "dim" }, " — " + note)));
}

/* Какой параметр run-plan/задачи отвечает за модель шага. Зеркалит
   FULL_STEP_MODEL сервера; Medical QA своей модели не имеет — она берёт
   модель back-check для обратного перевода. */
/* Зеркало FULL_STEP_MODEL на сервере. Забыть шаг здесь — значит показать
   у него чужую подпись («модель back-check», ветка Medical QA ниже) и не
   отправить его модель в задачу. */
const STEP_MODEL_PARAM = { translate: "model", backcheck: "bc_model",
                           termcheck: "tc_model", termaudit: "tcx_model",
                           repair: "rp_model", review: "rv_model" };

/* Подсказки о моделях, которые противоречат друг другу по РОЛИ, а не
   по силе. Само правило — ОДНО на все экраны (`modelRoleConflicts` в ui.jsx):
   ту же пару шагов разбирает админка, где эти модели назначают на всю систему.
   Здесь только «что считать действующей моделью»: то, что сервер назвал
   в разборе (plan.steps[].model), — выбор «по умолчанию» тоже может совпасть
   с моделью перевода, и молчать о нём нельзя. */
function modelConflicts(plan, cat, mods) {
  const eff = {};
  (plan && plan.steps || []).forEach(st => { eff[st.step] = st.model; });
  eff.judge = (mods && mods.judge_model) || (cat && cat.judgeDefault) || "";
  const label = (id) => {
    const m = (cat && cat.models || []).find(x => x.id === id);
    return m ? m.label : (id || "?");
  };
  return modelRoleConflicts(eff, label).map(c => c.text);
}

function RunPanel({ summary, store, toast, onClose, onStarted, plan, cat, mods, setMod,
                    tkParams, fixConf, setFixConf, confN }) {
  const project = store.activeProject;
  const tk = summary.turnkey;
  /* Выбор моделей из браузера — только в виде эксперта, где его видно
     (инвариант 24: скрытая настройка — честное умолчание). Иначе в задачу
     молча уезжала модель, выбранная когда-то в редакторе, мимо «Моделей
     шагов» в админке, — и смета считалась по ней же. */
  const mm = store.expert ? (mods || {}) : {};
  /* Те же ДВА рубежа, что в редакторе (инвариант 24), и путать их нельзя.
     УСТРОЙСТВО прогона — выбор моделей, действующая модель, цена по шагам —
     системному администратору: выбирать модель человеку, который не знает
     целевого языка, нечем, а ошибка стоит денег. СМЕТА — тому, кто платит.
     Панель «Анализа» рубежа роли не знала вовсе: её единственным условием
     был тенантный `simple` (инвариант 22), то есть переводчик видел здесь
     ровно ту таблицу моделей, которую редактор ему не показывает. Состав
     (шаг и сколько сегментов) остаётся всем: это обещание работы, а не
     устройство. */
  const expert = !!store.expert;
  const showCost = !!(store.can && (store.can.owner || store.can.super));
  /* Называются ли модели — ОДНО правило на все экраны (modelsShown в ui.jsx):
     копия предиката здесь разошлась бы с карточкой сегмента и импортом, а
     разойтись ей нельзя — пропущенное место и есть утечка. */
  const showModels = modelsShown(store);
  const [busy, setBusy] = useState(false);
  const caseIds = tk.case || [];
  const accIds = (summary.human || {}).revertedByScore || [];
  const [fixCase, setFixCase] = useState(true);
  const [fixAcc, setFixAcc] = useState(false);

  // Смета по шагам. estimateRun живёт в tab_editor.jsx (модульная функция),
  // guard нужен тестам, которые грузят только этот файл.
  // useMemo обязателен: считается она по ВСЕМ сегментам проекта (2670 на
  // боевом), а перерисовок у панели много — каждая галочка и каждый «занято».
  const est = useMemo(() => {
    if (!plan || !cat || typeof estimateRun !== "function") return null;
    const byId = {};
    (cat.models || []).forEach(m => { byId[m.id] = m; });
    const segById = {};
    (project.segments || []).forEach(sg => { segById[sg.id] = sg; });
    // Судья — выбранный здесь либо дефолт сервера; сам он в plan.steps
    // не значится, потому что вызывается внутри back-check и ремонта.
    const judgeM = byId[mm.judge_model || cat.judgeDefault];
    const bcStep = (plan.steps || []).find(x => x.step === "backcheck") || {};
    let cost = 0, unknown = false;
    const rows = (plan.steps || []).map(st => {
      const targets = (st.ids || []).map(i => segById[i]).filter(Boolean);
      const model = byId[st.model] || null;
      // Ремонт судится симметрично прежней оценке, и в прогоне с разрешением
      // прежняя могла сложиться выше обычной зоны — значит judgeAll и здесь,
      // ровно как на сервере (_run_segment_repair → judge_all).
      const opts = st.step === "backcheck"
        ? { judge: true, judgeModel: judgeM, judgeAll: true }
        : st.step === "repair"
          ? { judge: true, judgeModel: judgeM, judgeAll: true,
              recheckModel: byId[bcStep.model] }
          : null;
      // Сервер назвал сегменты, а в копии браузера их нет (её могли не
      // подтянуть после разбора картинок) — это «не знаю», а не «бесплатно».
      // Ноль здесь ушёл бы на кнопку как «≈ $0.00» за настоящую платную
      // работу и в est_cost, которым калибруется поправка estRatio.
      const missing = (st.ids || []).length > 0 && targets.length === 0;
      const e = targets.length ? estimateRun(st.step, targets, model, opts)
                               : { cost: missing ? null : 0, count: 0 };
      if (e.cost == null) unknown = true; else cost += e.cost || 0;
      return { step: st.step, label: st.label, count: st.count,
               modelLabel: st.modelLabel, cost: e.cost };
    });
    return { rows, cost, unknown, byStep: rows.reduce((a, r) => (a[r.step] = r, a), {}) };
  }, [plan, cat, project && project.id, mm.judge_model]);

  const run = async () => {
    if (busy || !plan || !window.API) return;
    setBusy(true);
    // Второй прогон поверх идущего — очередь на сервере и два счётчика
    // об одном на экране. Спрашиваем сервер, а не свою память: прогон могли
    // запустить из другой вкладки.
    const jl = await window.API.safeCall(() => window.API.listJobs(project.id));
    if (jl && (jl.active || []).length) {
      setBusy(false);
      toast.warning(TR("Прогон уже идёт"), TR("Дождитесь окончания — прогресс в «Редакторе»."));
      return;
    }
    const pull = async (ids) => {
      if (!ids || !ids.length || !window.API.fetchSegments) return;
      const got = await window.API.safeCall(() => window.API.fetchSegments(project.id, ids));
      store.mergeServerSegments(project.id, got && got.segments);
    };
    let freeFixed = false;
    if (fixCase && caseIds.length) {
      // Ровно те сегменты, что названы на галочке: без списка сервер правит
      // весь проект, включая ушедшие человеку, — и число на галочке врало бы.
      const r = await window.API.safeCall(
        () => window.API.termCase(project.id, { apply: true, segmentIds: caseIds }));
      if (r && r.ok) {
        await pull(r.ids);
        freeFixed = true;
        toast.success(TR("Начертание приведено к оригиналу"), r.segments + TR(" сегм. — без вызова модели"));
      } else {
        toast.error(TR("Начертание не поправилось"), (r && r.error) || TR("сервер не ответил"));
      }
    }
    if (fixAcc && accIds.length) {
      const r = await window.API.safeCall(() => window.API.acceptRepairBatch(project.id, { dry_run: false }));
      if (r && r.ok) {
        await pull(r.ids);
        freeFixed = true;
        toast.success(TR("Принято правок: ") + r.accepted,
          TR("откат — по метке ") + (r.stamp || "—") + TR("; этот же прогон их перепроверит"));
      } else {
        toast.error(TR("Правки не принялись"), TR("Сервер отказал."));
      }
    }
    // Состав берём ПОСЛЕ бесплатных правок: принятые тексты стали
    // непроверенными и обязаны попасть в этот же прогон, а не в следующий.
    const fresh = freeFixed
      ? await window.API.safeCall(() => window.API.runPlan(project.id, tkPlanBody(tkParams || tk.params, mm)))
      : plan;
    const ids = (fresh && fresh.ids) || [];
    if (!ids.length) {
      setBusy(false);
      toast.info(TR("Прогону нечего делать"), TR("Все проверки свежие."));
      if (onStarted) onStarted();
      onClose();
      return;
    }
    // est_cost — то самое число, что человек видел на кнопке: рядом с фактом
    // оно и калибрует поправку estRatio. Модели — те же, под которые считан
    // разбор (tkPlanBody): задача с другими моделями сделала бы другую работу.
    const params = Object.assign(tkPlanBody(tkParams || tk.params, mm),
      est && est.cost != null ? { est_cost: est.cost } : {});
    const res = await window.API.safeCall(() => window.API.createJob(project.id, "full", ids, params));
    setBusy(false);
    if (!res || !res.ok) { toast.error(TR("Не удалось запустить"), TR("Сервер не принял задачу.")); return; }
    // Снимок состава для полосы прогона в редакторе — та же тройка опознания
    // «номер + проект + время создания», что и у запуска из редактора.
    if (typeof writeRunSnap === "function" && fresh && fresh.steps) {
      const planned = {};
      (fresh.steps || []).forEach(st => { planned[st.step] = st.count; });
      writeRunSnap({ jobId: res.job.id, project: res.job.project,
                     created: res.job.created, steps: planned });
    }
    toast.info(TR("Прогон запущен"), ids.length + TR(" сегм. — прогресс в «Редакторе», вкладку можно закрыть."));
    if (onStarted) onStarted();
    store.go("editor");
  };

  const extra = plan && plan.total != null
    ? Math.max(0, plan.total - (tk.machine || []).length) : 0;
  return React.createElement("div", { className: "card card-pad",
    style: { marginTop: 10, display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "row between" },
      React.createElement("span", { style: { fontWeight: 500 } }, TR("Что сделает прогон")),
      plan === false && React.createElement("span", { className: "dim", style: { fontSize: 12.5 } },
        TR("разбор не получен — обновите страницу"))),
    !plan && plan !== false && React.createElement("div", { className: "dim", style: { fontSize: 13 } }, TR("Считаем состав…")),
    /* Шаги — СЕТКОЙ (.tk-grid в styles.css), а не флексом: у флекса текст
       действующей модели сжимался до ширины одного слова и вставал столбиком,
       а селектор судьи растягивался на всю строку. Четыре колонки — шаг,
       выбор, действующая модель, состав·цена; ниже 720 px сетка складывается
       в две, и строка занимает две линии вместо четырёх столбиков. */
    plan && React.createElement("div", { className: showModels ? "tk-grid" : "tk-grid tk-grid-plain" },
      (plan.steps || []).map(st => {
        const row = est && est.byStep[st.step];
        const pkey = STEP_MODEL_PARAM[st.step];
        return React.createElement(React.Fragment, { key: st.step },
          React.createElement("span", { className: "tk-label" }, st.label),
          /* Модель шага — выбирается тут же, а не только в редакторе; пустой
             выбор = дефолт сервера, действующая модель названа рядом. У Medical
             QA селектора нет: своей модели у неё нет, обратный перевод она
             заказывает моделью back-check. Без устройства колонок нет вовсе:
             пустые ячейки оставили бы полстроки дыры между шагом и составом. */
          showModels && (pkey && setMod
            ? React.createElement(Select, { className: "select tk-select", value: mm[pkey] || "",
                onChange: (e) => setMod(pkey, e.target.value) },
                React.createElement("option", { value: "" }, TR("по умолчанию")),
                (cat && cat.models || []).map(m => React.createElement("option", { key: m.id, value: m.id }, m.label)))
            : React.createElement("span", { className: "dim tk-select" }, TR("модель back-check"))),
          showModels && React.createElement("span", { className: "dim tk-eff", title: st.modelLabel || "" },
            st.modelLabel ? "→ " + st.modelLabel : ""),
          React.createElement("span", { className: "dim tk-cost" },
            st.count + TR(" сегм.") + (showModels && row && row.cost != null && typeof fmtCost === "function"
              ? " · ≈ " + fmtCost(row.cost) : "")));
      }),
      /* Судья — не шаг, а участник back-check и ремонта: та же сетка. */
      showModels && setMod && React.createElement(React.Fragment, { key: "judge" },
        React.createElement("span", { className: "tk-label" }, TR("судья")),
        React.createElement(Select, { className: "select tk-select", value: mm.judge_model || "",
          onChange: (e) => setMod("judge_model", e.target.value) },
          React.createElement("option", { value: "" }, TR("по умолчанию")),
          (cat && cat.models || []).map(m => React.createElement("option", { key: m.id, value: m.id }, m.label))),
        React.createElement("span", { className: "dim tk-eff", title: TR("в back-check и перепроверке ремонта, с разрешением выше зоны") },
          TR("в back-check и ремонте, выше зоны")),
        React.createElement("span", { className: "dim tk-cost" }, ""))),
    /* Модели, спорящие друг с другом по роли, — вслух и до нажатия. Только тому,
       кто модели и выбирает: подсказка называет модели поимённо и просит
       выбрать другую — тому, у кого выбора нет, это тревога без двери. */
    plan && showModels && modelConflicts(plan, cat, mm).map((w, i) => React.createElement("div", { key: "w" + i,
      style: { fontSize: 12.5, color: "var(--c-warning)", lineHeight: 1.5 } }, "⚠ " + w)),
    plan && extra > 0 && React.createElement("div", { className: "dim", style: { fontSize: 12.5 } },
      TR("В состав входят и готовые сегменты — освежить проверки (") + extra + TR(" сегм. сверх корзины).")),
    /* Про смету — тому, кто платит; про судью — тому, кто видит устройство. */
    plan && ((showCost && !costHidden()) || showModels) && React.createElement("div", { className: "dim", style: { fontSize: 12.5 } },
      (showCost && !costHidden()
        ? TR("Смета — нижняя граница: проверки этого же прогона могут добавить работы ремонту. ") : "")
      + (showModels
        ? TR("Судья идёт с разовым разрешением смотреть и бесспорные сегменты (балл выше зоны).") : "")),
    (caseIds.length > 0 || accIds.length > 0) && React.createElement("div", {
      style: { display: "flex", flexDirection: "column", gap: 6, paddingTop: 8,
               borderTop: "1px solid var(--border)" } },
      React.createElement("span", { style: { fontWeight: 500, fontSize: 13 } }, TR("Заодно бесплатно, без вызова модели:")),
      caseIds.length > 0 && React.createElement(FreeFixCheck, { on: fixCase, setOn: setFixCase,
        label: TR("Привести начертание терминов к оригиналу (") + caseIds.length + TR(" сегм.)"),
        note: TR("меняются только заглавные и строчные, слова и порядок те же") }),
      accIds.length > 0 && React.createElement(FreeFixCheck, { on: fixAcc, setOn: setFixAcc,
        label: TR("Принять правки, отменённые только баллом (") + accIds.length + TR(" сегм.)"),
        note: TR("текст уже написан и оплачен; заверенное человеком не трогается, копия уйдёт в бэкап, этот же прогон всё перепроверит") })),
    /* Разрешение переписать ЗАВЕРЕННОЕ — не бесплатная правка, а решение
       человека на этот прогон (include_confirmed). Стоит отдельно и прямо над
       кнопкой запуска: оно снимает отметки «подтвердил», и увидеть это
       надо до нажатия. Разбор пересчитывается под него у родителя. */
    setFixConf && confN > 0 && React.createElement("div", {
      style: { display: "flex", flexDirection: "column", gap: 6, paddingTop: 8,
               borderTop: "1px solid var(--border)" } },
      React.createElement(FreeFixCheck, { on: !!fixConf, setOn: setFixConf,
        label: TR("Чинить и заверенные вами (") + confN + TR(" сегм.)"),
        note: TR("только по найденным ошибкам; прежний текст уйдёт в «прошлый перевод», отметка «подтвердил человек» снимется") })),
    React.createElement("div", { className: "row", style: { gap: 8, paddingTop: 4 } },
      /* Запуск гаснет, когда делать нечего ВООБЩЕ: ни состава у прогона,
         ни включённой бесплатной правки. && связывает сильнее || — скобки
         вокруг трёх последних не нужны, но читаются лучше. */
      React.createElement(Btn, { variant: "primary",
        disabled: busy || !plan || (!(plan.ids || []).length
          && !(fixCase && caseIds.length) && !(fixAcc && accIds.length)),
        onClick: run },
        busy ? TR("Запускаем…")
          /* Смета на кнопке — тому, кто платит: у владельца это единственное
             число, по которому он решает, запускать ли книгу; переводчику деньги
             не его дело — тот же рубеж, что у EstLine в редакторе. */
          : TR("Запустить") + (showCost && est && est.cost != null && typeof fmtCost === "function"
              ? " · ≈ " + fmtCost(est.cost) + (est.unknown ? "+" : "") : "")),
      React.createElement(Btn, { variant: "ghost", disabled: busy, onClick: onClose }, TR("Отмена"))));
}

/* Полоса готовности «Проверки»: процент, полоса трёх цветов, легенда и ОДНА
   кнопка «Доделать сама». Средняя корзина («доделает машина») показана
   КНОПКОЙ, а не третьим числом: это не состояние текста, а невыполненная
   работа. Суммы при этом сходятся: готово + кнопка + вопросы = всё.
   Корзины карточками, срезы «из них» и «ревизия ручается» — эксперту
   (`expert`, store.can.super): человеку отвечает список вопросов ниже. */
function TurnkeySummary({ summary, store, toast, onReload, expert }) {
  const tk = summary.turnkey;
  const total = summary.total || 0;
  const ready = tk.ready || [], machine = tk.machine || [], human = tk.human || [];
  /* Те же группы по действию, что в «Подробностях» (analysisHumanGroups).
     «Править оригинал» — подписью под готовностью: перевод там сделан,
     насколько позволяет исходник, и бить им по проценту перевода нечестно. */
  const groups = analysisHumanGroups(summary);
  const srcN = (groups.find(g => g.key === "source") || { n: 0 }).n;
  const [panel, setPanel] = useState(false);
  /* Разбор прогона держит РОДИТЕЛЬ, а не панель. Панель монтируется по
     нажатию, и её собственный useEffect гонял бы /run-plan на каждое
     открытие — а это пять проходов по всему проекту на ЕДИНСТВЕННОМ воркере.
     Здесь он считается один раз на загруженный итог: сам итог
     перезагружается после прогона и правок, то есть свежесть у них общая. */
  const [plan, setPlan] = useState(null);
  const [cat, setCat] = useState(null);
  /* Модели по шагам. Источник — ТЕ ЖЕ ключи localStorage, что у карточек
     редактора (window.MODEL_LS из tab_editor.jsx): второго хранилища одного
     выбора нет. Выбор влияет и на СОСТАВ, поэтому смена модели
     перезапрашивает разбор — тем же телом, каким потом уйдёт задача. */
  const [mods, setMods] = useState(() => {
    const out = {}, keys = window.MODEL_LS || {};
    Object.keys(keys).forEach(k => {
      try { out[k] = localStorage.getItem(keys[k]) || ""; } catch (e) { out[k] = ""; }
    });
    return out;
  });
  const setMod = (k, v) => {
    setMods(m => Object.assign({}, m, { [k]: v }));
    const keys = window.MODEL_LS || {};
    if (keys[k]) {
      try { v ? localStorage.setItem(keys[k], v) : localStorage.removeItem(keys[k]); }
      catch (e) { /* приватный режим — выбор живёт до перезагрузки */ }
    }
  };
  /* Разрешение чинить ЗАВЕРЕННОЕ (include_confirmed) — единственная дверь
     к корзинам «заверено, но есть находки» у того, кто не видит строки
     «Ремонт». Разрешение на ОДИН прогон: живёт в памяти компонента, а он
     пересоздаётся при смене проекта (key у TabAnalysis), в localStorage
     не пишется. Разбор считается ПОД него же — иначе строка обещала бы одно,
     а прогон делал другое. */
  const [fixConf, setFixConf] = useState(false);
  const runParams = Object.assign({}, tk.params, fixConf ? { include_confirmed: true } : {});
  /* Число на галочке — из тех же групп, что и вопросы (там списки уже
     сужены до корзины «нужен человек»): два числа об одном расходились бы. */
  const confN = new Set([].concat.apply([], [].concat.apply([], groups.map(g => g.rows))
    .filter(r => r.key === "confirmedFindings" || r.key === "glossaryConfirmed")
    .map(r => r.ids))).size;
  useEffect(() => {
    if (!window.API || !store.activeProject) return;
    let dead = false;
    /* Прежний разбор снимаем СРАЗУ: пока новый в пути, «Запустить» ушло бы
       со старыми ids и новым include_confirmed — работа разошлась бы со сметой. */
    setPlan(null);
    Promise.all([
      window.API.safeCall(() => window.API.runPlan(store.activeProject.id, tkPlanBody(runParams, store.expert ? mods : null))),
      window.API.safeCall(() => window.API.models()),
    ]).then(([p, m]) => { if (!dead) { setPlan(p || false); setCat(m || null); } });
    return () => { dead = true; };
  }, [store.activeProject && store.activeProject.id, summary, mods, fixConf, store.expert]);
  /* Тернарник, а не `total && ...`: при total === 0 такое выражение даёт
     ЧИСЛО 0, и React честно печатает его. */
  const seg = (n, color) => (total > 0 && n > 0)
    ? React.createElement("div", {
        style: { width: (n / total * 100) + "%", background: color, height: "100%" } })
    : null;
  const dot = (color) => React.createElement("i", { style: { background: color } });

  const strip = React.createElement("div", { className: "ready-strip" },
    React.createElement("div", { className: "ready-pct" }, tkPct(ready.length, total),
      React.createElement("small", null, TR("готово"))),
    React.createElement("div", null,
      React.createElement("div", { className: "ready-meter", role: "img",
          "aria-label": tkPct(ready.length, total) + " " + TR("готово") },
        seg(ready.length, "var(--c-success)"),
        seg(machine.length, "var(--c-primary)"),
        seg(human.length, "var(--c-warning)")),
      /* Три цвета без подписей — украшение. Легенда обязательна. */
      React.createElement("div", { className: "ready-legend" },
        React.createElement("span", null, dot("var(--c-success)"), ready.length + TR(" из ") + total + TR(" строк")),
        React.createElement("span", null, dot("var(--c-primary)"), TR("доделаю сама") + " · " + machine.length),
        React.createElement("span", null, dot("var(--c-warning)"), TR("спрошу вас") + " · " + human.length),
        srcN > 0 && React.createElement("span", null, srcN + TR(" ждут правки оригинала")))),
    React.createElement("div", { className: "ready-cta" },
      /* Кнопка открыта и при пустой машинной корзине, если есть заверенное
         с находками: галочка «чинить и заверенные» живёт в панели, и другой
         двери к этой корзине у человека нет (инвариант 24). */
      React.createElement(Btn, { variant: "primary", icon: "zap", disabled: !machine.length && !confN,
        onClick: () => setPanel(p => !p) },
        machine.length ? TR("Доделать сама") + " · " + machine.length + TR(" строк")
          : confN ? TR("Доделать сама") : TR("Машине делать нечего"))));

  const expertCard = expert && React.createElement("div", { className: "section" },
    React.createElement("h2", { className: "section-title" }, TR("Перевод под ключ"),
      React.createElement(InfoTip, { title: TR("Три корзины"),
        body: TR("Каждый сегмент проекта ровно в одной корзине, суммы сходятся с общим числом — считает сервер теми же правилами, что и сам прогон.\n\n«Готово» — переведено, проверено, открытых вопросов нет.\n\n«Возьмёт прогон» — кнопка «Перевести и доделать»: перевод, проверки, судья (включая бесспорные по разовому разрешению), ремонт по находкам.\n\n«Нужно ваше решение» — то, что прогон не решает по построению: споры с глоссарием, заверенные сегменты с находками, откаченные правки. Команды — в «Подробностях» ниже.\n\nЛюбая строка открывает редактор с этими сегментами.") })),
    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column" } },
      /* Три корзины — КАРТОЧКАМИ: это три разных места, куда человек идёт
         с разными намерениями. Четвёртая — срез «заверено вручную»: он
         входит в корзины выше и потому приглушён. */
      React.createElement("div", { className: "st-cards" },
        React.createElement(BucketCard, { store, toast, total, ids: ready, tone: "ok",
          label: TR("Готово к сдаче"), hint: TR("переведено и проверено, открытых вопросов нет") }),
        React.createElement(BucketCard, { store, toast, total, ids: machine, tone: "mach",
          label: TR("Возьмёт ближайший прогон"), hint: TR("перевод, проверки, судья и ремонт по находкам"),
          action: React.createElement(Btn, { variant: "primary", size: "sm", icon: "zap",
            onClick: (e) => { e.stopPropagation(); setPanel(p => !p); } }, TR("Перевести и доделать")) }),
        React.createElement(BucketCard, { store, toast, total, ids: human, tone: "hum",
          label: TR("Нужно ваше решение"), hint: TR("прогон это не решит — состав и команды в «Подробностях»") }),
        React.createElement(BucketCard, { store, toast, ids: tk.confirmed || [], tone: "mine", dim: true,
          label: TR("Заверено вручную"), hint: TR("входит в корзины выше") })),
      groups.filter(g => g.n > 0).map(g => React.createElement(AnalysisRow, {
        key: g.key, store, toast, ids: g.ids, n: g.n, dim: true,
        total: g.key === "records" ? undefined : total,
        label: TR("из них: ") + g.label.charAt(0).toLowerCase() + g.label.slice(1), hint: g.hint })),
      /* Претензии слепых измерителей снял свежий вердикт ревизии — сегменты
         в «Готово». Срезом, а не молча: снятое без следа неотличимо
         от потерянного. Старый сервер поля не отдаёт — строки нет. */
      (tk.reviewVouched || []).length > 0 && React.createElement(AnalysisRow, {
        store, toast, total, ids: tk.reviewVouched, dim: true,
        label: TR("Ревизия ручается — претензии проверок сняты"),
        hint: TR("ревизор прочитал пару целиком и не нашёл дефекта; входит в «Готово»") })));

  return React.createElement(React.Fragment, null,
    strip,
    panel && React.createElement(RunPanel, { summary, store, toast, plan, cat, mods, setMod,
      tkParams: runParams, fixConf, setFixConf, confN,
      onClose: () => setPanel(false), onStarted: onReload }),
    expertCard || null);
}

/* Журнал решений: что применили и чем это откатить.

   До него отката в интерфейсе фактически не было — метка копии называлась
   один раз всплывающей подсказкой, и закрытая подсказка уносила её навсегда.
   Список даёт сервер (`GET /decisions`, кольцо на проекте), откат идёт теми же
   эндпоинтами, что и раньше; откаченная запись остаётся видна и гаснет —
   пропавшая строка выглядела бы так, будто решения и не было.
   Показываются ТОЛЬКО команды, у которых дверь отката существует: кнопка
   «Отменить», которая ничего не отменяет, хуже её отсутствия. */
const DEC_UNDO = {
  repair: (pid, st) => window.API.undoAcceptRepair(pid, st),
  review: (pid, st) => window.API.undoReview(pid, st),
  termctx: (pid, st) => window.API.termContextUndo(pid, st),
  style: (pid, st) => window.API.styleUndo(pid, st),
};
const DEC_LABEL = {
  repair: TR("Приняли готовые тексты"),
  review: TR("Поставили советы ревизии"),
  termctx: TR("Подставили совет по термину"),
  style: TR("Исправили орфографию"),
};
function CheckLog({ project, store, toast, onReload }) {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState("");
  const load = () => {
    if (!window.API || !window.API.decisions || !project) return;
    window.API.safeCall(() => window.API.decisions(project.id))
      .then(r => { if (r && r.ok) setRows(r.decisions || []); });
  };
  useEffect(() => { setRows(null); load(); }, [project && project.id]);
  if (!rows || !rows.length) return null;
  const undo = (d) => {
    const fn = DEC_UNDO[d.kind];
    if (!fn || busy) return;
    if (!window.confirm(TR("Вернуть как было? Это отменит: ")
        + (DEC_LABEL[d.kind] || d.kind) + " · " + d.count + TR(" сегм.")
        + "\n\n" + TR("Строки, которые правили ПОСЛЕ, не трогаем — их назову числом."))) return;
    setBusy(d.stamp);
    window.API.safeCall(() => fn(project.id, d.stamp)).then(async (r) => {
      setBusy("");
      if (!r || !r.ok) { toast.error(TR("Не удалось отменить"), TR("Сервер отказал.")); return; }
      const back = (r.restored || []).length;
      const kept = (r.changedSince || []).length;
      toast.success(TR("Вернули как было: ") + back + TR(" сегм."),
        kept ? TR("правленых после не трогали: ") + kept : "");
      /* Вернувшиеся тексты тянем поимённо: проект весит мегабайты, а в браузере
         иначе остался бы текст, которого на сервере уже нет. */
      if (back && window.API.fetchSegments) {
        const got = await window.API.safeCall(
          () => window.API.fetchSegments(project.id, r.restored));
        store.mergeServerSegments(project.id, got && got.segments);
      }
      load();
      if (onReload) onReload();
    });
  };
  return React.createElement("div", { className: "ask-stack" },
    React.createElement("div", { className: "ask-stack-h" },
      React.createElement("span", null, TR("Журнал решений")),
      React.createElement("span", { className: "ask-n" }, TR("отменить можно любое"))),
    React.createElement("div", { className: "ask-list" },
      rows.map((d, i) => React.createElement("div", { key: d.stamp + ":" + i, className: "ask ask-quiet" },
        React.createElement("span", { className: "ask-sev" }),
        React.createElement("div", { className: "ask-cell" },
          React.createElement("div", { className: "ask-t" }, DEC_LABEL[d.kind] || d.kind),
          React.createElement("div", { className: "ask-m" },
            (d.name ? d.name + " · " : "") + d.at + (d.note ? " · " + d.note : ""))),
        React.createElement("div", { className: "ask-where" }, d.undone ? TR("уже отменено") : ""),
        React.createElement("div", { className: "ask-acts" },
          !d.undone && DEC_UNDO[d.kind] && React.createElement(Btn,
            { variant: "ghost", size: "sm", disabled: busy === d.stamp, onClick: () => undo(d) },
            busy === d.stamp ? TR("Отменяем…") : TR("Отменить"))),
        React.createElement("div", { className: "ask-scope" }, d.count + TR(" сегм."))))));
}

/* «Вопросы к вам» — ТАБЛИЦА из четырёх колонок: что не так · где · ваш ответ ·
   сколько изменится. Выровнена сеткой (`.ask-list` + `.ask`): строки разной
   длины без колонок читаются как разъехавшийся список, и это была первая
   жалоба на экран.
   Состав — те же группы по действию (analysisHumanGroups), команды — тот же
   хук (useAnalysisCommands): предпросмотр, подтверждение и откат у них общие.
   **Раскладка идёт по ФАКТУ наличия команды, а не по списку ключей.** Строка,
   у которой есть что нажать, — вопрос и стоит в таблице; строка, у которой
   есть только «Открыть», — не вопрос: ответа у неё нет, и колонка «ваш ответ»
   стояла бы пустой. Такие уходят вниз, в «Просмотреть глазами». Список ключей
   разошёлся бы с `analysisHumanGroups` первой же правкой политики, а потерянная
   строка означает сегменты, которых на экране нет вовсе, — то есть картину
   благополучнее, чем есть.
   Два исхода стоят особняком: снятая отметка «проверено» идёт ПОЛОСОЙ НАД
   таблицей (это извещение, а не вопрос, и по инварианту 14 оно обязано быть
   громким), повреждённый оригинал — своей строкой внизу: там правят книгу,
   а не перевод, и в общую стопку «просмотрите» он не годится.
   Заголовки здесь СВОИ (`ASK_TITLE`): «ревизия», «судья», «back-check» —
   имена деталей внутри, и на первом экране их быть не должно (инвариант 32).
   У экспертного итога (`WorkSummary`) заголовки те же, что были. */
const ASK_TOP = 10;
const ASK_TITLE = {
  reviewConfirmed: TR("Я перечитала эти строки и предлагаю другой перевод"),
  reviewFlagged: TR("Вижу проблему, но починить не смогла"),
  weak: TR("Перевела обратно — вышло другое"),
  reverted: TR("Пробовала исправить, вышло хуже — оставила как было"),
  revertedByScore: TR("Готовый текст ждёт вашего «да»"),
  staleFindings: TR("Слово, которое я забраковала, осталось в тексте"),
  confirmWithdrawn: TR("Я поправила строки, которые вы отметили как проверенные"),
  glossaryConfirmed: TR("Вы отметили строки, а перевод спорит со словарём"),
  confirmedFindings: TR("Вы отметили строки как проверенные, а я нашла ошибку"),
  qaCritical: TR("Вы отметили строки, а в них критичное замечание"),
  sourceSuspect: TR("Похоже, в книге испорчен сам текст"),
};
function CheckQuestions({ summary, store, toast, onReload }) {
  const { acceptAll, accBusy, applyHeldReview, rvBusy, applyAdvice, demoteAdvised, ctxBusy } =
    useAnalysisCommands(store, toast, onReload);
  const [all, setAll] = useState(false);
  const h = summary.human || {};
  const groups = analysisHumanGroups(summary);
  const open = (label, ids) => {
    if (!ids || !ids.length) return;
    store.setSegmentFilter(ids);
    store.go("editor");
    toast.info(label, ids.length + TR(" сегментов"));
  };
  const btn = (key, label, onClick, variant, disabled) => React.createElement(Btn,
    { key, variant: variant || "ghost", size: "sm", disabled: !!disabled, onClick }, label);
  /* У заверенных с находками подсказка групп ведёт к строке «Ремонт», которой
     человек на этом экране не видит. Дверь у него — галочка «чинить
     и заверенные» в панели «Доделать сама», и назвать надо её. */
  const HINT = {
    confirmedFindings: TR("вы заверили, но проверки нашли ошибки — починит «Доделать сама» с галочкой «чинить и заверенные»"),
    glossaryConfirmed: TR("вы заверили, но перевод расходится со словарём — починит «Доделать сама» с галочкой «чинить и заверенные»"),
  };
  /* «Где» — адрес, а не пересказ: номер строки человек видит в таблице
     редактора, и по нему же работает переход по номеру. Больше двух номеров
     не называем: адрес из десяти чисел перестаёт быть адресом. */
  const whereSegs = (ids) => {
    const a = ids || [];
    if (!a.length) return "";
    if (a.length === 1) return TR("строка ") + a[0];
    return TR("строки ") + a.slice(0, 2).join(", ")
      + (a.length > 2 ? TR(" и ещё, всего: ") + a.length : "");
  };
  const loud = r => r.color === "var(--c-error)" ? 1 : 0;
  /* Группа `records` (термины, споры со словарём, вердикты арбитра) ниже
     разбирается ПОШТУЧНО — по строке на запись, с её командой. Пустить её
     сюда значит показать те же три решения дважды: сырой строкой без кнопок
     и разобранной с кнопками. */
  const segRows = [].concat.apply([], groups.filter(g => g.key !== "records").map(g => g.rows))
    .sort((a, b) => (loud(b) - loud(a)) || (b.n - a.n));
  const qs = [], stack = [];
  let alarm = null, source = null;
  segRows.forEach(r => {
    const title = ASK_TITLE[r.key] || r.label;
    const meta = HINT[r.key] || r.hint;
    /* Команда — то, что РЕШАЕТ. «Открыть» решением не является: она уводит
       смотреть, и строка с одной этой кнопкой вопросом не считается. */
    const cmds = [];
    if (r.key === "revertedByScore")
      cmds.push(btn("acc", accBusy ? TR("Принимаем…") : TR("Принять все"), acceptAll, "secondary", accBusy));
    if (r.key === "reviewConfirmed")
      cmds.push(btn("rv", rvBusy ? TR("Применяем…") : TR("Применить советы"), () => applyHeldReview(r.ids), "secondary", rvBusy));
    const item = { key: r.key, sev: loud(r) ? "bad" : "warn", title, meta,
                   where: whereSegs(r.ids), ids: r.ids,
                   scope: r.n + TR(" строк"), acts: cmds.slice() };
    if (r.ids.length) item.acts.push(btn("open", TR("Открыть"), () => open(title, r.ids)));
    if (r.key === "confirmWithdrawn") { alarm = item; return; }
    if (r.key === "sourceSuspect") { source = item; return; }
    if (cmds.length) qs.push(item); else stack.push(item);
  });
  /* Термины: тот же состав, что очередь «Словарей» для человека (actionable):
     ждущие решения плюс готовые к одобрению. Ждущие ДАННЫХ сюда не входят —
     их дорешает прогон, и они названы в подвале. В колонке охвата стоит число
     РЕШЕНИЙ, а не строк: сколько строк документа закроет ответ по термину,
     `/analysis` не считает, и написать там «строк» значило бы соврать. */
  const termsN = (h.termsTotal || 0) + ((summary.proposed || {}).terms || 0);
  if (termsN > 0) qs.push({ key: "terms", sev: "warn",
    title: termsN + TR(" терминов ждут ответа «верно / не то»"),
    meta: TR("ответ в «Словарях» закрывает все строки с термином"), where: "",
    scope: termsN + TR(" решений"),
    acts: [btn("go", TR("Открыть Словари"), () => store.go("glossary"), "secondary")] });
  /* Записи словаря: одно решение на ЗАПИСЬ закрывает все её строки. Запись,
     про которую уже ответил арбитр, в спорах второй раз не считается — тот же
     ключ, что у analysisHumanGroups. Сама пара и есть «где»: кусок текста
     человеку, который целевого языка не знает, ничего не скажет, а пара
     «было → надо» читается на любом языке. */
  const rkey = d => ((d.src || "") + "→" + (d.tgt || "")).toLowerCase();
  const ctxWrong = h.termContextWrong || [];
  const ctxKeys = new Set(ctxWrong.map(rkey));
  const disputes = (h.termcheckDisputes || []).filter(d => !ctxKeys.has(rkey(d)));
  ctxWrong.forEach((d, i) => {
    const segs = d.segments || [];
    const acts = [];
    if (d.use) acts.push(btn("apply", TR("Применить к ") + segs.length + TR(" сегм."), () => applyAdvice(d), "secondary", ctxBusy));
    acts.push(btn("demote", TR("Понизить запись"), () => demoteAdvised(d), "ghost", ctxBusy));
    if (segs.length) acts.push(btn("open", TR("Открыть"), () => open(d.src, segs)));
    qs.push({ key: "ctx" + i, sev: "warn",
      title: TR("Арбитр: запись словаря не подходит здесь"),
      meta: [d.use ? TR("здесь верно: ") + d.use : "", d.why ? TRS(d.why) : ""]
        .filter(Boolean).join(" · "),
      where: d.src + " → " + d.tgt, frag: true,
      scope: segs.length + TR(" строк"), acts });
  });
  disputes.forEach((d, i) => {
    const segs = d.segments || [];
    const acts = [btn("demote", TR("Понизить запись"), () => demoteAdvised(d), "ghost", ctxBusy)];
    if (segs.length) acts.push(btn("open", TR("Открыть"), () => open(d.src, segs)));
    qs.push({ key: "disp" + i, sev: "warn",
      title: TR("Проверка спорит со словарём"),
      meta: TR("проверка предлагает: ") + ((d.suggests || []).join(", ") || TR("без замены")),
      where: d.src + " → " + d.tgt, frag: true,
      scope: segs.length + TR(" строк"), acts });
  });
  /* Что именно разошлось — со значениями, если сервер их посчитал
     (`_override_values`). «Расхождение чисел» без чисел человеку нечем
     проверить: он идёт искать их глазами по абзацу. У записей прежних
     прогонов значений нет — тогда общая фраза, а не выдуманные цифры.
     Подписи по КОДУ (`numbers`/`units`), а не по фразе сервера: тот же
     закон, что у `CLEAN_*`. */
  const VAL_WHAT = { numbers: TR("числа"), units: TR("единицы") };
  const wvals = [].concat.apply([], (h.confirmWithdrawnWhy || []).map(w => w.vals || []));
  const alarmWhy = wvals.length
    ? wvals.slice(0, 2).map(v => (VAL_WHAT[v.what] || v.what) + TR(": в книге ")
        + v.src + TR(", назад вернулось ") + v.back).join(" · ")
      + TR(" — это важнее отметки «проверено»")
    : TR("разошлись числа, единицы или отрицание — это важнее отметки; что именно нашлось, видно в самой строке");
  const shown = all ? qs : qs.slice(0, ASK_TOP);
  const stackIds = new Set();
  stack.forEach(i => (i.ids || []).forEach(x => stackIds.add(x)));
  const askRow = (q, quiet) => React.createElement("div",
    { key: q.key, className: "ask" + (quiet ? " ask-quiet" : "") },
    React.createElement("span", { className: "ask-sev " + q.sev }),
    React.createElement("div", { className: "ask-cell" },
      React.createElement("div", { className: "ask-t" }, q.title),
      q.meta && React.createElement("div", { className: "ask-m" }, q.meta)),
    React.createElement("div", { className: "ask-where" + (q.frag ? " frag" : "") },
      q.frag ? React.createElement("span", null, q.where || "") : (q.where || "")),
    React.createElement("div", { className: "ask-acts" }, q.acts),
    React.createElement("div", { className: "ask-scope" }, q.scope || ""));
  return React.createElement("div", { className: "col", style: { gap: 12 } },
    React.createElement("div", { className: "ask-head" },
      React.createElement("h2", null, TR("Вопросы к вам")),
      (qs.length + (alarm ? 1 : 0)) > 0 && React.createElement("span", { className: "ask-n" },
        qs.length + (alarm ? 1 : 0)),
      qs.length > 0 && React.createElement("span", { className: "ask-hint" },
        TR("одно решение закрывает все строки в карточке"))),
    /* Снятая отметка «проверено» — полосой НАД таблицей и с числом впереди:
       главное здесь не то, что машина сделала с отметкой, а что именно
       разошлось. Доказательство лежит в карточке сегмента. */
    alarm && React.createElement("div", { className: "ask-alarm" },
      React.createElement("div", null,
        React.createElement("div", { className: "ask-alarm-t" }, alarm.title),
        /* С самими значениями, если сервер их дал: «расхождение чисел» без
           чисел человеку нечем проверить. У записей прежних прогонов значений
           нет — тогда остаётся общая фраза, а не выдуманные цифры. */
        React.createElement("div", { className: "ask-m" }, alarmWhy)),
      React.createElement("div", { className: "ask-acts" }, alarm.acts)),
    React.createElement("div", { className: "ask-list" },
      !qs.length && !alarm && React.createElement("div", { className: "ask-empty" }, TR("Вопросов к вам нет.")),
      qs.length > 0 && React.createElement("div", { className: "ask ask-hd" },
        React.createElement("span", null),
        React.createElement("div", { className: "ask-cell" }, TR("Что не так")),
        React.createElement("div", { className: "ask-where" }, TR("Где")),
        React.createElement("div", { className: "ask-acts" }, TR("Ваш ответ")),
        React.createElement("div", { className: "ask-scope" }, TR("Сколько изменится"))),
      shown.map(q => askRow(q, false))),
    qs.length > ASK_TOP && React.createElement("div", null,
      React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setAll(v => !v) },
        all ? TR("Свернуть") : TR("Показать все") + " · " + qs.length)),
    /* Строки, у которых общего решения нет: это не вопрос, а стопка
       на просмотр. Прятать их нельзя — сегменты, пропавшие с экрана,
       выглядят благополучием, — но и спрашивать про них нечего, поэтому
       список тише и без колонки ответа. */
    stack.length > 0 && React.createElement("div", { className: "ask-stack" },
      React.createElement("div", { className: "ask-stack-h" },
        React.createElement("span", null, TR("Просмотреть глазами")),
        React.createElement("span", { className: "ask-n" }, stackIds.size + TR(" строк"))),
      React.createElement("div", { className: "ask-list" },
        stack.map(q => askRow(q, true)))),
    /* Повреждённый оригинал — единственная строка, где машина бессильна
       по построению: чинят не перевод, а книгу. */
    source && React.createElement("div", { className: "ask-stack" },
      React.createElement("div", { className: "ask-list" },
        askRow({ key: "src", sev: "bad", title: source.title,
                 meta: TR("перевод здесь не поможет — нужен исправленный файл"),
                 where: source.where, scope: source.scope, acts: source.acts }, true))));
}

/* ---------- Что проверяется в этой паре ----------
   Закон детерминированных проверок: нет правил для пары — молчим. Но молчание
   неотличимо от успеха, пока о нём не сказано. Списки считает СЕРВЕР по тем
   же таблицам, из которых проверки берут правила; здесь только показ. */
/* `quiet` — для человека: карточка есть, только когда на паре что-то МОЛЧИТ.
   «Всё работает» — не новость, а молчание без предупреждения неотличимо
   от успеха. */
function CoverageCard({ project, quiet }) {
  const [cov, setCov] = useState(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!window.API || !window.API.coverage || !project) return;
    let dead = false;
    window.API.safeCall(() => window.API.coverage(project.id))
      .then(r => { if (!dead && r && r.ok) setCov(r); });
    return () => { dead = true; };
  }, [project && project.id]);
  if (!cov) return null;
  const n = cov.silent.length;
  if (quiet && !n) return null;
  const head = n
    ? TR("На паре ") + cov.src + " → " + cov.tgt + TR(" молчат ") + n + TR(" из ") + (n + cov.works.length) + TR(" бесплатных проверок")
    : TR("На паре ") + cov.src + " → " + cov.tgt + TR(" работают все бесплатные проверки");
  const col = (title, items, why) => React.createElement("div", null,
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, title),
    React.createElement("ul", { style: { margin: 0, paddingLeft: 18, fontSize: 13 } },
      items.map(i => React.createElement("li", { key: i.key },
        i.label, why && i.why ? React.createElement("span", { className: "dim" }, " — " + TRS(i.why)) : null))));
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "row between" },
      React.createElement("div", { style: { fontWeight: 600, color: n ? "var(--c-warn)" : undefined } }, head),
      React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setOpen(o => !o) },
        open ? TR("Скрыть") : TR("Подробнее"))),
    open && React.createElement("div", { className: "grid grid-3", style: { marginTop: 12, gap: 16 } },
      col(TR("Работает"), cov.works, false),
      col(TR("Молчит"), cov.silent, true),
      col(TR("Через модель — на любой паре"), cov.model, false)));
}

// Стайл-шит документа: выборы, а не слова — человек без целевого языка выбирает
// журнал и вариант орфографии. Действующие значения и блок промпта считает
// СЕРВЕР (`/style`); проверка орфографии и аббревиатур — `/style-check`,
// бесплатно и с откатом по метке.
// Терм-лист документа (фаза 0): термины решаются ДО перевода. Список собирает
// задача `termsheet`; в промпт уходит только по тумблеру, и рядом стоит замер
// вреда — тот же счёт, каким похоронили подсказки автоимпорта.
function TermlistCard({ project, toast }) {
  const [tl, setTl] = useState(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const load = () => {
    if (!window.API || !window.API.termlist || !project) return Promise.resolve();
    return window.API.safeCall(() => window.API.termlist(project.id)).then(r => { if (r && r.ok) setTl(r); });
  };
  useEffect(() => { setTl(null); setJobId(null); load(); }, [project && project.id]);
  useEffect(() => {
    if (!jobId || !window.API || !window.API.listJobs) return;
    let dead = false;
    const t = setInterval(() => {
      window.API.safeCall(() => window.API.listJobs(project.id)).then(r => {
        if (dead || !r) return;
        const j = (r.jobs || []).find(x => x.id === jobId);
        if (j && ["done", "error", "stopped"].indexOf(j.status) !== -1) {
          setJobId(null); load();
          const c = j.counters || {};
          if (j.status === "error") toast(TR("Сбор терм-листа не удался: ") + (j.error || ""));
          else if (j.status === "stopped") toast(TR("Сбор остановлен: список не записан, вызовов оплачено ") + (c.calls || 0));
        }
      });
    }, 4000);
    return () => { dead = true; clearInterval(t); };
  }, [jobId]);
  if (!tl) return null;
  const build = () => {
    setBusy(true);
    window.API.safeCall(() => window.API.createJob(project.id, "termsheet", [], {})).then(r => {
      setBusy(false);
      if (!r || !r.ok) return;
      setJobId(r.job.id);
      toast(TR("Терм-лист собирается: ") + (r.job.total || "") + TR(" сегм."));
    });
  };
  const post = (body) => {
    setBusy(true);
    window.API.safeCall(() => window.API.setTermlist(project.id, body)).then(r => { setBusy(false); if (r && r.ok) setTl(r); });
  };
  const c = tl.counts || {};
  const m = tl.measure || {};
  const disputed = (tl.entries || []).filter(e => e.status === "disputed");
  const agreed = (tl.entries || []).filter(e => e.status === "agreed");
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "row between" },
      React.createElement("div", null,
        React.createElement("div", { style: { fontWeight: 600 } }, TR("Терм-лист документа")),
        React.createElement("div", { className: "dim", style: { fontSize: 13 } },
          tl.built
            ? TR("согласовано ") + (c.agreed || 0) + TR(", спорных ") + (c.disputed || 0) + TR(", отклонено ") + (c.rejected || 0)
              + TR(", без ответа ") + (c.pending || 0) + TR(", уже в глоссарии ") + (c.shadowed || 0)
              + (tl.strict ? " · " + TR("строгая область: в промпте просьба, не приказ") : "")
              + (tl.partial ? " · " + TR("часть порций не прошла: ") + tl.partial : "")
            : TR("Термины решаются до перевода: модель читает оригинал, предлагает стандартный перевод, корпус и сверка смысла отсеивают кальки. В глоссарий ничего не пишется."))),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        jobId ? React.createElement("span", { className: "dim" }, TR("собирается…"))
          : React.createElement(Btn, { variant: tl.built ? "ghost" : "secondary", size: "sm", disabled: busy, onClick: build },
              tl.built ? TR("Пересобрать") : TR("Собрать терм-лист")))),
    tl.built && React.createElement("div", { style: { marginTop: 10, fontSize: 13 } },
      React.createElement("label", { className: "row", style: { gap: 8, alignItems: "center" } },
        React.createElement("input", { type: "checkbox", checked: !!tl.use, disabled: busy || !agreed.length,
          onChange: (e) => post({ use: e.target.checked }) }),
        TR("Использовать в промптах перевода, ревизии и ремонта")
        + (tl.use ? " · " + TR("в промпте: ") + (tl.active || 0) : "")),
      tl.pendingHuman ? React.createElement("div", { className: "row", style: { gap: 8, alignItems: "center", marginTop: 6 } },
        React.createElement("span", { className: "dim" },
          (tl.strict ? TR("Строгая область: в промпт идут только принятые человеком. Согласовано машиной: ")
                     : TR("Согласовано машиной, без решения человека: ")) + tl.pendingHuman),
        React.createElement(Btn, { variant: "secondary", size: "sm", disabled: busy,
          onClick: () => { if (window.confirm(TR("Принять все согласованные машиной пары как решение человека?"))) post({ accept_all: true }); } },
          TR("Принять все") + " (" + tl.pendingHuman + ")")) : null,
      m.insertions ? React.createElement("div", { className: "dim", style: { marginTop: 6 } },
        TR("Замер: ") + m.insertions + TR(" вставок в ") + m.segments + TR(" сегм., забраковано termcheck ") + m.harm
        + " (" + m.per10k + TR(" на 10 тыс.; подсказки автоимпорта давали ") + m.baseline.per10k + "). "
        + TR("Меряется только вред; пользу покажут два прогона одних сегментов.")) : null,
      disputed.length ? React.createElement("div", { style: { marginTop: 8 } },
        React.createElement("div", { className: "eyebrow" }, TR("Спорные — решает человек")),
        disputed.slice(0, showAll ? 200 : 8).map(e => React.createElement("div", { key: e.src, className: "row", style: { gap: 8, alignItems: "center", marginTop: 4 } },
          React.createElement("span", null, e.src + " → " + e.tgt),
          React.createElement("span", { className: "dim" }, e.why ? " · " + e.why : ""),
          React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy, onClick: () => post({ decisions: [{ src: e.src, tgt: e.tgt, status: "agreed" }] }) }, TR("Принять")),
          React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy, onClick: () => post({ decisions: [{ src: e.src, tgt: e.tgt, status: "rejected" }] }) }, TR("Отклонить")))),
        disputed.length > 8 ? React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setShowAll(v => !v) },
          showAll ? TR("Скрыть") : TR("Показать все") + " (" + disputed.length + ")") : null) : null,
      agreed.length ? React.createElement("div", { className: "dim", style: { marginTop: 8 } },
        TR("Согласовано: ") + agreed.slice(0, 12).map(e => e.src + " → " + e.tgt).join("; ") + (agreed.length > 12 ? " …" : "")) : null));
}

// Правила документа: как переведена ЭТА книга — обращение, кавычки, числа,
// имена, заголовки, орфография языка перевода. Выводятся сами из первых
// переведённых строк (один вызов модели на прогоне, `_guide_auto`) или по
// кнопке; человек правит, выключает и дописывает. Правило про сам язык
// владелец переносит в организацию — оно действует во всех книгах на этот язык.
function GuideCard({ project, store, toast }) {
  const [g, setG] = useState(null);
  const [draft, setDraft] = useState([]);
  const [busy, setBusy] = useState(false);
  const [add, setAdd] = useState("");
  const owner = !!(store && store.can && store.can.owner);
  const take = (r) => { setG(r); setDraft((r.rules || []).map(x => ({ ...x }))); };
  useEffect(() => {
    if (!window.API || !window.API.guide || !project) return;
    let dead = false;
    setG(null); setAdd("");
    window.API.safeCall(() => window.API.guide(project.id)).then(r => { if (!dead && r && r.ok) take(r); });
    return () => { dead = true; };
  }, [project && project.id]);
  if (!g) return null;
  const same = (a, b) => a.text === b.text && a.kind === b.kind && !!a.on === !!b.on;
  const dirty = draft.length !== (g.rules || []).length || draft.some((r, i) => !same(r, g.rules[i]));
  /* Не safeCall: тот глотает ошибку молча, а здесь отказ — это ответ
     человеку (идёт прогон — 409, кончился лимит — 402, модель не ответила — 502). */
  const run = (fn, msg) => {
    setBusy(true);
    Promise.resolve().then(fn).then(r => {
      setBusy(false);
      if (!r || !r.ok) return;
      take(r);
      if (msg) toast(msg(r));
    }, e => { setBusy(false); toast(TR("Не получилось: ") + ((e && e.message) || "")); });
  };
  const save = (body) => run(() => window.API.setGuide(project.id, body));
  const build = () => {
    if (!window.confirm(TR("Собрать правила по переведённым строкам? Один платный вызов модели. Правила, которые вы правили или добавили, останутся."))) return;
    run(() => window.API.buildGuide(project.id), r => TR("Правил добавлено: ") + (r.added || 0));
  };
  const setRule = (i, patch) => setDraft(d => d.map((r, j) => j === i ? { ...r, ...patch } : r));
  const addRule = () => {
    const t = add.trim();
    if (!t) return;
    setDraft(d => d.concat([{ text: t, kind: "doc", on: true }]));
    setAdd("");
  };
  const orgLang = g.orgLang || [];
  const saveLang = (rules) => {
    setBusy(true);
    Promise.resolve().then(() => window.API.setLangRules(g.tgt, rules)).then(r => {
      setBusy(false);
      if (r && r.ok) { setG(s => ({ ...s, orgLang: r.rules })); toast(TR("Правила языка организации сохранены")); }
    }, e => { setBusy(false); toast(TR("Не получилось: ") + ((e && e.message) || "")); });
  };
  const head = g.built
    ? (g.builtBy === "auto" ? TR("Собраны сами по первым ") : TR("Собраны по кнопке по ")) + g.sample + TR(" строкам")
      + " · " + TR("в промпте: ") + g.active + (g.off ? " · " + TR("выключены") : "")
    : (g.rules || []).length
      ? TR("Правила записаны вручную") + " · " + TR("в промпте: ") + g.active
      : TR("Соберутся сами, когда будет переведено ") + g.min + TR(" строк (сейчас ") + g.ready + TR("). Или соберите сейчас.");
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "row between", style: { gap: 8, flexWrap: "wrap" } },
      React.createElement("div", { style: { minWidth: 0 } },
        React.createElement("div", { style: { fontWeight: 600 } }, TR("Правила документа")),
        React.createElement("div", { className: "dim", style: { fontSize: 13 } },
          TR("Как переведена эта книга: обращение к читателю, кавычки, числа, имена, заголовки, орфография. Только форма — термины решает словарь."))),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Btn, { variant: g.built ? "ghost" : "secondary", size: "sm",
          disabled: busy || dirty || g.ready < g.minPairs, onClick: build },
          g.built ? TR("Пересобрать") : TR("Собрать сейчас")),
        (g.rules || []).length ? React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy || dirty,
          onClick: () => save({ off: !g.off }) }, g.off ? TR("Включить") : TR("Отключить")) : null)),
    React.createElement("div", { className: "dim", style: { fontSize: 13, marginTop: 6 } }, head),
    draft.length ? React.createElement("div", { style: { marginTop: 10, display: "flex", flexDirection: "column", gap: 6 } },
      draft.map((r, i) => React.createElement("div", { key: r.id || ("n" + i), className: "row", style: { gap: 8, alignItems: "center", flexWrap: "wrap" } },
        React.createElement("input", { type: "checkbox", checked: !!r.on, disabled: busy, title: TR("В промпте"),
          onChange: (e) => setRule(i, { on: e.target.checked }) }),
        React.createElement(Input, { value: r.text, disabled: busy, style: { flex: "1 1 260px", minWidth: 0 },
          onChange: (e) => setRule(i, { text: e.target.value }) }),
        React.createElement(Select, { value: r.kind || "doc", disabled: busy, style: { width: "auto" },
          onChange: (e) => setRule(i, { kind: e.target.value }) },
          React.createElement("option", { value: "doc" }, TR("книга")),
          React.createElement("option", { value: "lang" }, TR("язык"))),
        owner && r.kind === "lang" && r.text.trim() && orgLang.indexOf(r.text.trim()) === -1
          ? React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy,
              title: TR("Правило будет действовать во всех книгах организации на этот язык"),
              onClick: () => saveLang(orgLang.concat([r.text.trim()])) }, TR("Во все книги")) : null,
        React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy, title: TR("Удалить"),
          onClick: () => setDraft(d => d.filter((_, j) => j !== i)) }, "×")))) : null,
    React.createElement("div", { className: "row", style: { gap: 8, marginTop: 10, flexWrap: "wrap" } },
      React.createElement(Input, { value: add, disabled: busy, placeholder: TR("Своё правило, например: к читателю — на «вы»"),
        style: { flex: "1 1 260px", minWidth: 0 },
        onChange: (e) => setAdd(e.target.value), onKeyDown: (e) => { if (e.key === "Enter") addRule(); } }),
      React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy || !add.trim(), onClick: addRule }, TR("Добавить")),
      dirty ? React.createElement(Btn, { variant: "primary", size: "sm", disabled: busy,
        onClick: () => save({ rules: draft }) }, TR("Сохранить правила")) : null,
      dirty ? React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy,
        onClick: () => setDraft((g.rules || []).map(x => ({ ...x }))) }, TR("Отменить")) : null),
    orgLang.length ? React.createElement("div", { style: { marginTop: 12, fontSize: 13 } },
      React.createElement("div", { className: "eyebrow" }, TR("Правила языка организации — во всех книгах на ") + g.tgt),
      orgLang.map((t, i) => React.createElement("div", { key: i, className: "row", style: { gap: 8, alignItems: "center", marginTop: 4 } },
        React.createElement("span", { style: { flex: 1, minWidth: 0 } }, t),
        owner ? React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy, title: TR("Удалить"),
          onClick: () => saveLang(orgLang.filter((_, j) => j !== i)) }, "×") : null))) : null);
}

function StyleCard({ project, toast }) {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rep, setRep] = useState(null);
  const [stamp, setStamp] = useState(null);
  useEffect(() => {
    if (!window.API || !window.API.style || !project) return;
    let dead = false;
    setRep(null); setStamp(null);
    window.API.safeCall(() => window.API.style(project.id))
      .then(r => { if (!dead && r && r.ok) setSt(r); });
    return () => { dead = true; };
  }, [project && project.id]);
  if (!st) return null;
  const OPTS = {
    preset: [["", TR("не задан")], ["ama", "AMA"], ["vancouver", "Vancouver"], ["apa", "APA"], ["nature", "Nature"]],
    spelling: [["", TR("по умолчанию")], ["US", TR("американская")], ["UK", TR("британская")]],
    register: [["", TR("по умолчанию")], ["academic", TR("научная статья")], ["clinical", TR("клиническая документация")],
               ["textbook", TR("учебник")], ["plain", TR("простой язык")]],
    abbreviations: [["", TR("по умолчанию")], ["expand_first", TR("расшифровка при первом упоминании")], ["as_source", TR("как в оригинале")]],
    quotes: [["", TR("по умолчанию")], ["double", "“ ”"], ["single", "‘ ’"], ["guillemets", "« »"]],
  };
  const LABEL = { preset: TR("Журнал"), spelling: TR("Орфография"), register: TR("Регистр"),
                  abbreviations: TR("Аббревиатуры"), quotes: TR("Кавычки") };
  const save = (body) => {
    setBusy(true);
    window.API.safeCall(() => window.API.setStyle(project.id, body)).then(r => {
      setBusy(false);
      if (!r || !r.ok) return;
      setSt(s => ({ ...s, ...r }));
      setRep(null);
      if (r.reviewsStale) toast(TR("Стайл-шит изменён: ревизия перечитает ") + r.reviewsStale + TR(" сегм. при следующем прогоне"));
    });
  };
  const check = (apply) => {
    if (apply && rep && rep.staleChecks
        && !window.confirm(TR("Проверки устареют у ") + rep.staleChecks + TR(" сегм.: ближайший прогон купит их заново. Исправить орфографию?"))) return;
    setBusy(true);
    window.API.safeCall(() => window.API.styleCheck(project.id, { dry_run: !apply })).then(r => {
      setBusy(false);
      if (!r || !r.ok) return;
      setRep(r);
      if (apply) { setStamp(r.stamp); toast(TR("Орфография исправлена: ") + r.applied + TR(" сегм.")); }
    });
  };
  const undo = () => window.API.safeCall(() => window.API.styleUndo(project.id, stamp)).then(r => {
    if (r && r.ok) { setStamp(null); setRep(null); toast(TR("Откат выполнен: ") + (r.restored || 0) + TR(" сегм.")); }
  });
  const eff = st.effective || {};
  const proj = st.project || {};
  if (!st.enabled) {
    return React.createElement("div", { className: "card card-pad" },
      React.createElement("div", { className: "row between" },
        React.createElement("div", null,
          React.createElement("div", { style: { fontWeight: 600 } }, TR("Стайл-шит документа не включён")),
          React.createElement("div", { className: "dim", style: { fontSize: 13 } },
            TR("Орфография, регистр, аббревиатуры и кавычки — одним правилом на весь документ, в промпты перевода, ревизии и ремонта."))),
        React.createElement(Btn, { variant: "secondary", size: "sm", disabled: busy, onClick: () => save({ fields: {} }) },
          TR("Включить"))));
  }
  const field = (k) => React.createElement("label", { key: k, style: { display: "flex", flexDirection: "column", gap: 4, fontSize: 12 } },
    React.createElement("span", { className: "dim" }, LABEL[k] + (proj[k] ? "" : (eff[k] ? " · " + TR("действует: ") + eff[k] : ""))),
    React.createElement(Select, { value: proj[k] || "", disabled: busy || (k === "spelling" && !st.spellingApplies),
                                  onChange: (e) => save({ fields: { [k]: e.target.value } }) },
      OPTS[k].map(([v, l]) => React.createElement("option", { key: v, value: v }, l))));
  const abbrs = (rep && rep.abbreviations) || [];
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "row between" },
      React.createElement("div", { style: { fontWeight: 600 } }, TR("Стайл-шит документа")),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Btn, { variant: "secondary", size: "sm", disabled: busy, onClick: () => check(false) }, TR("Проверить стиль")),
        React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy, onClick: () => save({ enable: false }) }, TR("Отключить")))),
    React.createElement("div", { className: "grid grid-3", style: { marginTop: 10, gap: 12 } },
      ["preset", "spelling", "register", "abbreviations", "quotes"].map(field)),
    rep && React.createElement("div", { style: { marginTop: 12, fontSize: 13 } },
      React.createElement("div", null,
        TR("Орфография") + (rep.spelling ? " (" + rep.spelling + "): " : ": ")
        + (rep.spelling ? rep.spellingChanges + TR(" замен в ") + rep.spellingSegments + TR(" сегм.") : TR("вариант не задан")),
        rep.skippedConfirmed && rep.skippedConfirmed.length
          ? React.createElement("span", { className: "dim" }, " · " + TR("заверено человеком, не тронуто: ") + rep.skippedConfirmed.length) : null,
        rep.dryRun && rep.staleChecks
          ? React.createElement("span", { className: "dim" }, " · " + TR("проверки устареют у ") + rep.staleChecks + TR(" сегм.")) : null),
      (rep.samples || []).slice(0, 3).map(sm => React.createElement("div", { key: sm.id, className: "dim" },
        "#" + sm.id + ": " + sm.changes.map(c => c[0] + " → " + c[1]).join(", "))),
      React.createElement("div", { style: { marginTop: 6 } },
        TR("Аббревиатуры без расшифровки при первом упоминании: ") + rep.abbreviationsTotal,
        abbrs.length ? React.createElement("span", { className: "dim" },
          " · " + abbrs.slice(0, 8).map(a => a.abbr + " (#" + a.id + ")").join(", ")) : null),
      React.createElement("div", { className: "row", style: { gap: 8, marginTop: 8 } },
        rep.dryRun && rep.ids && rep.ids.length
          ? React.createElement(Btn, { variant: "primary", size: "sm", disabled: busy, onClick: () => check(true) },
              TR("Исправить орфографию") + " (" + rep.ids.length + ")") : null,
        stamp ? React.createElement(Btn, { variant: "ghost", size: "sm", onClick: undo }, TR("Вернуть прежний")) : null)));
}

/* «Проверка» — экран для того, кому нужен перевод под ключ. Человек видит
   ровно два блока: сколько готово (с одной кнопкой) и вопросы к нему.
   Устройство прогона — корзины карточками, терм-лист, полосы back-check,
   соответствие глоссарию, termcheck, ремонт и кнопка арбитра — эксперту
   (store.can.super) под «Подробностями»: «пропавшая кнопка неотличима от
   потерянной функции», поэтому команды по вопросам живут в самих вопросах.
   Старый сервер без turnkey — подробный итог всем, как и раньше. */
function TabAnalysis({ store, toast }) {
  const project = store.activeProject;
  const [summary, setSummary] = useState(null);
  const [sumNonce, setSumNonce] = useState(0);
  const [details, setDetails] = useState(false);
  /* Стиль книги — одно решение на весь документ: свёрнут, но доступен всем
     (под ролью он отнял бы настройку у владельца). */
  const [styleOpen, setStyleOpen] = useState(false);
  useEffect(() => {
    if (!window.API || !window.API.analysis || !project) return;
    let dead = false;
    window.API.safeCall(() => window.API.analysis(project.id))
      .then(r => { if (!dead && r && r.ok) setSummary(r); });
    return () => { dead = true; };
  }, [project && project.id, sumNonce]);
  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));
  /* Экспертный вид — выбор суперпользователя (`store.expert`), по умолчанию
     выключен: простой экран видят все, включая владельца сервиса. */
  const expert = !!store.expert;
  const canExpert = !!(store.can && store.can.super);
  const reload = () => setSumNonce(n => n + 1);
  const onDrill = (title, segList) => {
    const ids = (segList || []).map(s => s.id);
    if (!ids.length) return;
    store.setSegmentFilter(ids);
    store.go("editor");
  };
  const T = (title, body, code) => React.createElement(InfoTip, { title, body, code });
  const tk = summary && summary.turnkey;
  // Старый сервер без turnkey: корзин нет, честный ответ — подробный итог,
  // а не посчитанные браузером числа (второй расчёт запрещён).
  const oldServer = !!(summary && !tk);
  const segs = project.segments;
  const hs = (summary && summary.human) || {};
  const todo = (summary && summary.todo) || {};
  /* Что машина сделала или сделает сама — числом, а не молча: снятое без
     следа неотличимо от потерянного. */
  const did = [
    tk && (tk.reviewVouched || []).length
      ? [TR("ревизия ручается за "), tk.reviewVouched.length, TR(" строк")] : null,
    hs.termsWaitingTotal
      ? [TR("терминов ждут данных: "), hs.termsWaitingTotal, TR(" — дорешаются после прогонов")] : null,
    (todo.consistency || []).length
      ? [TR("разнобой переводов: "), todo.consistency.length, TR(" пар — выровняет прогон")] : null,
  ].filter(Boolean);
  return React.createElement("div", { className: "page page-stack" + (expert ? " page-wide" : "") },
    React.createElement("div", { className: "row between page-head", style: { alignItems: "flex-end" } },
      React.createElement("div", null,
        React.createElement("h1", null, TR("Проверка")),
        React.createElement("p", { className: "lead", style: { marginBottom: 0 } },
          TR("Что готово и о чём я спрошу вас."))),
      React.createElement(Btn, { variant: "secondary", icon: "download",
        onClick: () => store.go("export") }, TR("Экспорт перевода"))),
    !summary && React.createElement("div", { className: "dim", style: { fontSize: 13 } }, TR("Считаем итог…")),
    /* Молчание проверок на паре человеку показываем, только если оно ЕСТЬ:
       «всё работает» — не новость, а «молчат три проверки» — предупреждение. */
    React.createElement(CoverageCard, { project, quiet: !expert }),
    tk && React.createElement(TurnkeySummary, { key: project.id, summary, store, toast,
      onReload: reload, expert }),
    tk && React.createElement(CheckQuestions, { summary, store, toast, onReload: reload }),
    /* Журнал решений — под вопросами: сначала «что делать», потом «что уже
       сделали и чем это вернуть». Компонент сам молчит, когда решений нет. */
    React.createElement(CheckLog, { project, store, toast, onReload: reload }),
    oldServer && React.createElement("div", { className: "dim", style: { fontSize: 13 } },
      TR("Сервер прежней версии — корзин «под ключ» нет, ниже подробный итог.")),
    summary && React.createElement("div", { className: "page-foot" },
      did.length > 0 && React.createElement("span", null, TR("Сама после прогона:")),
      did.map((d, i) => React.createElement("span", { key: i }, d[0], React.createElement("b", null, d[1]), d[2])),
      React.createElement("span", { className: "spacer" }),
      React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setStyleOpen(v => !v) },
        styleOpen ? TR("Скрыть настройки книги") : TR("Настройки книги")),
      expert && tk && React.createElement(Btn, { variant: "ghost", size: "sm",
        onClick: () => setDetails(d => !d) },
        details ? TR("▴ Скрыть подробности") : TR("▾ Подробности и ручные команды")),
      canExpert && store.setExpertView && React.createElement(Btn, { variant: "ghost", size: "sm",
        onClick: () => store.setExpertView(!store.expertView) },
        store.expertView ? TR("Простой вид") : TR("Вид эксперта"))),
    /* Настройки книги — стиль и терм-лист: решения на весь документ, до
       перевода. Свёрнуты, но доступны всем — под ролью они отняли бы
       настройку у владельца. */
    styleOpen && React.createElement(GuideCard, { project, store, toast }),
    styleOpen && React.createElement(StyleCard, { project, toast }),
    styleOpen && React.createElement(TermlistCard, { project, toast }),
    summary && (oldServer || (expert && details)) && React.createElement(React.Fragment, null,
      expert && React.createElement(CoverageCard, { project }),
      React.createElement(WorkSummary, { summary, store, toast, onReload: reload }),
      React.createElement(BackcheckBands, { segments: segs, project, onDrill, T }),
      React.createElement(GlossaryImpact, { project, store, toast, onDrill, T }),
      React.createElement(TermcheckSummary, { segments: segs, onDrill, T }),
      React.createElement(RepairSummary, { segments: segs, onDrill, T })));
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
  const scored = translated.filter(s => s.backcheck && s.backcheck.score != null);
  // Устаревшая оценка описывает текст, которого больше нет: человек правил
  // перевод после проверки. Считать её действующей — значит вечно держать
  // исправленный и подтверждённый сегмент в полосе «Совпадения почти нет»
  // и звать разбираться с работой, которая уже сделана. Признак `stale`
  // считает СЕРВЕР (_segment_for_client): sha1 браузеру не пересчитать.
  // Так же устроена соседняя карточка «Проверка терминологии» — и по той же
  // причине. Своей строкой ниже: пропавшее с экрана выглядит благополучнее,
  // чем есть, а такой сегмент ждёт очередного прогона.
  const staleBc = scored.filter(s => s.backcheck.stale);
  const checked = scored.filter(s => !s.backcheck.stale);
  const termLost = checked.filter(s => (s.backcheck.terms_lost || []).length > 0);
  // Заверенные человеком со свежей оценкой. Балл их не отменяет: он мера
  // обратного перевода, а не приговор — человек прочитал текст и подтвердил,
  // и корзины «под ключ» считают такой сегмент готовым (см. /analysis:
  // machine_set -= confirmed_ids). Без этой строки низкий балл на заверённом
  // сегменте выглядит невыполненной работой, и её идут делать заново.
  const bcConfirmed = checked.filter(s => s.status === "confirmed");
  const maxCount = Math.max(1, ...bands.map(b =>
    checked.filter(s => s.backcheck.score >= b.min && s.backcheck.score <= b.max).length));

  return React.createElement("div", { className: "section" },
    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 14 } },
      React.createElement("div", { className: "row between", style: { alignItems: "flex-end", flexWrap: "wrap", gap: 10 } },
        React.createElement("div", null,
          React.createElement("h3", { style: { fontSize: 15, fontWeight: 600 } }, TR("Соответствие обратного перевода"),
            T(TR("Соответствие обратного перевода"),
              TR("Перевод переводится обратно на язык оригинала и сравнивается с исходным текстом: числа, единицы, отрицания, лево-право, сохранность терминов. Процент показывает, сколько смысла пережило круг. Запускается на вкладке «Редактор», карточка Back-check."))),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } },
            TR("Проверено ") + checked.length + TR(" из ") + translated.length + TR(" переведённых сегментов"))),
        checked.length > 0 && React.createElement("div", { className: "dim", style: { fontSize: 13 } },
          TR("Средний балл: ") +
          Math.round(checked.reduce((a, s) => a + s.backcheck.score, 0) / checked.length) + "%")
      ),

      checked.length === 0
        ? React.createElement(EmptyState, { icon: "repeat", title: TR("Back-check ещё не запускался"),
            sub: TR("Запустите его в Редакторе — карточка Back-check в блоке пакетных операций.") })
        : React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            bands.map(b => {
              const list = checked.filter(s => s.backcheck.score >= b.min && s.backcheck.score <= b.max);
              const pct = Math.round(list.length / maxCount * 100);
              return React.createElement("div", {
                key: b.key, className: "row", style: { gap: 10, cursor: list.length ? "pointer" : "default", opacity: list.length ? 1 : 0.45, padding: "3px 0" },
                onClick: () => list.length && onDrill(b.label, list),
                title: list.length ? TR("Открыть эти сегменты в редакторе") : TR("Нет сегментов в этой полосе") },
                React.createElement("span", { className: "mono", style: { width: 72, fontSize: 13, fontWeight: 600, color: window.bcBandColor(b.color) } }, b.label),
                React.createElement("span", { className: "dim", style: { flex: "1 1 150px", maxWidth: 190, minWidth: 0, fontSize: 12.5 } }, b.note),
                React.createElement("div", { style: { flex: "2 1 120px", height: 10, background: "var(--bg-sunken)", borderRadius: 5, overflow: "hidden" } },
                  React.createElement("div", { style: { width: pct + "%", height: "100%", background: window.bcBandColor(b.color) } })),
                React.createElement("b", { className: "tnum", style: { width: 56, textAlign: "right", fontSize: 13 } }, list.length)
              );
            })
          ),

      staleBc.length > 0 && React.createElement("div", {
        className: "row between", style: { borderTop: "1px solid var(--border)", paddingTop: 10, cursor: "pointer" },
        onClick: () => onDrill(TR("Оценка устарела"), staleBc),
        title: TR("Открыть эти сегменты в редакторе") },
        React.createElement("div", { style: { minWidth: 0 } },
          React.createElement("span", { style: { fontSize: 13, fontWeight: 600 } }, TR("Оценка устарела")),
          React.createElement("p", { className: "muted", style: { marginTop: 2, fontSize: 12.5 } },
            TR("перевод правили после проверки — прежний балл говорит о тексте, которого больше нет"))),
        React.createElement("b", { className: "tnum", style: { fontSize: 13 } }, staleBc.length)),

      React.createElement("div", {
        className: "row between", style: { borderTop: "1px solid var(--border)", paddingTop: 10, flexWrap: "wrap", gap: 10 } },
        React.createElement("div", { style: { minWidth: 0 } },
          React.createElement("div", { className: "row", style: { gap: 6 } },
            React.createElement("span", { style: { fontSize: 13, fontWeight: 600 } }, TR("Оценки по прежним правилам")),
            T(TR("Пересчёт оценок back-check"),
              TR("Правила подсчёта меняются, а хеш перевода сторожит только текст — запись, посчитанная по-старому, считается свежей вечно и сама не пересчитается.\n\nПересчёт бесплатный: обратный перевод, оригинал и вердикт судьи лежат в самой записи, ни одного вызова модели он не делает.\n\nСперва разбор — он ничего не меняет и показывает числа. Прежние записи уходят копией в data/backups и возвращаются откатом."))),
          React.createElement("p", { className: "muted", style: { marginTop: 4, fontSize: 13 } },
            rescBusy ? TR("Считаем…")
              : !resc ? TR("Нажмите «Разобрать», чтобы узнать, сколько оценок посчитано прежними правилами")
              : !resc.rescored ? TR("Все оценки посчитаны нынешними правилами")
              : (resc.dry_run ? TR("Посчитано прежними правилами: ") : TR("Пересчитано: ")) + resc.rescored
                + TR("; балл ") + (resc.dry_run ? TR("изменится") : TR("изменился")) + TR(" у ") + resc.changed
                + TR("; к судье ") + (resc.dry_run ? TR("вернётся ") : TR("вернулось ")) + resc.freed_judge
                + TR("; машинно-чистых было ") + resc.machine_clean.before + TR(", стало ") + resc.machine_clean.after)),
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat", disabled: rescBusy,
            onClick: () => rescore(false) }, TR("Разобрать")),
          resc && resc.dry_run && resc.rescored > 0 && React.createElement(Btn, {
            variant: "primary", size: "sm", disabled: rescBusy, onClick: () => rescore(true) },
            TR("Пересчитать ") + resc.rescored))),

      bcConfirmed.length > 0 && React.createElement("div", {
        className: "row between", style: { borderTop: "1px solid var(--border)", paddingTop: 10, cursor: "pointer" },
        onClick: () => onDrill(TR("Заверено человеком"), bcConfirmed),
        title: TR("Открыть эти сегменты в редакторе") },
        React.createElement("div", { style: { minWidth: 0 } },
          React.createElement("span", { style: { fontSize: 13, fontWeight: 600, color: "var(--c-success)" } },
            TR("Из них заверено человеком")),
          React.createElement("p", { className: "muted", style: { marginTop: 2, fontSize: 12.5 } },
            TR("балл этого не отменяет: на экране «Анализ» такой сегмент считается готовым"))),
        React.createElement("b", { className: "tnum", style: { fontSize: 13 } }, bcConfirmed.length)),

      termLost.length > 0 && React.createElement("div", {
        className: "row between", style: { borderTop: "1px solid var(--border)", paddingTop: 10, cursor: "pointer" },
        onClick: () => onDrill(TR("Потеря термина"), termLost),
        title: TR("Открыть эти сегменты в редакторе") },
        React.createElement("span", { style: { fontSize: 13, fontWeight: 600, color: "var(--c-error)" } },
          TR("Из них с потерей термина")),
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
    title: clickable ? TR("Открыть эти сегменты в редакторе") : TR("Нет таких сегментов") },
    React.createElement("div", { className: "row", style: { gap: 8, minWidth: 0 } },
      React.createElement("span", { style: { fontSize: 13, fontWeight: bold ? 600 : 500, color: color || "var(--text)" } }, label),
      note && React.createElement("span", { className: "dim", style: { fontSize: 12 } }, note)),
    React.createElement("b", { className: "tnum", style: { fontSize: 13, color: color || "var(--text)" } }, count));
}

/* ============================================================
   Соответствие одобренным терминам глоссария
   ============================================================ */
// Одобрение термина не переписывает готовые переводы. Этот блок показывает,
// где они разошлись с глоссарием, и открывает такие сегменты в редакторе —
// сам переперевод запускается там, секцией «Соответствие глоссарию»
// в карточке «Одобрить и применить».
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
      toast && toast.error(TR("Не вышло разобрать начертание"), (dry && dry.error) || TR("попробуйте ещё раз"));
      return;
    }
    if (!dry.segments) {
      setFixing(false);
      toast && toast.info(TR("Начертание терминов"), TR("и так по оригиналу — менять нечего"));
      return;
    }
    const sample = (dry.samples || []).slice(0, 5)
      .map(x => "  #" + x.id + ": " + (x.fixed || []).map(f => f.was + " → " + f.now).join(", "))
      .join("\n");
    const skipped = (dry.skippedConfirmed || []).length;
    const ok = window.confirm(
      TR("Привести начертание терминов к оригиналу: ") + dry.segments + TR(" сегм.\n")
      + TR("Меняются только заглавные и строчные — слова и порядок те же.\n\n")
      + sample + (dry.segments > 5 ? "\n  …" : "")
      + (skipped ? TR("\n\nЗаверенных человеком не трогаем: ") + skipped : ""));
    if (!ok) { setFixing(false); return; }
    const res = await window.API.safeCall(() => window.API.termCase(project.id, { apply: true }));
    setFixing(false);
    if (!res || !res.ok) {
      toast && toast.error(TR("Правка не выполнена"), (res && res.error) || TR("попробуйте ещё раз"));
      return;
    }
    /* Подтягиваем ТОЛЬКО правленые сегменты: проект на 2670 строк весит
       5 МБ, и тянуть его целиком ради десятка изменившихся — трафик впустую. */
    if ((res.ids || []).length && window.API.fetchSegments && store) {
      const got = await window.API.safeCall(() => window.API.fetchSegments(project.id, res.ids));
      store.mergeServerSegments(project.id, got && got.segments);
    }
    toast && toast.success(TR("Начертание приведено к оригиналу"),
                           res.segments + TR(" сегм. — без единого вызова модели"));
    load();
  };

  return React.createElement("div", { className: "section" },
    React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
      React.createElement("div", { className: "row between", style: { alignItems: "flex-end", flexWrap: "wrap", gap: 10 } },
        React.createElement("div", null,
          React.createElement("h3", { style: { fontSize: 15, fontWeight: 600 } }, TR("Соответствие глоссарию"),
            T(TR("Соответствие одобренным терминам"),
              TR("Сегменты, где термин есть в оригинале, а утверждённого перевода в готовом тексте нет.\n\nОдобрение термина влияет только на будущие переводы — уже сделанные сами не меняются, поэтому после правок глоссария этот список и появляется.\n\nСчитается только по проверенным записям: автоимпорт модель вправе игнорировать.\n\nПереперевести пакетом можно в Редакторе — секция «Соответствие глоссарию» в карточке «Одобрить и применить»."))),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } },
            busy ? TR("Считаем…") : !data ? "—"
              : data.segments.length ? TR("Расходятся с глоссарием: ") + data.segments.length + TR(" сегм. по ") + data.terms.length + TR(" терминам")
              : TR("Все переводы соответствуют одобренным терминам"))),
        React.createElement("div", { className: "row", style: { gap: 8 } },
          data && (data.caseSegments || []).length > 0 && React.createElement(Btn, {
            variant: "primary", size: "sm", icon: "edit", disabled: fixing || busy, onClick: fixCase },
            fixing ? TR("Правим…") : TR("Привести начертание")),
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "repeat", disabled: busy, onClick: load }, TR("Пересчитать")))),

      /* Отдельной строкой, а не вперемешку с расхождениями выше: там термина
         в переводе НЕТ вовсе и нужен платный переперевод, здесь он есть, но
         не в том начертании — и чинится бесплатно, одной кнопкой. */
      data && React.createElement(StatRow, {
        label: TR("Начертание не по оригиналу"),
        note: (data.caseSegments || []).length ? TR("чинится без вызовов модели") : TR("всё по оригиналу"),
        count: (data.caseSegments || []).length,
        color: (data.caseSegments || []).length ? "var(--c-warning)" : undefined,
        onDrill: () => onDrill(TR("Начертание терминов не по оригиналу"), pick(data.caseSegments)) }),

      data && data.terms.length > 0 && React.createElement("div", { style: { display: "flex", flexDirection: "column" } },
        React.createElement(StatRow, { label: TR("Всего расхождений"), bold: true, count: data.segments.length,
          color: "var(--c-warning)", onDrill: () => onDrill(TR("Расходятся с глоссарием"), pick(data.segments)) }),
        React.createElement(StatRow, { label: TR("— не подтверждено"), note: TR("можно переперевести сразу"),
          count: data.pending.length, onDrill: () => onDrill(TR("Расходятся с глоссарием (не подтверждено)"), pick(data.pending)) }),
        React.createElement(StatRow, { label: TR("— подтверждено"), note: TR("перезапись только по явной команде"),
          count: data.confirmed.length, color: "var(--c-error)",
          onDrill: () => onDrill(TR("Расходятся с глоссарием (подтверждено)"), pick(data.confirmed)) }),
        /* Куда нажимать. Сама кнопка живёт в СОСЕДНЕЙ карточке «Одобрение
           терминов» (одна задача одобряет термины и тут же чинит ими текст),
           и человек искал её здесь — в карточке, названной по задаче.
           Дублировать запуск нельзя: под двумя кнопками встали бы два состава.
           Поэтому здесь — указание, а не вторая кнопка. */
        data.pending.length > 0 && React.createElement("div",
          { className: "dim", style: { fontSize: 12, lineHeight: 1.5, paddingTop: 8 } },
          TR("Починить их: вкладка «Редактор» → карточка «Одобрение терминов» → ")
          + TR("кнопка «Применить к ") + data.pending.length + TR(" сегм.». ")
          + TR("Правка записи готовый текст сама не меняет — это отдельная команда."))),

      data && data.terms.length > 0 && React.createElement("div", { style: { borderTop: "1px solid var(--border)", paddingTop: 10 } },
        React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600, marginBottom: 6 } }, TR("По терминам")),
        data.terms.slice(0, 10).map((t, i) => React.createElement("div", {
          key: i, className: "row between", style: { padding: "3px 0", fontSize: 13, cursor: "pointer" },
          onClick: () => onDrill(TR("Термин: ") + t.src, pick(t.segments)),
          title: TR("Открыть сегменты с этим термином") },
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
          React.createElement("h3", { style: { fontSize: 15, fontWeight: 600 } }, TR("Проверка терминологии"),
            T(TR("Проверка терминологии"),
              TR("Модель смотрит только на перевод и отвечает, нормальный ли это термин целевого языка: кальки, транслитерации, подмены понятия, склеенные обрывки.\n\nЭто не back-check: тот спрашивает, пережил ли смысл обратный перевод, и на кальке всегда отвечает «да». Запускается в Редакторе, карточка «Проверка терминологии»."))),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } },
            TR("Проверено ") + checked.length + TR(" из ") + translated.length + TR(" переведённых сегментов"))),
        withFindings.length > 0 && React.createElement("div", { className: "dim", style: { fontSize: 13 } },
          TR("Замечания в ") + Math.round(withFindings.length / Math.max(1, fresh.length) * 100) + TR("% проверенного"))),

      checked.length === 0
        ? React.createElement(EmptyState, { icon: "book", title: TR("Проверка терминологии ещё не запускалась"),
            sub: TR("Запустите её в Редакторе — карточка «Проверка терминологии» в блоке пакетных прогонов.") })
        : React.createElement("div", { style: { display: "flex", flexDirection: "column" } },
            React.createElement(StatRow, { label: TR("С замечаниями"), note: TR("нужна правка или решение"), bold: true,
              count: withFindings.length, color: "var(--c-warning)",
              onDrill: () => onDrill(TR("Терминология: есть замечания"), withFindings) }),
            React.createElement(StatRow, { label: TR("— критично"), note: TR("другое понятие или нечитаемый фрагмент"),
              count: bySev("critical").length, color: "var(--c-error)",
              onDrill: () => onDrill(TR("Терминология: критичные замечания"), bySev("critical")) }),
            React.createElement(StatRow, { label: TR("— серьёзно"), note: TR("не термин целевого языка"),
              count: bySev("major").length, color: "var(--c-warning)",
              onDrill: () => onDrill(TR("Терминология: серьёзные замечания"), bySev("major")) }),
            React.createElement(StatRow, { label: TR("Без замечаний"), count: clean.length, color: "var(--c-success)",
              onDrill: () => onDrill(TR("Терминология: без замечаний"), clean) }),
            React.createElement(StatRow, { label: TR("Нечего проверять"), note: TR("числа, обозначения — без вызова модели"),
              count: skipped.length, onDrill: () => onDrill(TR("Терминология: нечего проверять"), skipped) }),
            React.createElement(StatRow, { label: TR("Проверка устарела"), note: TR("перевод меняли после проверки"),
              count: stale.length, onDrill: () => onDrill(TR("Терминология: устаревшие проверки"), stale) }),
            React.createElement(StatRow, { label: TR("Ещё не проверялись"), count: translated.length - checked.length,
              onDrill: () => onDrill(TR("Терминология: не проверялись"), translated.filter(s => !s.termcheck)) })),

      topTerms.length > 0 && React.createElement("div", { style: { borderTop: "1px solid var(--border)", paddingTop: 10 } },
        React.createElement("div", { className: "row", style: { fontSize: 12.5, fontWeight: 600, marginBottom: 6 } },
          TR("Чаще всего повторяется"),
          T(TR("Повторяющиеся замечания"),
            TR("Один и тот же неверный термин обычно тянется по всему документу. Выгоднее одобрить правильный вариант в «Глоссарий → Кандидаты» и перевести затронутые сегменты заново, чем чинить каждый по отдельности."))),
        topTerms.map((t, i) => React.createElement("div", {
          key: i, className: "row between",
          style: { padding: "3px 0", cursor: "pointer", fontSize: 13 },
          onClick: () => onDrill(TR("Термин: ") + t.term, t.segs),
          title: TR("Открыть сегменты с этим термином") },
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
  /* БЕЗ TR(): это не надписи, а КОДЫ ПРИЧИН, которые сравниваются
     с `backcheck.reasons` — русским текстом, пришедшим с сервера. Оберни их
     переводом, и в узбекском интерфейсе `indexOf` перестанет находить
     совпадения: кнопка «Починить» погаснет на сегментах, которые чинить
     МОЖНО, и понять почему будет неоткуда. Тот же закон, что у ключей
     объекта и операндов сравнения (CLAUDE.md, инвариант 17). */
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
          React.createElement("h3", { style: { fontSize: 15, fontWeight: 600 } }, TR("Автоматический ремонт"),
            T(TR("Автоматический ремонт"),
              TR("Переписывает перевод по конкретным находкам back-check и проверки терминологии, затем перепроверяет теми же проверками. Новый текст остаётся, только если оценка не упала.\n\nИсправленные сегменты получают статус «Требует проверки»: автоправка не заверяет сама себя, подтвердить должен человек."))),
          React.createElement("p", { className: "muted", style: { marginTop: 6, fontSize: 14 } },
            touched.length ? TR("Ремонт применялся к ") + touched.length + TR(" сегментам") : TR("Ремонт ещё не запускался"))),
        gain !== null && React.createElement("div", { className: "dim", style: { fontSize: 13 } },
          TR("Средний прирост back-check: ") + (gain > 0 ? "+" : "") + gain + "%")),

      touched.length === 0 && pending.length === 0
        ? React.createElement(EmptyState, { icon: "repeat", title: TR("Чинить пока нечего"),
            sub: TR("Сначала прогоните back-check или проверку терминологии — ремонт работает по их находкам.") })
        : React.createElement("div", { style: { display: "flex", flexDirection: "column" } },
            React.createElement(StatRow, { label: TR("Исправлено"), note: TR("текст заменён, проверка подтвердила улучшение"), bold: true,
              count: applied.length, color: "var(--c-success)",
              onDrill: () => onDrill(TR("Ремонт: исправлено"), applied) }),
            React.createElement(StatRow, { label: TR("— ждут подтверждения"), note: TR("статус «Требует проверки»"),
              count: needReview.length, color: "var(--c-warning)",
              onDrill: () => onDrill(TR("Ремонт: ждут подтверждения"), needReview) }),
            React.createElement(StatRow, { label: TR("Откачено"), note: TR("вариант модели не улучшил оценку"),
              count: reverted.length, onDrill: () => onDrill(TR("Ремонт: откачено"), reverted) }),
            React.createElement(StatRow, { label: TR("Ждут ремонта"), note: TR("есть находки, ремонт не запускался"),
              count: pending.length, color: "var(--c-primary)",
              onDrill: () => onDrill(TR("Ремонт: ждут ремонта"), pending) }))
    )
  );
}

window.TabAnalysis = TabAnalysis;
