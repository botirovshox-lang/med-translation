/* ============================================================
   Tab: Glossary — medical terminology management
   ============================================================ */
const PAGE_SIZE = 100;
// Очередь кандидатов — карточки, а не строки таблицы: сотня разом
// нечитаема, да и решают их по одной.
const QUEUE_PAGE = 25;

// Поиск с выбором стороны: русский термин или английский перевод.
// «ё» приравнена к «е» — в медицинских текстах их пишут вперемешку.
const PAIR_SCOPES = [["all", "Везде"], ["src", "Оригинал (RU)"], ["tgt", "Перевод (EN)"]];
function pairNorm(t) { return (t || "").toLowerCase().replace(/ё/g, "е"); }
function pairMatches(row, q, scope) {
  const needle = pairNorm(q);
  if (!needle) return true;
  return (scope !== "tgt" && pairNorm(row.src).includes(needle))
      || (scope !== "src" && pairNorm(row.tgt).includes(needle));
}
function ScopeSelect({ value, onChange }) {
  return React.createElement(Select, { value, onChange, style: { width: "auto" }, "aria-label": "Где искать" },
    PAIR_SCOPES.map(([v, l]) => React.createElement("option", { key: v, value: v }, l)));
}


/* ============================================================
   Очередь кандидатов в глоссарий
   Сюда попадает всё, чему система научилась сама: расхождения между
   глоссарием и подтверждённым переводом, короткие подтверждённые сегменты,
   извлечённые моделью пары. В глоссарий кандидат уходит ТОЛЬКО после
   одобрения человеком — записи глоссария идут в промпт как правило, и
   автопополнение закрепляло бы собственные ошибки.
   ============================================================ */
const CAND_KIND = {
  conflict: ["Конфликт с глоссарием", "warn", "var(--c-warning)"],
  segment:  ["Из подтверждённого сегмента", "checkCircle", "var(--c-success)"],
  extract:  ["Извлечено моделью", "cpu", "var(--c-primary)"],
  audit:    ["Проверка терминологии", "book", "var(--c-purple)"],
};

/* ---------- Автоодобрение однозначных кандидатов ----------
   Кнопка «Проверить» ничего не меняет: сервер считает вердикты и возвращает,
   что попадёт и что отсеяно с причинами. Применение — отдельным нажатием,
   откат пачки — одним. Правила языко- и тематико-независимы, поэтому панель
   не знает ни про медицину, ни про русский: всё приходит с сервера. */
/* ---------- Вынос массового импорта ----------
   Удаление по одной записи — это про правку, а не про десять тысяч строк
   автоимпорта. Отдельная команда с предпросмотром, пощадой правленого
   человеком и откатом из файла. */
function GlossaryPurgePanel({ store, toast, onDone }) {
  const project = store.activeProject;
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState("");
  const [unusedOnly, setUnusedOnly] = useState(false);
  const [wholeService, setWholeService] = useState(false);
  /* Приказы, доставшиеся импорту по умолчанию миграции («записи нет в массовом
     импорте — значит добавлена руками»). Это предположение машины, а не чьё-то
     решение: записи со следом человека сервер не выносит в любом случае. */
  const [alsoOrders, setAlsoOrders] = useState(false);
  const [purges, setPurges] = useState([]);
  const reloadPurges = () => window.API.safeCall(() => window.API.purgeList())
    .then(r => setPurges((r && r.purges) || []));
  useEffect(() => { if (window.API) reloadPurges(); }, []);
  // Любая смена фильтра обесценивает прошлый разбор: цифра на кнопке
  // «Вынести N» обязана относиться к тому, что уйдёт на самом деле.
  useEffect(() => { setRes(null); },
    [project && project.id, unusedOnly, wholeService, alsoOrders]);
  if (!project) return null;

  const opts = (dry) => ({ project: wholeService ? null : project.id,
                           tier: alsoOrders ? "verified" : "auto",
                           unused_only: unusedOnly, dry_run: dry });

  const run = async (dry) => {
    setBusy(dry ? "check" : "apply");
    const r = await window.API.safeCall(() => window.API.purgeGlossary(opts(dry)));
    setBusy("");
    if (!r || !r.ok) { toast.error("Не выполнено", "Сервер не ответил."); return; }
    setRes(r);
    if (dry) {
      toast.info("К выносу: " + r.matched,
        "Пощажено правленого человеком: " + r.keptHuman + " · всего записей: " + r.total);
    } else {
      toast.warning("Вынесено: " + (r.removed || 0),
        "Копия сохранена, вернуть можно кнопкой ниже. Готовый перевод не изменился.");
      reloadPurges();
      onDone && onDone();
    }
  };

  const undo = async (stamp) => {
    setBusy("undo");
    const r = await window.API.safeCall(() => window.API.undoPurge(stamp));
    setBusy("");
    if (!r || !r.ok) { toast.error("Откат не выполнен", "Копия не найдена."); return; }
    setRes(null);
    reloadPurges();
    toast.success("Возвращено записей: " + r.restored,
      r.skipped ? "Пропущено: " + r.skipped + " — " + r.skippedWhy : "");
    onDone && onDone();
  };

  return React.createElement("div", { className: "card", style: { padding: "12px 14px", background: "var(--bg-sunken)", display: "flex", flexDirection: "column", gap: 10, marginBottom: 12 } },
    React.createElement("div", { className: "row between row-wrap", style: { gap: 10 } },
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Icon, { name: "close", size: 16, style: { color: "var(--c-error)" } }),
        React.createElement("span", { style: { fontWeight: 650, fontSize: 14 } }, "Вынести массовый импорт"),
        React.createElement(InfoTip, { title: "Что произойдёт", body: "Массовый импорт лежит в глоссарии уровнем «подсказка»: он уходит в промпт с пометкой «не проверено, часть неверна» и прямым разрешением его игнорировать. На уже готовый перевод вынос не влияет НИЧЕМ — расхождения и ремонт считаются только по записям уровня «приказ».\n\nМеняется одно: чем модель воспользуется при СЛЕДУЮЩЕМ переводе. Вместе с мусором уходит и сырьё: подсказка поднимается до приказа, когда несколько независимых чистых сегментов сойдутся на одном переводе.\n\nЗаписи, которых касался человек (одобрение кандидата, ручная правка, откат понижения), не выносятся никогда — сколько таких, сказано в отчёте. Вынесенное целиком уходит файлом в data/backups и возвращается откатом." })),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } },
        alsoOrders ? "уровень «приказ» · без следа решения человека"
                   : "уровень «подсказка»")),

    React.createElement("div", { className: "col", style: { gap: 4 } },
      React.createElement(Checkbox, { checked: unusedOnly, onChange: () => setUnusedOnly(v => !v) },
        "Только те, что не встречаются ни в одном тексте"),
      React.createElement(Checkbox, { checked: wholeService, onChange: () => setWholeService(v => !v) },
        "По всему сервису, а не только в области этого проекта"),
      React.createElement(Checkbox, { checked: alsoOrders, onChange: () => setAlsoOrders(v => !v) },
        "Приказы, доставшиеся импорту по умолчанию"),
      alsoOrders && React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5, paddingLeft: 26 } },
        "Уровень «приказ» запись могла получить не от человека, а от миграции: "
        + "«её нет в массовом импорте — значит добавлена руками». Одобренное "
        + "вами и правленное руками не тронется в любом случае.")),

    React.createElement("div", { className: "row row-wrap", style: { gap: 10, alignItems: "center" } },
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "target", disabled: !!busy, onClick: () => run(true) },
        busy === "check" ? "Считаем…" : "Посмотреть, что уйдёт"),
      res && res.matched > 0 && React.createElement(Btn, {
        variant: "danger", size: "sm", icon: "close", disabled: !!busy, onClick: () => run(false) },
        busy === "apply" ? "Выносим…" : "Вынести " + res.matched),
      res && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setRes(null) }, "Скрыть")),

    res && React.createElement("div", { className: "col", style: { gap: 5, fontSize: 12.5 } },
      React.createElement("div", null,
        "всего записей: ", React.createElement("b", null, res.total),
        " · к выносу: ", React.createElement("b", { style: { color: "var(--c-error)" } }, res.matched),
        " · пощажено правленного человеком: ", React.createElement("b", null, res.keptHuman)),
      res.matched === 0 && React.createElement("div", { className: "dim" },
        "Под фильтр ничего не попало — выносить нечего."),
      res.samples && res.samples.length > 0 && React.createElement("div", { className: "dim", style: { lineHeight: 1.6 } },
        "например: " + res.samples.map(x => x.src + " → " + x.tgt).join(" · ")),
      React.createElement("div", { className: "dim", style: { lineHeight: 1.55 } },
        "Готовый перевод не изменится: расхождения и ремонт считаются только "
        + "по записям уровня «приказ». Изменится то, чем модель воспользуется "
        + "при следующем переводе.")),

    purges.length > 0 && React.createElement("div", { className: "row row-wrap", style: { gap: 10, alignItems: "center", fontSize: 12, paddingTop: 6, borderTop: "1px solid var(--border)" } },
      React.createElement("span", { className: "dim" }, "Прошлые выносы:"),
      purges.slice(0, 4).map(x => React.createElement("span", { key: x.stamp, className: "row", style: { gap: 6 } },
        React.createElement("span", { className: "dim" }, x.stamp + (x.count != null ? " · " + x.count + " зап." : "")),
        React.createElement(Btn, { variant: "ghost", size: "sm", disabled: !!busy, onClick: () => undo(x.stamp) }, "Вернуть")))));
}


/* ---------- Смысловая сверка записей, уже стоящих приказом ----------
   Сверка при автоодобрении сторожит ВХОД в глоссарий. Записи, попавшие туда
   раньше (в том числе получившие приказ по умолчанию миграции), её не
   проходили — а приказывают модели и гонят ремонт именно они. Проверка
   платная, поэтому только по кнопке; понижение — отдельным нажатием. */
function GlossaryAuditPanel({ store, toast, onDone }) {
  const project = store.activeProject;
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState("");
  useEffect(() => { setRes(null); }, [project && project.id]);
  if (!project) return null;

  const run = async (dry, force) => {
    setBusy(dry ? (force ? "recheck" : "check") : "apply");
    const r = await window.API.safeCall(() => window.API.auditGlossary({
      project: project.id, dry_run: dry, force: !!force }));
    setBusy("");
    if (!r || !r.ok) {
      toast.error("Сверка не выполнена", "Нужен ключ OpenAI, или сервер не ответил.");
      return;
    }
    setRes(r);
    if (dry) {
      toast.info("Спрошено: " + r.checked + " · из памяти: " + (r.cached || 0),
        r.bad.length ? "Смысл расходится у " + r.bad.length
          + " · понизить можно " + r.downgradable
          : "Расхождений не найдено.");
    } else {
      toast.success("Понижено до подсказки: " + (r.downgraded || 0),
        "Перевод не тронут — записи перестали приказывать модели. "
        + "Пачку можно откатить в списке ниже.");
      onDone && onDone();
    }
  };

  const bad = (res && res.bad) || [];
  const CAP = 20;

  /* Находка, которую машина понизить не вправе (на записи след решения
     человека), обязана давать человеку способ согласиться. Иначе сверка
     показывает проблему и ничем не заканчивается — а именно на такие
     записи приходится больше всего сегментов. */
  const act = async (b, kind) => {
    if (kind === "del" && !window.confirm(
      "Удалить запись «" + b.src + " → " + b.tgt + "» из глоссария?\n\n"
      + "Готовый перевод не изменится. Если перевод верен в каком-то контексте, "
      + "лучше понизить до подсказки — тогда модель сможет им пользоваться, "
      + "но не будет обязана.")) return;
    setBusy("row");
    const r = await window.API.safeCall(() => kind === "del"
      ? window.API.deleteTerm(b.src, b.lang, b.domain)
      : window.API.demoteTerm(b.src, b.lang, b.domain));
    setBusy("");
    if (!r || !r.ok) { toast.error("Не выполнено", "Сервер не ответил."); return; }
    // Убираем из показанного сразу: строка про запись, которой в приказах
    // больше нет, — это уже неправда.
    setRes(x => x && ({ ...x, bad: x.bad.filter(y => y.src !== b.src || y.tgt !== b.tgt),
                        downgradable: Math.max(0, (x.downgradable || 0) - (b.humanTouched ? 0 : 1)) }));
    // Понижение снимает повод чинить дальше, но уже переписанное так и осталось.
    // Возвращаем его тут же: руками это сотни сегментов, а откат ничего
    // не сочиняет — подставляет текст, который стоял до правки.
    const done = (r.repairedCount || 0);
    let tail = "";
    if (kind !== "del" && done) {
      const rv = await window.API.safeCall(() => window.API.revertRepairs(b.src, b.lang, b.domain));
      if (rv && rv.ok) {
        tail = " · возвращено сегментов: " + rv.revertedCount
          + (rv.requeuedCount ? " · отдано ремонту заново: " + rv.requeuedCount : "")
          + (rv.skippedCount ? " · не вернуть: " + rv.skippedCount : "");
      } else {
        tail = " · ВНИМАНИЕ: ремонт вписал этот перевод в " + done
          + " сегм., откат не выполнился";
      }
    }
    toast.success(kind === "del" ? "Запись удалена" : "Понижено до подсказки",
      b.src + " → " + b.tgt
      + (kind === "del" ? "" : " · модель вправе её игнорировать") + tail);
    onDone && onDone();
  };
  return React.createElement("div", { className: "card", style: { padding: "12px 14px", background: "var(--bg-sunken)", display: "flex", flexDirection: "column", gap: 10, marginBottom: 12 } },
    React.createElement("div", { className: "row between row-wrap", style: { gap: 10 } },
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Icon, { name: "book", size: 16, style: { color: "var(--c-warning)" } }),
        React.createElement("span", { style: { fontWeight: 650, fontSize: 14 } }, "Сверка смысла записей"),
        React.createElement(InfoTip, { title: "Зачем это нужно", body: "Приказная запись глоссария заставляет модель писать именно этот перевод и служит основанием для ремонта. Ни одна другая проверка не спрашивает, ТО ЖЕ ли это понятие: корпус подтверждает лишь, что строка в языке существует, проверка терминов — что термин настоящий, согласие сегментов — что модель повторяет себя. «Анизакидоз → Anisakis» (болезнь против рода паразита) проходит их все.\n\nНаходка ПОНИЖАЕТСЯ до подсказки, а не удаляется: перевод остаётся на месте, запись остаётся видна, но перестаёт приказывать модели и гнать ремонт.\n\nЗаписи со следом решения человека (одобрение кандидата, ручная правка) не понижаются никогда — только помечаются. Своё предположение машина вправе пересмотреть, чужое решение — нет." })),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } },
        res ? "спрошено: " + res.checked + " · из памяти: " + (res.cached || 0)
              + " · всего приказных: " + res.total
            : "проверяются только записи уровня «приказ»")),

    React.createElement("div", { className: "row row-wrap", style: { gap: 10, alignItems: "center" } },
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "target", disabled: !!busy, onClick: () => run(true, false) },
        busy === "check" ? "Сверяем…" : res ? "Досверить новые" : "Проверить смысл записей"),
      // Вердикт лежит на записи, поэтому обычная кнопка спрашивает только про
      // новое. Переспросить всё — отдельное действие: это полная оплата ещё
      // раз, и на пограничных парах судья ответит иначе.
      res && React.createElement(Btn, { variant: "ghost", size: "sm", disabled: !!busy, onClick: () => run(true, true) },
        busy === "recheck" ? "Переспрашиваем…" : "Переспросить всё (" + res.total + ")"),
      res && res.downgradable > 0 && React.createElement(Btn, {
        variant: "primary", size: "sm", icon: "check", disabled: !!busy, onClick: () => run(false) },
        busy === "apply" ? "Понижаем…" : "Понизить " + res.downgradable + " до подсказки"),
      res && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setRes(null) }, "Скрыть")),

    res && (res.capped > 0 || res.pending > 0) && React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
      "Осталось спросить: " + ((res.capped || 0) + (res.pending || 0))
      + " — нажмите «Досверить новые» ещё раз. Первыми идут записи, которые "
      + "уже расходятся с переводом в этом проекте."),

    res && !bad.length && React.createElement("div", { className: "dim", style: { fontSize: 12.5 } },
      "Расхождений смысла не найдено."),

    bad.length > 0 && React.createElement("div", { className: "col", style: { gap: 5 } },
      bad.slice(0, CAP).map((b, i) => React.createElement("div", {
        key: i, className: "row between row-wrap", style: { gap: 10, fontSize: 12.5, padding: "3px 0" } },
        React.createElement("span", null,
          b.src + " → ",
          React.createElement("b", { style: { color: "var(--c-error)" } }, b.tgt),
          React.createElement("span", { className: "dim" },
            " — " + (b.kind === "rule" ? (b.why || "правилом не годится") : b.back))),
        React.createElement("span", { className: "row", style: { gap: 8 } },
          b.segments > 0 && React.createElement("span", { className: "dim", style: { fontSize: 12 } },
            "сегментов: " + b.segments),
          b.disputed > 0 && React.createElement("span", { className: "dim", style: { fontSize: 12 } },
            "проверка спорит: " + b.disputed),
          b.humanTouched
            ? React.createElement("span", { className: "row", style: { gap: 6 } },
                React.createElement(Badge, { variant: "confirmed" }, "решили вы"),
                React.createElement(Btn, { variant: "ghost", size: "sm", disabled: !!busy,
                  onClick: () => act(b, "demote") }, "Понизить"),
                React.createElement(Btn, { variant: "ghost", size: "sm", disabled: !!busy,
                  onClick: () => act(b, "del") }, "Удалить"))
            : React.createElement(Badge, { variant: "soft" }, "понизится")))),
      bad.length > CAP && React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
        "и ещё " + (bad.length - CAP) + " записей")));
}


function AutoApprovePanel({ store, toast, onDone }) {
  const project = store.activeProject;
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState("");
  const [softOnly, setSoftOnly] = useState(false);
  /* Разрешение на приказ по согласию сегментов там, где область его запрещает
     (медицина, фарма, юриспруденция). НЕ хранится в localStorage намеренно:
     это разрешение на один запуск, а не настройка. Гаснет при смене проекта
     и при включении «Только подсказки» — просьба ничего не поднимать сильнее. */
  const [allowVerified, setAllowVerified] = useState(false);
  const [batches, setBatches] = useState([]);
  const [domains, setDomains] = useState([]);

  useEffect(() => {
    if (!window.API) return;
    window.API.safeCall(() => window.API.autoBatches()).then(r => setBatches((r && r.batches) || []));
    window.API.safeCall(() => window.API.models()).then(r => setDomains((r && r.domains) || []));
  }, []);

  /* Считаем сразу при открытии вкладки: разбор идёт на сервере без вызовов
     модели, платить не за что, а прятать цифру за лишним кликом незачем. */
  useEffect(() => {
    if (!window.API || !store.activeProject) return;
    let cancelled = false;
    window.API.safeCall(() => window.API.autoApprove({
      project: store.activeProject.id, dry_run: true,
      max_tier: softOnly ? "auto" : null,
      allow_verified: allowVerified,
    })).then(res => { if (!cancelled && res && res.ok) setPreview(res); });
    return () => { cancelled = true; };
  }, [store.activeProject && store.activeProject.id, softOnly, allowVerified]);

  /* Разрешение не переживает смену проекта: области у проектов разные, и
     молча перенести снятый запрет на соседний проект нельзя. */
  useEffect(() => { setAllowVerified(false); },
    [store.activeProject && store.activeProject.id]);

  if (!project) return null;
  const domLabel = (id) => (domains.find(d => d.id === id) || {}).label || id;
  const scopeText = project.src + "→" + project.tgt + " · " + domLabel(project.domain || "medical");

  const opts = () => ({ project: project.id, max_tier: softOnly ? "auto" : null,
                        allow_verified: allowVerified });

  const check = async () => {
    setBusy("check");
    const res = await window.API.safeCall(() => window.API.autoApprove({ ...opts(), dry_run: true }));
    setBusy("");
    if (!res || !res.ok) { toast.error("Не удалось посчитать", "Сервер не ответил."); return; }
    setPreview(res);
    if (!res.counts.auto && !res.counts.verified && !res.counts.closed)
      toast.info("Однозначных нет", "Все кандидаты в этой области требуют решения человека.");
  };

  const apply = async () => {
    setBusy("apply");
    const res = await window.API.safeCall(() => window.API.autoApprove({ ...opts(), dry_run: false }));
    setBusy("");
    if (!res || !res.ok) { toast.error("Не удалось одобрить", "Сервер не ответил."); return; }
    setPreview(null);
    const n = res.counts.auto + res.counts.verified;
    // batch приходит null, когда сервер ничего не выбрал: в историю такое не кладём,
    // иначе «Откатить» уходит на /auto-approve/null/undo и возвращает 422.
    if (res.batch) setBatches(b => [{ id: res.batch, at: "только что", counts: res.counts }, ...b]);
    toast.success("Одобрено автоматически: " + n,
      "Подсказок: " + res.counts.auto + " · приказов: " + res.counts.verified +
      (res.counts.rejectedMeaning
        ? " · отклонено по смыслу: " + res.counts.rejectedMeaning : "") +
      (res.counts.closed ? " · закрыто как уже известное: " + res.counts.closed : ""));
    onDone && onDone();
  };

  const undo = async (batch) => {
    setBusy("undo");
    const res = await window.API.safeCall(() => window.API.undoAutoApprove(batch));
    setBusy("");
    if (!res || !res.ok) { toast.error("Откат не выполнен", "Сервер не ответил."); return; }
    setBatches(b => b.filter(x => x.id !== batch));
    toast.warning("Пачка #" + batch + " откачена",
      "Удалено: " + res.removed + " · возвращено прежних: " + res.restored +
      " · кандидатов обратно в очередь: " + res.returned);
    onDone && onDone();
  };

  const tierBadge = (tier) => tier === "verified"
    ? React.createElement(Badge, { variant: "confirmed" }, "приказ")
    : tier === "auto"
      ? React.createElement(Badge, { variant: "soft" }, "подсказка")
      : React.createElement(Badge, { variant: "soft" }, "уже есть");

  const c = preview && preview.counts;
  // Запрет области виден по политике, которую вернул сервер: зашивать список
  // «медицина, фарма, юриспруденция» в браузер — значит завести второй
  // источник правды рядом с AUTO_APPROVE_BY_DOMAIN.
  // Запрет области — отдельное поле с сервера: он снимается ДО учёта
  // разрешения, поэтому тумблер не исчезает от того, что его включили.
  const banned = !!(preview && preview.policy && preview.policy.domainBanned);
  return React.createElement("div", { className: "card", style: { padding: "12px 14px", background: "var(--bg-sunken)", display: "flex", flexDirection: "column", gap: 10, marginBottom: 12 } },
    React.createElement("div", { className: "row between row-wrap", style: { gap: 10 } },
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Icon, { name: "zap", size: 16, style: { color: "var(--c-primary)" } }),
        React.createElement("span", { style: { fontWeight: 650, fontSize: 14 } }, "Автоодобрение однозначных"),
        React.createElement(InfoTip, { title: "Что считается однозначным",
          body: "Пара попадает в глоссарий сама, только если: у термина ровно один вариант перевода в очереди; та же пара пришла из нескольких независимых сегментов ИЛИ сегмент подтвердил человек; сегменты-доноры прошли back-check и проверку терминологии чисто; пара не спорит с проверенной записью.\n\nПо умолчанию запись уходит уровнем «подсказка» — модель вправе её игнорировать. Приказом («use these exact translations») запись становится от человека или от трёх независимых чистых сегментов, а в медицине, фармацевтике и юриспруденции — только от человека.\n\nПравила не зависят от языка и тематики: считаются согласие источников и оценки других прогонов, а не мнение той модели, что делала перевод." })),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "область: " + scopeText)),

    React.createElement("div", { className: "row row-wrap", style: { gap: 10, alignItems: "center" } },
      React.createElement(Btn, { variant: "secondary", size: "sm", icon: "target", disabled: !!busy, onClick: check },
        busy === "check" ? "Считаем…" : preview ? "Пересчитать" : "Проверить, что попадёт"),
      preview && (c.auto + c.verified + c.closed > 0) && React.createElement(Btn, {
        variant: "primary", size: "sm", icon: "check", disabled: !!busy, onClick: apply },
        busy === "apply" ? "Одобряем…" : "Одобрить " + (c.auto + c.verified)),
      preview && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setPreview(null) }, "Скрыть"),
      React.createElement("div", { className: "spacer" }),
      React.createElement(Switch, { on: softOnly, label: "Только подсказки", onClick: () => { setSoftOnly(v => !v); setPreview(null); } }),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "не поднимать до приказа")),

    // Запрет области снимается только здесь и только на этот запуск. Показываем
    // тумблер лишь там, где запрет реально есть: в остальных областях приказ по
    // согласию сегментов и так разрешён, и лишний переключатель врал бы о том,
    // что без него чего-то не хватает.
    banned && !softOnly && React.createElement(
      "div", { className: "col", style: { gap: 6, padding: "9px 11px", borderRadius: 8,
        background: allowVerified ? "var(--c-warning-bg, rgba(240,180,40,.10))" : "transparent",
        border: "1px solid " + (allowVerified ? "var(--c-warning)" : "var(--border)") } },
      React.createElement("div", { className: "row", style: { gap: 10, alignItems: "center" } },
        React.createElement(Switch, { on: allowVerified, label: "Приказ по согласию сегментов",
          onClick: () => { setAllowVerified(v => !v); setPreview(null); } }),
        React.createElement("span", { className: "dim", style: { fontSize: 12 } },
          "снять запрет области на этот запуск")),
      React.createElement("div", { className: "dim", style: { fontSize: 12, lineHeight: 1.6 } },
        allowVerified
          ? "Приказ получат термины с согласием " + (preview.policy.verified_min_segments || 3)
            + " независимых чистых сегментов с РАЗНЫМИ исходниками. При "
            + "применении каждый пройдёт смысловую сверку судьёй (то же ли "
            + "понятие) — ложные друзья вроде «болезнь → род паразита» будут "
            + "отклонены. Пачка откатывается целиком кнопкой ниже."
          : "Сейчас в этой области приказ даёт только человек или выверенный "
            + "справочник — согласия сегментов не хватает. Включите, если "
            + "готовы принять машинный приказ под свою ответственность.")),

    preview && c.pending === 0 && React.createElement("div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.6 } },
      "Кандидатов в этой области пока нет. Они появляются сами: после back-check и проверки терминологии — с сегментов, прошедших обе проверки чисто; и при подтверждении сегмента вручную."),

    preview && c.pending > 0 && React.createElement("div", { className: "col", style: { gap: 8 } },
      React.createElement("div", { className: "row row-wrap", style: { gap: 14, fontSize: 12.5 } },
        React.createElement("span", null, "разобрано: ", React.createElement("strong", null, c.pending),
          c.queueTotal > c.pending ? " из " + c.queueTotal : ""),
        React.createElement("span", { style: { color: "var(--c-success)" } }, "подсказкой: ", React.createElement("strong", null, c.auto)),
        React.createElement("span", { style: { color: "var(--c-primary)" } }, "приказом: ", React.createElement("strong", null, c.verified)),
        React.createElement("span", { className: "dim" }, "уже в глоссарии: ", React.createElement("strong", null, c.closed)),
        React.createElement("span", { style: { color: "var(--c-warning)" } }, "останется человеку: ", React.createElement("strong", null, c.skipped))),

      preview.items.length > 0 && React.createElement("div", { className: "col", style: { gap: 4, maxHeight: 260, overflow: "auto" } },
        preview.items.slice(0, 60).map(it => React.createElement("div", { key: it.id, className: "row row-wrap", style: { gap: 8, fontSize: 13, padding: "3px 0" } },
          React.createElement("span", { style: { fontWeight: 600 } }, it.src),
          React.createElement(Icon, { name: "chevR", size: 12, style: { color: "var(--text-3)" } }),
          React.createElement("span", null, it.tgt),
          tierBadge(it.tier),
          React.createElement("span", { className: "dim", style: { fontSize: 12 } }, it.reason))),
        preview.items.length > 60 && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
          "…и ещё " + (preview.items.length - 60))),

      preview.skipped.length > 0 && React.createElement("div", { className: "col", style: { gap: 3 } },
        React.createElement("div", { className: "dim", style: { fontSize: 12, fontWeight: 600, marginTop: 4 } }, "Останется человеку — почему:"),
        preview.skipped.map((b, i) => React.createElement("div", { key: i, className: "dim", style: { fontSize: 12.5 } },
          b.count + "× " + b.reason +
          (b.samples.length ? " (напр. " + b.samples.map(s => s.src).join(", ") + ")" : ""))))),

    batches.length > 0 && React.createElement("div", { className: "row row-wrap", style: { gap: 8, alignItems: "center", borderTop: "1px solid var(--border)", paddingTop: 8 } },
      React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "Последние прогоны:"),
      batches.slice(0, 3).map(b => React.createElement("span", { key: b.id, className: "row", style: { gap: 4 } },
        React.createElement(Badge, { variant: "soft" }, "#" + b.id + " · " + ((b.counts || {}).auto + (b.counts || {}).verified || 0) + " зап."),
        React.createElement(Btn, { variant: "ghost", size: "sm", icon: "repeat", disabled: !!busy, onClick: () => undo(b.id) }, "Откатить"))))
  );
}

function TermQueue({ store, toast, version }) {
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({});
  const [loading, setLoading] = useState(true);
  const [drafts, setDrafts] = useState({});      // {id: предлагаемый перевод}
  const [busy, setBusy] = useState(null);
  const [open, setOpen] = useState(true);
  // total — сколько кандидатов ЕСТЬ, items — сколько показано. Раньше значок
  // показывал длину показанного списка, а он обрезан лимитом: при 260 в очереди
  // там всегда стояло 200, и разобранные двадцать штук ничего не меняли.
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(QUEUE_PAGE);
  // Разбор «почему кандидат ждёт» с сервера: очередь на четыреста карточек
  // без него — стена одинаковых строк, и не видно, что треть из них вообще
  // не термины, а обрывки фраз.
  const [groups, setGroups] = useState([]);
  const [only, setOnly] = useState(null);      // показывать только эту причину

  const load = async (lim) => {
    if (!window.API) { setLoading(false); return; }
    const pid = store.activeProject && store.activeProject.id;
    const res = await window.API.safeCall(() => window.API.termQueue("pending", lim || limit, pid));
    setItems((res && res.items) || []);
    setCounts((res && res.counts) || {});
    setGroups((res && res.groups) || []);
    setTotal((res && res.total) || 0);
    setLoading(false);
  };

  // Массовое ОТКЛОНЕНИЕ группы. Массового одобрения тут нет намеренно:
  // одобрение пишет правило для всех будущих текстов, и подписывать пачкой
  // то, что не читал, — ровно то, от чего защищает вся остальная система.
  const rejectGroup = async (g) => {
    const msg = "Отклонить " + g.count + " кандидатов?\n\n" + g.reason
      + "\n\nВ глоссарий ничего не пишется. Если такая пара встретится снова "
      + "с другим переводом, вопрос задастся заново.";
    if (!window.confirm(msg)) return;
    setBusy("group");
    const res = await window.API.safeCall(() => window.API.bulkReject(g.ids));
    setBusy(null);
    if (!res || !res.ok) { toast.error("Не удалось отклонить", "Сервер не ответил."); return; }
    toast.info("Отклонено: " + res.count,
      g.reason + (res.kept && res.kept.length
        ? " · не тронуто: " + res.kept.length + " — " + res.keptWhy : ""));
    setOnly(null);
    load();
  };
  // Перезагружаем и при смене проекта: разбор «почему ждёт» и id в группах
  // считаются в его области, и от чужого проекта они не годятся.
  useEffect(() => { setOnly(null); load(); },
    [version, store.activeProject && store.activeProject.id]);

  // Решили карточку — убираем её и из показанного, и из общего числа:
  // иначе счётчик стоял бы на месте до перезагрузки страницы.
  // Разбор вариантов по смыслу: {cid: {loading|variants}}. Платный вызов,
  // поэтому только по кнопке на конкретной карточке.
  const [explained, setExplained] = useState({});
  const explain = async (c) => {
    setExplained(e => ({ ...e, [c.id]: { loading: true } }));
    // Черновик из поля — это ровно тот вариант, ради которого нажимают кнопку.
    // Не передав его, мы сравнили бы всё, кроме того, что человек напечатал.
    const typed = (drafts[c.id] !== undefined ? drafts[c.id] : c.tgt || "").trim();
    const res = await window.API.safeCall(() => window.API.explainTerm(c.id, typed));
    if (!res || !res.ok) {
      setExplained(e => ({ ...e, [c.id]: null }));
      toast.error("Не удалось разобрать", "Модель не ответила или у термина нет вариантов.");
      return;
    }
    setExplained(e => ({ ...e, [c.id]: res }));
  };

  const drop = (ids) => {
    const gone = new Set(ids);
    setItems(list => list.filter(x => !gone.has(x.id)));
    setTotal(t => Math.max(0, t - gone.size));
  };

  /* Замечание судьи по карточке: {cid: {kind, text}}. Живёт до решения —
     одобрение вопреки ему идёт вторым нажатием, уже осознанным. */
  const [warned, setWarned] = useState({});

  const approve = async (c, confirm) => {
    const tgt = (drafts[c.id] !== undefined ? drafts[c.id] : c.tgt || "").trim();
    if (!tgt) { toast.warning("Нужен перевод", "Впишите верный вариант — он станет проверенной записью глоссария."); return; }
    setBusy(c.id);
    const res = await window.API.safeCall(() => window.API.approveTerm(c.id, { tgt, confirm: !!confirm }));
    setBusy(null);
    if (!res || !res.ok) { toast.error("Не удалось одобрить", "Сервер не ответил."); return; }
    // Судья возражает — в глоссарий ничего не записано. Показываем возражение
    // на самой карточке: тост уедет, а решение принимать здесь.
    if (res.warning) {
      setWarned(w => ({ ...w, [c.id]: res.warning }));
      toast.warning("Проверьте перед одобрением", res.warning.text);
      return;
    }
    setWarned(w => { const n = { ...w }; delete n[c.id]; return n; });
    // Сервер закрывает и остальные карточки про этот же термин: человек ответил
    // на вопрос, а не на карточку. Убираем их сразу, иначе они висят до перезагрузки.
    drop([c.id].concat(res.closed || []));
    toast.success(res.replaced ? "Запись глоссария заменена" : "Термин добавлен в глоссарий",
      c.src + " → " + tgt + ((res.closed && res.closed.length)
        ? " · закрыто карточек про этот же термин: " + res.closed.length : ""));
  };

  const reject = async (c) => {
    setBusy(c.id);
    const res = await window.API.safeCall(() => window.API.rejectTerm(c.id));
    setBusy(null);
    if (!res || !res.ok) { toast.error("Не удалось отклонить", "Сервер не ответил."); return; }
    drop([c.id]);
    toast.info("Отклонено", "Этот кандидат больше не всплывёт.");
  };

  if (loading) return null;
  if (!items.length && !total) return null;

  return React.createElement("div", { className: "card card-pad", style: { marginBottom: 18 } },
    React.createElement("div", { className: "row between", style: { cursor: "pointer" }, onClick: () => setOpen(o => !o) },
      React.createElement("div", { className: "row", style: { gap: 10 } },
        React.createElement(Icon, { name: open ? "chevD" : "chevR", size: 16 }),
        React.createElement("h3", { style: { margin: 0, fontSize: 16 } }, "Кандидаты в глоссарий"),
        React.createElement(Badge, { variant: "review" }, total),
        // Молчаливых потолков не бывает: показали часть — сказали, какую.
        total > items.length && React.createElement("span", { className: "dim", style: { fontSize: 12 } },
          "показаны " + items.length),
        React.createElement(InfoTip, { title: "Откуда берутся кандидаты",
          body: "Система учится на подтверждённых сегментах: расхождение с глоссарием, короткий сегмент-термин, извлечение моделью. Ни один кандидат не попадает в глоссарий сам — глоссарий уходит в промпт как правило, и автопополнение закрепляло бы ошибки перевода." })),
      React.createElement("span", { className: "dim", style: { fontSize: 12 } },
        "по частоте · одобрено: " + (counts.approved || 0) + " · отклонено: " + (counts.rejected || 0))),

    // Разбор очереди по причинам: сразу видно, где работа человека, а где мусор.
    open && groups.length > 0 && React.createElement("div", { className: "col", style: { gap: 5, marginTop: 12 } },
      React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        "Почему ждут — нажмите, чтобы отобрать:"),
      groups.map(g => React.createElement("div", { key: g.reason, className: "row between", style: { gap: 10, fontSize: 12.5, padding: "3px 0" } },
        React.createElement("span", {
          style: { cursor: "pointer", fontWeight: only === g.reason ? 650 : 400,
                   color: g.reason === "ready" ? "var(--c-success)" : "var(--text-2)" },
          onClick: () => {
            const next = only === g.reason ? null : g.reason;
            setOnly(next);
            // Счётчик группы — по всей очереди, а показанная страница короче.
            // Без подгрузки клик по группе часто давал бы пустой список.
            if (next && g.count > items.length) { const n = Math.min(g.count + 5, 400); setLimit(n); load(n); }
          } },
          (g.reason === "ready" ? "готовы к автоодобрению (до корпусной проверки)"
            : g.reason === "closed" ? "уже есть в глоссарии"
              : g.reason) + " · " + g.count),
        g.bulk && React.createElement(Btn, {
          variant: "ghost", size: "sm", disabled: !!busy, onClick: () => rejectGroup(g) },
          "Отклонить все"))),
      React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
        "Одобрить пачкой можно только то, что подтверждено, — это делает "
        + "«Автоодобрение однозначных» выше. Отклонить можно любую группу: "
        + "в глоссарий ничего не пишется, а если пара встретится снова "
        + "с другим переводом, вопрос задастся заново.")),

    open && React.createElement("div", { className: "col", style: { gap: 10, marginTop: 14 } },
      items.filter(c => !only || c.why === only).map(c => {
        const [label, icon, color] = CAND_KIND[c.kind] || ["Кандидат", "info", "var(--text-2)"];
        return React.createElement("div", { key: c.id, className: "card", style: { padding: "12px 14px", background: "var(--bg-sunken)", display: "flex", flexDirection: "column", gap: 8 } },
          React.createElement("div", { className: "row between row-wrap", style: { gap: 8 } },
            React.createElement("div", { className: "row", style: { gap: 8 } },
              React.createElement(Icon, { name: icon, size: 15, style: { color } }),
              React.createElement("span", { style: { fontSize: 12, color, fontWeight: 600 } }, label),
              c.hits > 1 && React.createElement(Badge, { variant: "soft" }, "встречалось " + c.hits + "×")),
            React.createElement("span", { className: "dim", style: { fontSize: 12 } },
              (c.lang ? c.lang + " · " : "") +
              (c.project ? "проект #" + c.project : "") +
              ((c.segments && c.segments.length > 1)
                ? " · сегментов: " + c.segments.length
                : (c.segment ? " · сегмент #" + c.segment : "")))),

          React.createElement("div", { className: "row row-wrap", style: { gap: 10, alignItems: "center" } },
            React.createElement("span", { style: { fontWeight: 600 } }, c.src),
            React.createElement(Icon, { name: "chevR", size: 14, style: { color: "var(--text-3)" } }),
            React.createElement(Input, {
              value: drafts[c.id] !== undefined ? drafts[c.id] : (c.tgt || ""),
              placeholder: c.kind === "conflict" ? "верный перевод" : "перевод",
              onChange: (e) => setDrafts(d => ({ ...d, [c.id]: e.target.value })),
              style: { maxWidth: 320 } }),
            c.wasTgt && React.createElement("span", { className: "dim", style: { fontSize: 12.5 } },
              "в глоссарии сейчас: ", React.createElement("s", null, c.wasTgt))),

          // Почему автоматика не берёт эту карточку. Без этого человек не
          // понимает, чего от него ждут: дорешать или дождаться проверок.
          c.why && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
            c.why === "ready" ? "готов к автоодобрению (до корпусной проверки)"
              : c.why === "closed" ? "уже есть в глоссарии"
                : "ждёт человека: " + c.why),

          c.note && React.createElement("div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.5 } }, c.note),

          c.sampleSrc && React.createElement("div", { className: "dim", style: { fontSize: 12, lineHeight: 1.6 } },
            React.createElement("div", null, c.sampleSrc),
            React.createElement("div", { style: { color: "var(--c-primary)" } }, c.sampleTgt)),

          // Разбор по смыслу: всё написано на языке ОРИГИНАЛА, чтобы выбирать
          // мог человек, не владеющий целевым языком. Он сравнивает значения,
          // а не строки, и нажимает на то, которое имел в виду.
          explained[c.id] && explained[c.id].variants && React.createElement("div",
            { className: "col", style: { gap: 6, borderTop: "1px solid var(--border)", paddingTop: 8 } },
            React.createElement("div", { className: "dim", style: { fontSize: 12 } },
              "Что означает каждый вариант — выберите по смыслу:"),
            explained[c.id].variants.map((v, i) => React.createElement("div", {
              key: i, className: "card", style: { padding: "8px 11px", background: "var(--bg)", cursor: "pointer", display: "flex", flexDirection: "column", gap: 3 },
              onClick: () => setDrafts(d => ({ ...d, [c.id]: v.tgt })) },
              React.createElement("div", { className: "row between row-wrap", style: { gap: 8 } },
                React.createElement("span", { style: { fontWeight: 600 } }, v.tgt),
                React.createElement("span", { className: "row", style: { gap: 6 } },
                  v.authority && React.createElement(Badge, {
                    variant: v.authority.tier === "verified" ? "confirmed" : "soft" },
                    v.authority.tier === "verified" ? "выверенный справочник" : "есть в справочнике"),
                  v.corpus && React.createElement(Badge, { variant: "soft" },
                    v.corpus.label + ": " + v.corpus.hits),
                  v.same === false && React.createElement(Badge, { variant: "review" }, "иное понятие"),
                  v.same === null && React.createElement(Badge, { variant: "soft" }, "модель не ответила"))),
              v.back && React.createElement("div", { style: { fontSize: 13 } },
                React.createElement("span", { className: "dim" }, "обратно: "), v.back),
              v.meaning && React.createElement("div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.5 } }, v.meaning),
              v.usage && React.createElement("div", { className: "dim", style: { fontSize: 12 } }, "употребление: " + v.usage))),
            explained[c.id].dropped > 0 && React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
              "Показаны первые 6 вариантов, ещё " + explained[c.id].dropped + " не разобрано."),
            React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
              "Нажмите на вариант — он подставится в поле выше. Разобрала модель "
              + (explained[c.id].model || "") + "; проверьте, что смысл совпадает с оригиналом.")),

          warned[c.id] && React.createElement("div", {
            className: "col", style: { gap: 3, padding: "8px 11px", borderRadius: 8,
              background: "var(--c-warning-bg, rgba(240,180,40,.10))",
              border: "1px solid var(--c-warning)" } },
            React.createElement("div", { style: { fontSize: 12.5, fontWeight: 600 } },
              warned[c.id].kind === "meaning"
                ? "Судья: перевод означает другое"
                : "Судья: правилом на весь документ не годится"),
            React.createElement("div", { className: "dim", style: { fontSize: 12.5, lineHeight: 1.55 } },
              warned[c.id].text),
            React.createElement("div", { className: "dim", style: { fontSize: 11.5, lineHeight: 1.5 } },
              warned[c.id].kind === "rule"
                ? "Запись приказывает модели во ВСЕХ сегментах сразу. Если перевод "
                  + "верен только в каком-то контексте — лучше отклонить: подсказку "
                  + "модель применит по месту сама."
                : "В глоссарий ничего не записано. Исправьте перевод в поле выше "
                  + "или отклоните кандидата.")),

          React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
            React.createElement(Btn, { variant: "primary", size: "sm", icon: "check", disabled: busy === c.id,
              onClick: () => approve(c, !!warned[c.id]) },
              warned[c.id] ? "Всё равно одобрить" : "В глоссарий"),
            React.createElement(Btn, { variant: "ghost", size: "sm", icon: "close", disabled: busy === c.id, onClick: () => reject(c) }, "Отклонить"),
            React.createElement(Btn, {
              variant: "secondary", size: "sm", icon: "book",
              disabled: busy === c.id || (explained[c.id] && explained[c.id].loading),
              onClick: () => explain(c) },
              explained[c.id] && explained[c.id].loading ? "Разбираем…"
                : explained[c.id] ? "Разобрать заново" : "Что это значит?")));
      }),
      total > items.length && React.createElement(Btn, {
        variant: "ghost", size: "sm", onClick: () => { const n = limit + QUEUE_PAGE; setLimit(n); load(n); } },
        "Показать ещё " + Math.min(QUEUE_PAGE, total - items.length) + " из " + (total - items.length)),
      !items.filter(c => !only || c.why === only).length && React.createElement(
        "div", { className: "dim", style: { fontSize: 13 } },
        only ? "В этой группе на загруженной странице ничего нет — нажмите «Показать ещё»."
             : "Нерешённых кандидатов нет.")
    )
  );
}

/* «Знания» — глоссарий и память переводов на одной странице. Разделены они
   были только исторически: это две справочные базы, которые работают в паре
   и по одной и той же области (языковая пара + тематика). Разбираться, почему
   термин взялся из одной, а перевод строки из другой, проще в одном месте. */
function TabKnowledge({ store, toast }) {
  const [side, setSide] = useState("glossary");
  return React.createElement("div", null,
    React.createElement("div", { className: "row", style: { gap: 8, padding: "18px 24px 0" } },
      [["glossary", "Глоссарий", store.glossary.length],
       ["tm", "Память переводов", (store.tm || []).length]].map(([key, label, n]) =>
        React.createElement(Btn, {
          key, variant: side === key ? "primary" : "ghost", size: "sm",
          onClick: () => setSide(key) }, label + " · " + n))),
    React.createElement(side === "glossary" ? TabGlossary : TabTM, { store, toast }));
}

function TabGlossary({ store, toast }) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [cat, setCat] = useState("all");
  const [sort, setSort] = useState("alpha");
  const [modal, setModal] = useState(null);
  const [allTerms, setAllTerms] = useState(store.glossary);
  const [loaded, setLoaded] = useState(false);
  const [page, setPage] = useState(0);
  // Автоодобрение и откат меняют и очередь, и сам глоссарий — обоим нужен
  // общий сигнал «перечитай», иначе таблица показывает вчерашний список.
  const [queueVersion, setQueueVersion] = useState(0);

  // Load full glossary from API on mount
  useEffect(() => {
    window.API && window.API.safeCall(() => window.API.listGlossary("", "", 10000, 0)).then(res => {
      if (res && res.items) { setAllTerms(res.items); store.glossary = res.items; }
      setLoaded(true);
    });
  }, [queueVersion]);

  // Reset page on filter change
  useEffect(() => { setPage(0); }, [query, scope, cat, sort]);

  const cats = ["all"].concat(
    Array.from(new Set(allTerms.map(g => g.cat).filter(Boolean))).sort());
  let rows = allTerms.filter(g => {
    if (cat !== "all" && g.cat !== cat) return false;
    if (query && !pairMatches(g, query, scope)) return false;
    return true;
  });
  rows = rows.slice().sort((a, b) => sort === "freq" ? (b.freq||0) - (a.freq||0) : a.src.localeCompare(b.src, "ru"));
  const totalPages = Math.ceil(rows.length / PAGE_SIZE);
  const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const save = (term, isNew) => {
    store.saveTerm(term, isNew);
    setModal(null);
    toast.success(isNew ? "Термин добавлен" : "Термин обновлён", term.src + " → " + term.tgt);
  };
  const del = (term) => { store.deleteTerm(term); toast.warning("Термин удалён", term.src); };

  // Клик по самому термину = «покажи, где он используется»: открываем редактор
  // с фильтром по затронутым сегментам. Совпадения ищет сервер тем же матчером,
  // что и инъекция в промпт, — иначе список разошёлся бы с реальностью.
  const openUsage = async (term, e) => {
    e.stopPropagation();
    if (!window.API) return;
    const res = await window.API.safeCall(() => window.API.glossaryUsage(term.src, 1, term.lang, term.domain));
    if (!res || !res.total) {
      toast.info("Термин не встречается", "«" + term.src + "» не найден ни в одном сегменте проектов.");
      return;
    }
    // Фильтр применяется к активному проекту — открываем тот, где совпадений больше
    const best = res.projects.slice().sort((a, b) => b.segments.length - a.segments.length)[0];
    const active = store.activeProject;
    const pick = (active && res.projects.find(x => x.id === active.id)) || best;
    if (!active || active.id !== pick.id) store.openProject(pick.id);
    store.setSegmentFilter(pick.segments);
    store.go("editor");
    toast.info("Показаны сегменты с термином", "«" + term.src + "» — " + pick.segments.length
      + " сегм." + (pick.violating.length ? " · перевод расходится с глоссарием: " + pick.violating.length : ""));
  };

  const confMeta = { high: ["badge-confirmed", "Высокая"], medium: ["badge-review", "Средняя"], low: ["badge-failed", "Низкая"] };

  return React.createElement("div", { className: "page page-wide" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Глоссарий",
        React.createElement(InfoTip, { title: "Глоссарий", body: "База утверждённых медицинских терминов с переводами. Используется для инъекции в GPT-промпт и проверки консистентности в QA." })),
      React.createElement("p", { className: "lead" }, "Утверждённая медицинская терминология. Совпадения автоматически подсказываются в редакторе сегментов.")),

    React.createElement(AutoApprovePanel, { store, toast, onDone: () => setQueueVersion(v => v + 1) }),
    React.createElement(GlossaryAuditPanel, { store, toast, onDone: () => setQueueVersion(v => v + 1) }),
    React.createElement(GlossaryPurgePanel, { store, toast, onDone: () => setQueueVersion(v => v + 1) }),

    React.createElement(TermQueue, { store, toast, version: queueVersion }),

    React.createElement("div", { className: "row between row-wrap", style: { marginBottom: 16, gap: 12 } },
      React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value),
        placeholder: scope === "src" ? "Поиск по термину (RU)…" : scope === "tgt" ? "Поиск по переводу (EN)…" : "Поиск по глоссарию…" }),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(ScopeSelect, { value: scope, onChange: (e) => setScope(e.target.value) }),
        React.createElement(Select, { value: cat, onChange: (e) => setCat(e.target.value), style: { width: "auto" } },
          cats.map(c => React.createElement("option", { key: c, value: c }, c === "all" ? "Все категории" : c))),
        React.createElement(Select, { value: sort, onChange: (e) => setSort(e.target.value), style: { width: "auto" } },
          React.createElement("option", { value: "freq" }, "По частоте"),
          React.createElement("option", { value: "alpha" }, "По алфавиту")),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "download" }, "TSV"),
        React.createElement(Btn, { variant: "primary", size: "sm", icon: "plus", onClick: () => setModal("add") }, "Термин")
      )
    ),

    React.createElement("div", { className: "table-wrap" },
      React.createElement("div", { className: "tbl-scroll" },
        React.createElement("table", { className: "tbl" },
          React.createElement("thead", null, React.createElement("tr", null,
            React.createElement("th", null, "Термин (RU)"), React.createElement("th", null, "Перевод (EN)"),
            React.createElement("th", { style: { width: 150 } }, "Категория", React.createElement(InfoTip, { title: "Категория", body: "Anatomy (анатомия), Dosage (дозировки), Disease (заболевания), Device (медтехника), Procedure (процедуры) и др." })),
            React.createElement("th", { style: { width: 120 } }, "Частота", React.createElement(InfoTip, { title: "Частота", body: "Сколько раз термин встречался в проектах." })),
            React.createElement("th", { style: { width: 150 } }, "Достоверность", React.createElement(InfoTip, { title: "Уверенность", body: "High — проверен экспертом, Medium — авто-извлечён, Low — требует проверки." })), React.createElement("th", { style: { width: 96 } }, ""))),
          React.createElement("tbody", null,
            pageRows.map((g, i) => { const [cls, lab] = confMeta[(g.conf || "").toLowerCase()] || confMeta.medium;
              return React.createElement("tr", { key: i, onClick: () => setModal(g) },
                React.createElement("td", { style: { fontWeight: 600 } },
                  React.createElement("button", {
                    className: "linklike", onClick: (e) => openUsage(g, e),
                    title: "Показать сегменты, где встречается этот термин" }, g.src)),
                React.createElement("td", { style: { color: "var(--c-primary)", fontWeight: 500 } }, g.tgt,
                  // auto = массовый автоимпорт: модель получает такую запись подсказкой, а не правилом
                  g.tier === "auto" && React.createElement("span", { className: "dim", style: { fontSize: 11, marginLeft: 8, whiteSpace: "nowrap" },
                    title: "Автоимпорт, не проверено человеком. В промпт уходит подсказкой, а не жёстким правилом." }, "авто")),
                React.createElement("td", null, React.createElement(Badge, { variant: "soft" }, g.cat)),
                React.createElement("td", { className: "tnum dim" }, g.freq + "×"),
                React.createElement("td", null, React.createElement("span", { className: "badge " + cls }, lab)),
                React.createElement("td", { onClick: (e) => e.stopPropagation() },
                  React.createElement("div", { className: "row", style: { gap: 2 } },
                    React.createElement(IconBtn, { icon: "edit", label: "Редактировать", sm: true, onClick: () => setModal(g) }),
                    React.createElement(IconBtn, { icon: "trash", label: "Удалить", sm: true, onClick: () => del(g) }))));
            })
          )
        )
      )
    ),
    React.createElement("div", { className: "row between", style: { marginTop: 12 } },
      React.createElement("span", { className: "dim", style: { fontSize: 13 } },
        loaded ? ("Показано " + pageRows.length + " из " + rows.length + " (всего " + allTerms.length + ")") : "Загрузка…"),
      totalPages > 1 && React.createElement("div", { className: "row", style: { gap: 6 } },
        React.createElement(Btn, { variant: "ghost", size: "sm", disabled: page === 0, onClick: () => setPage(p => p - 1) }, "←"),
        React.createElement("span", { className: "dim", style: { fontSize: 13, padding: "0 4px" } }, (page + 1) + " / " + totalPages),
        React.createElement(Btn, { variant: "ghost", size: "sm", disabled: page >= totalPages - 1, onClick: () => setPage(p => p + 1) }, "→")
      )
    ),

    modal && React.createElement(TermModal, { term: modal === "add" ? null : modal,
      scope: store.activeProject
        ? { lang: store.activeProject.src + "→" + store.activeProject.tgt,
            domain: store.activeProject.domain || "medical" }
        : null,
      onClose: () => setModal(null), onSave: save })
  );
}

// Примеры употребления прямо в карточке: без них правка термина делается вслепую.
// Предпросмотр — механическая замена старого варианта на новый в готовом переводе,
// поэтому подписан именно как предпросмотр, а не как перевод.
function TermUsage({ src, oldTgt, newTgt, lang, domain }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let dead = false;
    if (!src || !window.API) { setData({ total: 0, examples: [] }); return; }
    window.API.safeCall(() => window.API.glossaryUsage(src, 4, lang, domain)).then(r => {
      if (!dead) setData(r || { total: 0, examples: [] });
    });
    return () => { dead = true; };
  }, [src]);

  if (!data) return React.createElement("div", { className: "row", style: { gap: 8 } },
    React.createElement(Spinner, null),
    React.createElement("span", { className: "dim", style: { fontSize: 13 } }, "Ищем примеры…"));
  if (!data.total) return React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } },
    "В переведённых сегментах этот термин пока не встречается.");

  const replaced = (text) => {
    if (!oldTgt || !newTgt || oldTgt === newTgt) return null;
    const i = (text || "").toLowerCase().indexOf(oldTgt.toLowerCase());
    if (i === -1) return null;
    return text.slice(0, i) + newTgt + text.slice(i + oldTgt.length);
  };

  return React.createElement("div", { className: "col", style: { gap: 10 } },
    React.createElement("div", { className: "dim", style: { fontSize: 12.5 } },
      "Встречается в " + data.total + " сегм."
      + (data.violatingTotal ? " · перевод расходится с глоссарием: " + data.violatingTotal : "")),
    data.examples.map((ex, i) => {
      const preview = replaced(ex.target);
      return React.createElement("div", { key: i, className: "card", style: { padding: "9px 11px", background: "var(--bg-sunken)", display: "flex", flexDirection: "column", gap: 4 } },
        React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
          "#" + ex.id + " · " + (ex.projectTitle || "проект " + ex.project)),
        React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5 } }, ex.source),
        ex.target
          ? React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5, color: "var(--c-primary)" } }, ex.target)
          : React.createElement("div", { className: "dim", style: { fontSize: 12.5, fontStyle: "italic" } }, "— не переведено —"),
        preview && React.createElement("div", { style: { fontSize: 13, lineHeight: 1.5, color: "var(--c-success)" } },
          "→ " + preview),
        ex.target && !preview && oldTgt !== newTgt && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
          "прежний вариант «" + oldTgt + "» в этом переводе не найден — сегмент нужно переперевести"));
    })
  );
}

function TermModal({ term, onClose, onSave, scope }) {
  const [src, setSrc] = useState(term ? term.src : "");
  const [tgt, setTgt] = useState(term ? term.tgt : "");
  const [cat, setCat] = useState(term ? term.cat : "Term");
  const [note, setNote] = useState(term ? term.note : "");
  const [conf, setConf] = useState(term ? term.conf : "high");
  const cats = ["Term", "Anatomy", "Cardiology", "Disease", "Dosage", "Symptom", "Lab", "Vitals", "Regulatory", "Document", "Device"];
  return React.createElement(Modal, {
    title: term ? "Редактировать термин" : "Новый термин", icon: "book", onClose,
    footer: React.createElement(React.Fragment, null,
      React.createElement(Btn, { variant: "ghost", onClick: onClose }, "Отмена"),
      React.createElement(Btn, { variant: "primary", icon: "check", disabled: !src || !tgt,
        /* lang/domain протаскиваем от исходной записи: без них сервер не нашёл бы
           её в своей области и завёл бы рядом дубль, а старый перевод остался бы жить. */
        /* Новая запись заводится в области открытого проекта, у правки область
           берётся от самой записи: иначе термин, добавленный в RU→DE проекте,
           лёг бы в область по умолчанию и не нашёлся бы при переводе. */
        onClick: () => onSave({ src, tgt, cat, note, conf, freq: term ? term.freq : 1,
                                lang: term ? term.lang : (scope || {}).lang || null,
                                domain: term ? term.domain : (scope || {}).domain || null }, !term) }, "Сохранить"))
  },
    React.createElement("div", { className: "grid grid-2" },
      React.createElement(Field, { label: "Термин (русский)" }, React.createElement(Input, { value: src, onChange: (e) => setSrc(e.target.value), placeholder: "напр. стеноз" })),
      React.createElement(Field, { label: "Перевод (английский)" }, React.createElement(Input, { value: tgt, onChange: (e) => setTgt(e.target.value), placeholder: "e.g. stenosis" }))),
    React.createElement(Field, { label: "Область записи",
      hint: "Пара языков и тематика, в которых запись видна при переводе" },
      React.createElement("div", { className: "dim", style: { fontSize: 13 } },
        (term ? (term.lang || "RU→EN") : ((scope || {}).lang || "RU→EN")) + " · " +
        (term ? (term.domain || "medical") : ((scope || {}).domain || "medical")))),
    React.createElement(Field, { label: "Категория" },
      React.createElement(Select, { value: cat, onChange: (e) => setCat(e.target.value) }, cats.map(c => React.createElement("option", { key: c, value: c }, c)))),
    React.createElement(Field, { label: "Примечание (необязательно)" },
      React.createElement(Textarea, { value: note, onChange: (e) => setNote(e.target.value), placeholder: "Контекст использования, предпочтительные варианты…", style: { minHeight: 70 } })),
    term && term.src && React.createElement(Field, { label: "Где используется",
      hint: "Зелёным — как будет выглядеть перевод после замены" },
      React.createElement(TermUsage, { src: term.src, oldTgt: (term.tgt || ""), newTgt: tgt,
        lang: term.lang, domain: term.domain })),
    React.createElement(Field, { label: "Достоверность" },
      React.createElement("div", { className: "row", style: { gap: 18 } },
        ["high", "medium", "low"].map(c => React.createElement(Radio, { key: c, name: "conf", checked: conf === c, onChange: () => setConf(c) },
          { high: "Высокая", medium: "Средняя", low: "Низкая" }[c]))))
  );
}
window.TabGlossary = TabGlossary;
window.TabKnowledge = TabKnowledge;

/* ============================================================
   Tab: TM — translation memory
   ============================================================ */
function TabTM({ store, toast }) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [quality, setQuality] = useState("all");
  const tmQuality = (t) => t.quality || (t.verified === true ? "verified" : t.verified === false ? "draft" : "draft");
  const rows = store.tm.filter(t => {
    const q2 = tmQuality(t);
    if (quality !== "all" && q2 !== quality) return false;
    if (query && !pairMatches(t, query, scope)) return false;
    return true;
  });
  return React.createElement("div", { className: "page page-wide" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Память переводов",
        React.createElement(InfoTip, { title: "Память переводов (TM)", body: "База подтверждённых пар (оригинал → перевод). Используется для поиска точных и нечётких совпадений в новых проектах. Экономит токены." })),
      React.createElement("p", { className: "lead" }, "Подтверждённые пары из предыдущих проектов. Точные совпадения подставляются автоматически и не тарифицируются.")),
    React.createElement("div", { className: "row between row-wrap", style: { marginBottom: 18, gap: 12 } },
      React.createElement(SearchInput, { value: query, onChange: (e) => setQuery(e.target.value),
        placeholder: scope === "src" ? "Поиск по оригиналу (RU)…" : scope === "tgt" ? "Поиск по переводу (EN)…" : "Поиск в памяти переводов…" }),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(ScopeSelect, { value: scope, onChange: (e) => setScope(e.target.value) }),
        React.createElement(Select, { value: quality, onChange: (e) => setQuality(e.target.value), style: { width: "auto" } },
          React.createElement("option", { value: "all" }, "Любое качество"),
          React.createElement("option", { value: "verified" }, "Проверенные"),
          React.createElement("option", { value: "draft" }, "Черновые")),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "upload" }, "Импорт TMX"),
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "download" }, "Экспорт TMX"))),
    React.createElement("div", { className: "grid grid-2" },
      rows.map((t, i) => React.createElement("div", { key: i, className: "card card-pad card-hover", style: { display: "flex", flexDirection: "column", gap: 12 } },
        React.createElement("div", { className: "row between" },
          tmQuality(t) === "verified"
            ? React.createElement(Badge, { variant: "confirmed", icon: "checkCircle" }, "Проверено")
            : React.createElement(Badge, { variant: "review", icon: "warn" }, "Черновик"),
          React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "Использовано " + t.used + "×")),
        React.createElement("div", { style: { fontSize: 14, lineHeight: 1.5 } }, t.src),
        React.createElement("div", { className: "divider", style: { margin: "0" } }),
        React.createElement("div", { style: { fontSize: 14, lineHeight: 1.5, color: "var(--c-primary)" } }, t.tgt),
        React.createElement("div", { className: "row between", style: { marginTop: 2 } },
          React.createElement("span", { className: "dim", style: { fontSize: 12 } }, "Создано " + t.created),
          React.createElement("div", { className: "row", style: { gap: 2 } },
            React.createElement(IconBtn, { icon: "copy", label: "Копировать", sm: true, onClick: () => { navigator.clipboard && navigator.clipboard.writeText(t.tgt); toast.info("Скопировано"); } }),
            React.createElement(IconBtn, { icon: "edit", label: "Редактировать", sm: true }),
            React.createElement(IconBtn, { icon: "trash", label: "Удалить", sm: true, onClick: () => { store.deleteTM(t); toast.warning("Запись удалена"); } })))
      ))
    )
  );
}
window.TabTM = TabTM;
