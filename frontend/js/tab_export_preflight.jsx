/* ── Текст, впечатанный в картинки ───────────────────────────────────
   Часть текста учебника живёт только в картинках: подписи под рисунками,
   схемы, куски отсканированных страниц. Абзацного якоря у него нет, поэтому
   до разбора он не переводится вовсе и в выгрузке «1в1» остаётся на языке
   оригинала.

   Карточка не прячется, когда находок ноль: пропавшее с экрана выглядит
   благополучнее, чем есть, а ноль здесь бывает и настоящим (в документе
   действительно нет надписей), и следствием того, что разбор не запускали. */
/* Ключ выбора модели чтения. Выбор глобальный, как у остальных шагов:
   человек решает, чем читать, а не проект. */
const OCR_MODEL_LS_KEY = "mct-ocr-model";

function ImagesCard({ project, store, toast }) {
  const pid = project.id;
  const [models, setModels] = useState([]);      // каталог с ценами из /api/models
  const [ocrModel, setOcrModel] = useState(() => {
    try { return localStorage.getItem(OCR_MODEL_LS_KEY) || ""; } catch (e) { return ""; }
  });
  const [rep, setRep] = useState(null);
  const [asked, setAsked] = useState(false);   // спрашивали ли сервер вообще
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const [forgetOpen, setForgetOpen] = useState(false);
  /* Что именно отсеяно. Без списка «Отсеяно: 230» — число, которое человеку
     нечем проверить, а отсев делает модель и ошибается в обе стороны. */
  const [drop, setDrop] = useState(null);        // {kind, pid, rows, total} | null
  const [dropBusy, setDropBusy] = useState(false);
  /* Кусок картинки по каждой строке списка — по требованию, а не сразу:
     надписей бывает под три сотни. Решать по голой строке текста нельзя,
     ровно за этим кроп и заведён. */
  const [crops, setCrops] = useState({});

  /* Ответ принимается, только если он про ТОТ ЖЕ проект. Экран не
     размонтируется при переключении, и без этой сверки числа проекта A
     рисуются в карточке проекта B — вместе с кнопками, которые работают
     уже с B. */
  const load = async (want) => {
    if (!window.API || !window.API.imagesReport) return;
    const r = await window.API.safeCall(() => window.API.imagesReport(want));
    setAsked(true);
    if (want !== pid) return;
    setRep(r || null);
  };
  useEffect(() => {
    setRep(null); setJob(null); setAsked(false); setForgetOpen(false);
    setDrop(null);
    setCrops(m => { dropCrops(m); return {}; });
    load(pid);
  }, [pid]);

  /* Каталог моделей и цены берём с сервера. Цифра в .jsx была бы вторым
     прайс-листом рядом с настоящим — тем самым, который однажды разойдётся
     с тем, по которому списывают. */
  useEffect(() => {
    if (!window.API || !window.API.models) return;
    window.API.safeCall(() => window.API.models()).then(d => {
      if (!d || !d.models) return;
      setModels(d.models);
      setOcrModel(cur => (cur && d.models.some(m => m.id === cur)) ? cur : "");
    });
  }, []);

  /* Опрос идёт, только пока задача жива. Задача живёт в памяти процесса:
     рестарт сервиса или вытеснение историей — и её больше нет. Без разбора
     этого случая карточка навсегда оставалась бы со спиннером, а кнопки
     запуска (они скрыты, пока идёт работа) — недоступны до перезагрузки
     страницы. */
  useEffect(() => {
    if (!job || !window.API) return;
    let dead = false;
    const tick = async () => {
      const res = await window.API.safeCall(() => window.API.listJobs(pid));
      if (dead || !res) return;
      const live = (res.active || []).find(x => x.id === job.id);
      if (live) { setJob(live); return; }
      setJob(null);
      load(pid);
      const done = (res.jobs || []).find(x => x.id === job.id);
      if (!done) {
        toast.warning("Разбор картинок пропал из очереди",
          "Сервис мог перезапуститься. Сделанное сохранено — посмотрите числа "
          + "ниже и при необходимости запустите заново.");
        return;
      }
      const c = done.counters || {};
      if (done.status === "error") toast.error("Разбор картинок прерван", done.error || "");
      else toast.success(done.status === "stopped" ? "Разбор остановлен" : "Разбор картинок закончен",
        "картинок: " + (done.done || 0) + " из " + (done.total || 0)
        + " · надписей всего: " + (c.blocks || 0)
        + (c.segments ? " · сегментов заведено: " + c.segments : "")
        + (c.readFailed ? " · не прочитано вызовов: " + c.readFailed : "")
        + (c.unreadable ? " · картинки не читаются: " + c.unreadable : ""));
      /* Сегменты завела задача НА СЕРВЕРЕ. Не подтянув их, карточка
         отчитывается о работе, которой на экране нет: редактор тянет проект
         один раз при старте. */
      if (c.segments && store && store.replaceProjectSegments) {
        const fresh = await window.API.safeCall(() => window.API.getProject(pid));
        if (!dead && fresh && fresh.segments) store.replaceProjectSegments(pid, fresh.segments);
      }
    };
    const t = setInterval(tick, 2500);
    return () => { dead = true; clearInterval(t); };
  }, [job && job.id, pid]);

  const start = async (dry) => {
    if (!window.API) return;
    setBusy(true);
    /* Смету отдаём серверу вместе с задачей: без неё факт не с чем сравнить,
       и поправка estRatio прогоны картинок не увидит никогда. */
    const r = await window.API.safeCall(() => window.API.createJob(pid, "images", [],
      { dry_run: !!dry, ocr_model: ocrModel || null, est_cost: est || 0 }));
    setBusy(false);
    if (!r || !r.ok) { toast.error("Разбор не запущен", "Сервер отказал."); return; }
    setJob(r.job);
    toast.info(dry ? "Ищем надписи" : "Читаем надписи",
      "Работа идёт на сервере — вкладку можно закрыть.");
  };
  const forget = async (wipe) => {
    setForgetOpen(false);
    closeDrop();          // список ссылается на привязку, которой сейчас не станет
    setBusy(true);
    const r = await window.API.safeCall(() => window.API.imagesForget(pid, true, wipe));
    setBusy(false);
    if (!r) { toast.error("Не удалось", "Сервер недоступен или идёт разбор."); return; }
    load(pid);
    if (store && store.replaceProjectSegments) {
      const fresh = await window.API.safeCall(() => window.API.getProject(pid));
      if (fresh && fresh.segments) store.replaceProjectSegments(pid, fresh.segments);
    }
    toast.success("Готово", "сегментов убрано: " + r.removed
      + (r.wiped ? " · прочитанный текст забыт" : " · прочитанное сохранено, повторный заход бесплатный"));
  };

  const loadBlocks = async (kind, want) => {
    const forPid = want == null ? pid : want;
    if (!window.API || !window.API.imagesBlocks) {
      toast.error("Список не показать", "Связь с сервером недоступна.");
      return;
    }
    setDropBusy(true);
    const r = await window.API.safeCall(() => window.API.imagesBlocks(forPid, kind));
    setDropBusy(false);
    /* Ответ по ЧУЖОМУ проекту не применяем: экран при переключении
       не размонтируется, а кнопки в строках работают уже с новым проектом —
       и «вернуть» вернуло бы чужую надпись, на которую человек не смотрел. */
    if (forPid !== pid) return;
    if (!r || !r.blocks) {
      toast.error("Список не показать", "Сервер не ответил.");
      return;
    }
    setDrop({ kind, pid: forPid, rows: r.blocks, total: r.total });
  };
  const openBlocks = (kind) => {
    if (drop && drop.kind === kind) { setDrop(null); return; }
    loadBlocks(kind);
  };
  const restore = async (b) => {
    if (!drop || drop.pid !== pid) { setDrop(null); return; }
    const forPid = pid, kind = drop.kind;
    setDropBusy(true);
    let r = null, why = "";
    try { r = await window.API.imageRestore(forPid, b.part, b.block); }
    catch (e) { why = (e && e.message) || ""; }
    setDropBusy(false);
    if (!r || !r.ok) {
      // Причину называем ту, что вернул сервер: «сервер отказал» одинаково
      // звучит и для идущего разбора, и для отвязанного исходника.
      toast.error("Не удалось вернуть", why || "Сервер не ответил.");
      return;
    }
    load(forPid);
    /* Список перечитываем, только если он ещё открыт: человек мог закрыть
       панель, и открывать её обратно за него незачем. Проект целиком отсюда
       НЕ тянем — 5 МБ ради одного сегмента; редактор подтянет его сам, он
       теперь сверяет число сегментов с сервером. */
    if (drop) loadBlocks(kind, forPid);
    toast.success("Возвращено в работу",
      "сегмент #" + r.segment + " — теперь его надо перевести");
  };

  const dropCrops = (map) => {
    Object.keys(map || {}).forEach(k => { if (map[k]) URL.revokeObjectURL(map[k]); });
  };
  const closeDrop = () => { setDrop(null); setCrops(m => { dropCrops(m); return {}; }); };
  const toggleCrop = async (b) => {
    const key = b.part + ":" + b.block;
    if (crops[key]) {
      setCrops(m => { if (m[key]) URL.revokeObjectURL(m[key]); const n = { ...m }; delete n[key]; return n; });
      return;
    }
    if (!window.API || !window.API.imageCropUrl) return;
    const url = await window.API.imageCropUrl(pid, { part: b.part, block: b.block });
    if (!url) { toast.error("Кусок картинки не пришёл", "Проверить надпись глазами не выйдет."); return; }
    setCrops(m => ({ ...m, [key]: url }));
  };

  const st = (rep && rep.stats) || null;
  const running = !!job;
  /* Пустой выбор означает «как решил сервер»: подставлять сюда что-то своё
     значит спорить с настройкой, которой человек не касался. */
  const useModel = ocrModel || (rep && rep.model) || "";
  const estOf = (id) => (rep && rep.est && rep.est[id] != null) ? rep.est[id] : null;
  const est = estOf(useModel);
  const mInfo = models.find(m => m.id === useModel) || null;
  const pickModel = (id) => {
    setOcrModel(id);
    try { localStorage.setItem(OCR_MODEL_LS_KEY, id); } catch (e) {}
  };
  const row = (label, value, color, tip, onClick) => React.createElement("div", { className: "row between", key: label },
    React.createElement("span", { className: "row muted", style: { gap: 6 } }, label,
      tip && React.createElement(InfoTip, { title: label, body: tip, size: 13 })),
    React.createElement("strong", {
      onClick: onClick || undefined,
      title: onClick ? "Показать список" : undefined,
      style: Object.assign({}, color ? { color } : null,
        onClick ? { cursor: "pointer", textDecoration: "underline dotted" } : null) },
      value));

  return React.createElement("div", null,
    React.createElement("h2", { className: "section-title" }, "Текст на картинках"),
    React.createElement("div", { className: "card card-pad col", style: { gap: 12 } },
      React.createElement("div", { style: { fontSize: 13, lineHeight: 1.55 } },
        "Подписи под рисунками и схемы впечатаны в картинки: абзаца у них нет, ",
        "и без разбора они остаются на языке оригинала. Найденные надписи становятся ",
        "обычными сегментами проекта, а при экспорте 1в1 перевод возвращается ",
        "в саму картинку — там, где фон однороден. Где нельзя (снимок, фотография), ",
        "перевод уходит подписью под картинкой: заплатка поверх рентгенограммы ",
        "испортила бы документ."),

      !project.sourceDocx && React.createElement("div", { className: "hint" },
        "Сначала приложите исходный .docx — искать надписи не в чем."),

      rep && !rep.engine && React.createElement("div", { className: "hint", style: { color: "var(--c-warning)" } },
        "Движок поиска строк недоступен: " + (rep.why || "причина не названа")
        + ". Это «не знаю», а не «надписей нет»."),

      /* «Не спросили» и «нет находок» — разные вещи, и вторым нельзя
         называть первое. */
      !asked && project.sourceDocx && React.createElement("div", { className: "hint" },
        "Спрашиваем сервер, что известно про картинки…"),
      !rep && asked && project.sourceDocx && React.createElement("div", { className: "hint", style: { color: "var(--c-warning)" } },
        "Сервер не ответил про картинки — что там, сейчас неизвестно."),
      !st && rep && project.sourceDocx && React.createElement("div", { className: "hint" },
        "Разбор ещё не делался."),

      st && React.createElement(React.Fragment, null,
        row("Картинок в документе", st.images),
        row("Разобрано", st.scanned),
        row("С надписями", st.withText),
        row("Надписей найдено", st.blocks),
        st.segments > 0 && row("Стали сегментами", st.segments, "var(--c-success)"),
        st.text > 0 && row("Вернём в картинку при экспорте", st.repaintable, null,
          "У этих надписей под текстом однородный фон, поэтому при экспорте «1в1» "
          + "перевод впишется В САМУ картинку, на место оригинала: исходную надпись "
          + "стираем цветом её же фона и пишем поверх. Это число — сколько надписей "
          + "проходят проверку фона; в файл попадут те из них, что переведены "
          + "и влезают читаемым кеглем (английский длиннее русского, и в тесную "
          + "рамку он иногда не помещается). Что не вышло — названо числом "
          + "в отчёте после выгрузки."),
        st.captioned > 0 && row("Уйдут подписью под картинкой", st.captioned, "var(--c-warning)",
          "Здесь фон пёстрый (рентгенограмма, фотография) либо перевод не влезает "
          + "читаемым кеглем. Стирать надпись значит положить на снимок прямоугольную "
          + "заплатку — это порча документа. Поэтому картинка остаётся нетронутой, "
          + "а перевод встаёт отдельным абзацем сразу под ней."),
        st.overlay > 0 && row("Отсеяно: надпечатка аппарата", st.overlay, null,
          "Надписи, которые сделал не автор книги, а прибор или программа: фамилии "
          + "пациентов и врачей, даты исследования, настройки томографа, линейки "
          + "и пункты меню. Это не текст документа — переводить его незачем, "
          + "а фамилиям нечего делать в памяти переводов. Метку ставит модель "
          + "при чтении, согласие между картинками или вы сами — в списке видно, "
          + "кто именно. Нажмите на число, чтобы увидеть список, посмотреть кусок "
          + "картинки и вернуть ошибочно отсеянное.",
          () => openBlocks("overlay")),
        st.noise > 0 && row("Отсеяно: шум", st.noise, null,
          "Строки, в которых переводить нечего: одиночные буквы («а», «б», «L»), "
          + "даты, номера кадров, показания приборов вроде «250MA». Правило простое "
          + "и языконезависимое: меньше трёх букв.",
          () => openBlocks("noise")),
        st.unread > 0 && row("Не прочитано", st.unread, "var(--c-warning)"),
        st.unreadable > 0 && row("Картинки не читаются", st.unreadable, "var(--c-warning)")),

      drop && React.createElement("div", { className: "col", style: { gap: 6, padding: "8px 10px", background: "var(--bg-sunken)", borderRadius: 8 } },
        React.createElement("div", { className: "row between" },
          React.createElement("span", { style: { fontSize: 12.5, fontWeight: 600 } },
            (drop.kind === "overlay" ? "Отсеяно как надпечатка аппарата: " : "Отсеяно как шум: ")
            + drop.rows.length + (drop.total > drop.rows.length ? " из " + drop.total : "")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: closeDrop }, "Закрыть")),
        React.createElement("div", { className: "col", style: { gap: 6, maxHeight: 300, overflowY: "auto" } },
          drop.rows.map((b) => React.createElement("div", { key: b.part + ":" + b.block, className: "col", style: { gap: 3 } },
            React.createElement("div", { className: "row between", style: { gap: 8 } },
              React.createElement("span", {
                onClick: () => toggleCrop(b), title: "Показать кусок картинки",
                style: { fontSize: 12, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                         whiteSpace: "nowrap", cursor: "pointer", textDecoration: "underline dotted" } },
                b.text || "— (модель не прочитала)"),
              React.createElement("span", { className: "row", style: { gap: 6, flexShrink: 0 } },
                /* Метку ставят трое, и своё решение человек обязан узнавать:
                   иначе он найдёт свои же пометки в списке «отсеяла модель»
                   и будет разбирать их заново. */
                b.by && b.by !== "model" && React.createElement("span", { className: "dim", style: { fontSize: 11 } },
                  b.by === "human" ? "ваше решение" : "по согласию картинок"),
                (b.text || "").trim() && React.createElement(Btn, { variant: "ghost", size: "sm", disabled: dropBusy,
                  onClick: () => restore(b) }, "Это текст документа"))),
            crops[b.part + ":" + b.block] && React.createElement("img", {
              src: crops[b.part + ":" + b.block], alt: "Надпись на картинке",
              style: { maxWidth: "100%", borderRadius: 4, display: "block" } })))),
        React.createElement("div", { className: "dim", style: { fontSize: 11.5 } },
          "Нажмите на строку — покажем кусок картинки. Вернуть можно любую надпись: "
          + "отсев делает модель, и ошибается она в обе стороны.")),

      running && React.createElement("div", { className: "col", style: { gap: 8 } },
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement(Spinner, null),
          React.createElement("span", { style: { fontSize: 13 } },
            "картинка " + (job.done || 0) + " из " + (job.total || 0))),
        React.createElement(Btn, { variant: "secondary", size: "sm",
          onClick: () => window.API.safeCall(() => window.API.stopJob(job.id)) },
          "Остановить")),

      /* Чем читать — решается ЗДЕСЬ, рядом с кнопкой, и с ценой этого самого
         разбора: цена за миллион токенов ничего не говорит человеку о том,
         во что обойдётся вот эта книга. */
      !running && project.sourceDocx && !forgetOpen && React.createElement("div", { className: "col", style: { gap: 6 } },
        React.createElement("div", { className: "row between", style: { gap: 10 } },
          React.createElement("span", { className: "muted", style: { fontSize: 13 } }, "Модель чтения"),
          React.createElement(Select, {
            value: useModel, style: { width: 260 },
            onChange: (e) => pickModel(e.target.value) },
            models.map(m => React.createElement("option", { key: m.id, value: m.id },
              m.label + (estOf(m.id) ? " — ~$" + estOf(m.id).toFixed(2) : ""))))),
        mInfo && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
          "цена модели: вход $" + mInfo.in + " · выход $" + mInfo.out + " за 1М токенов"
          + (rep && rep.estTokens && rep.estTokens.in
              ? " · в этом разборе ≈ " + Math.round(rep.estTokens.in / 1000) + "К входных" : "")),
        !models.length && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
          "каталог моделей не загрузился — читать будет модель по умолчанию")),

      !running && project.sourceDocx && !forgetOpen
        && React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "search",
          disabled: busy, onClick: () => start(true) }, "Найти надписи"),
        /* Кнопку включает ОСТАТОК РАБОТЫ, а не смета. Смета обнуляется, как
           только всё прочитано, — но после сноса сегментов работа остаётся
           (завести их заново), и по смете кнопка гасла навсегда. */
        React.createElement(Btn, { variant: "primary", size: "sm", icon: "sparkles",
          disabled: busy || !st || !st.pending, onClick: () => start(false) },
          "Прочитать и завести сегменты" + (est ? " (~$" + est.toFixed(2) + ")" : "")),
        st && st.segments > 0 && React.createElement(Btn, { variant: "ghost", size: "sm",
          disabled: busy, onClick: () => setForgetOpen(true) }, "Забыть распознанное")),

      /* Отката у этой команды нет, поэтому спрашиваем до, а не рассказываем
         после. Два разных действия и разная цена: сегменты заводятся заново
         бесплатно, прочитанный текст — за деньги. */
      forgetOpen && React.createElement("div", { className: "col", style: { gap: 8 } },
        React.createElement("div", { style: { fontSize: 13 } },
          "Убрать сегменты, заведённые из картинок? Сегменты с готовым переводом "
          + "останутся. Отката у этого действия нет."),
        React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
          React.createElement(Btn, { variant: "secondary", size: "sm", disabled: busy,
            onClick: () => forget(false) }, "Убрать сегменты"),
          React.createElement(Btn, { variant: "danger", size: "sm", disabled: busy,
            onClick: () => forget(true) }, "Убрать и забыть прочитанное"),
          React.createElement(Btn, { variant: "ghost", size: "sm",
            onClick: () => setForgetOpen(false) }, "Отмена"))),

      rep && rep.at && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        "разбор: " + rep.at + " · по умолчанию: " + (rep.model || "")
        + ((rep.skipped && rep.skipped.length)
            ? " · нерастровых картинок пропущено: " + rep.skipped.length : ""))));
}
window.ImagesCard = ImagesCard;

/* ============================================================
   Tab: Export — download translated document
   ============================================================ */
function TabExport({ store, toast }) {
  const project = store.activeProject;
  /* Формат по умолчанию решает приложенный исходник. Приложить его и значит
     попросить документ «как оригинал» — другого смысла у этого действия нет.
     Оставленный на «новом файле» переключатель молча собирал документ с нуля:
     человек прикладывал 21 МБ исходника и получал голый текст без оформления,
     причём отличить это можно было, только открыв файл. */
  const [fmt, setFmt] = useState(
    () => (store.activeProject && store.activeProject.sourceDocx) ? "docx_layout" : "docx");
  const [opts, setOpts] = useState({ source: true, notes: true, qa: false, glossary: true });
  const [busy, setBusy] = useState(false);
  const [attaching, setAttaching] = useState(false);
  const fileRef = React.useRef(null);
  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));

  /* Исходник проекта. Есть он или нет — единственное, что решает, доступен ли
     экспорт 1в1: собрать оформление из сегментов нельзя, в них нет ни шрифта,
     ни картинок. Проекты, импортированные до появления этого формата, файла
     не сохранили, поэтому его прикладывают здесь же. */
  const srcDoc = project.sourceDocx || null;
  const doAttach = async (file, force) => {
    if (!file || !window.API) return;
    setAttaching(true);
    const res = await window.API.safeCall(() => window.API.attachSource(project.id, file, force));
    setAttaching(false);
    if (fileRef.current) fileRef.current.value = "";
    if (!res) { toast.error("Файл не приложен", "Сервер недоступен."); return; }
    const st = res.stats || {};
    if (!res.ok) {
      // Не тот файл виден по числу совпадений, и молчать об этом нельзя:
      // экспорт расставил бы переводы по чужим абзацам.
      toast.error("Файл не приложен", res.error || "Сервер отказал.");
      return;
    }
    // Точечная правка проекта в сторе, а не перезагрузка: проект на 2670
    // сегментов весит 5 МБ, и тянуть его ради одной отметки незачем.
    if (store.patchProject) store.patchProject(project.id, { sourceDocx: res.sourceDocx });
    // Исходник прикладывают ради 1в1 — переключаем формат сами, а не ждём,
    // что человек заметит радиокнопку выше.
    setFmt("docx_layout");
    toast.success("Исходник приложен",
      "Абзацев: " + st.paras + " · сегментов совпало: " + st.matched + " из " + st.segments
        + (st.unmatched ? " · без пары: " + st.unmatched + " (останутся на языке оригинала)" : ""));
  };

  const toggle = (k) => setOpts(o => ({ ...o, [k]: !o[k] }));
  /* Единственное условие попадания в файл — непустой перевод. Ни статус,
     ни подтверждение человеком роли не играют: экспорт не судит о качестве,
     он выгружает то, что есть. Показываем это числом, потому что рядом стоит
     «Подтверждено», и без второй строки оно читается как условие. */
  const translated = project.segments.filter(s => (s.target || "").trim()).length;
  const untranslated = project.segments.length - translated;
  const fmtLabel = fmt === "docx_layout" ? "DOCX 1в1" : fmt.toUpperCase();
  const doExport = async () => {
    setBusy(true);
    let result = null;
    if (window.API) result = await window.API.safeCall(() => window.API.exportProject(project.id, fmt, opts.source));
    setBusy(false);
    if (result && result.ok && result.url) {
      // Реальное скачивание: бэкенд собирает файл и отдаёт по result.url
      const a = document.createElement("a");
      a.href = window.API.downloadUrl(result.url);
      a.download = result.file || (project.title + "." + fmt);
      document.body.appendChild(a);
      a.click();
      a.remove();
      if (store.setExportHistory) {
        store.setExportHistory(h => [{ file: result.file, when: new Date().toISOString().slice(0,16).replace("T"," "), size: result.size || "" }, ...h]);
      }
      const st = result.stats || {};
      // Про 1в1 говорим не «готово», а что именно легло в файл: сколько абзацев
      // переведено, сколько осталось на языке оригинала и в скольких границу
      // выделения пришлось ставить по доле длины, а не по знаку препинания.
      // Без этих цифр человек узнаёт о пропусках, только пролистав документ
      // до конца.
      // Про картинки говорим тем же порядком: что вписали внутрь, что ушло
      // подписью и что не попало никуда. Счётчик, посчитанный и не показанный,
      // ничем не лучше несчитанного.
      const imgLost = (st.img_lost || 0) + (st.img_stale || 0) + (st.img_noseg || 0);
      toast.success("Файл готов", st.written != null
        ? (result.file + " · переведено абзацев: " + st.written
           + (st.untranslated ? " · без перевода: " + st.untranslated : "")
           + (st.inline ? " · выделений перенесено: " + st.inline : "")
           + (st.approx ? " (из них приблизительно: " + st.approx + ")" : "")
           + (st.img_repainted ? " · надписей вписано в картинки: " + st.img_repainted : "")
           + (st.img_captioned ? " · подписями под картинками: " + st.img_captioned : "")
           + (st.img_untranslated ? " · надписей без перевода: " + st.img_untranslated : "")
           + (imgLost ? " · надписей не попало в файл: " + imgLost : ""))
        : (result.file + " — загрузка началась."));
    } else {
      toast.error("Экспорт не выполнен", (result && result.error) || "Сервер недоступен или вернул ошибку.");
    }
  };
  // Описания честные: обычный DOCX собирается ЗАНОВО и оформления исходника
  // не переносит вовсе — карточка годами обещала обратное.
  const formats = [
    ["docx_layout", "DOCX 1\u04321 \u2014 как оригинал",
     srcDoc ? "Перевод подставляется в исходный файл: шрифты, картинки, таблицы, колонтитулы и выделения внутри абзаца на месте"
            : "Нужен исходный .docx — приложите его ниже", "file"],
    ["docx", "DOCX — новый файл", "Собирается с нуля: таблица оригинал/перевод либо перевод абзацами. Оформление исходника не переносится", "file"],
    ["pdf", "PDF", "Пока недоступен — используйте DOCX", "file"],
    ["xlsx", "Excel", "Таблица: оригинал и перевод по столбцам", "columns"],
  ];

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Экспорт"),
      React.createElement("p", { className: "lead" },
        "Соберите готовый документ по проекту «" + project.title + "». В файл идёт всё, "
        + "что переведено, независимо от статуса; сегменты без перевода остаются "
        + "на языке оригинала.")),

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
          React.createElement("p", { className: "hint", style: { marginTop: 10 } },
            srcDoc && fmt !== "docx_layout"
              ? "К проекту приложен исходник — «DOCX 1в1» сохранит его оформление. Выбранный сейчас формат соберёт документ с нуля."
              : "«DOCX 1в1» сохраняет оформление оригинала. Остальные форматы собираются с нуля.")
        ),
        React.createElement("div", null,
          React.createElement("h2", { className: "section-title" }, "Исходный документ"),
          React.createElement("div", { className: "card card-pad col", style: { gap: 12 } },
            srcDoc
              ? React.createElement("div", { className: "row between", style: { gap: 12, flexWrap: "wrap" } },
                  React.createElement("div", { style: { minWidth: 0 } },
                    React.createElement("div", { className: "row", style: { gap: 8 } },
                      React.createElement(Icon, { name: "checkCircle", size: 16, style: { color: "var(--c-success)" } }),
                      React.createElement("span", { style: { fontWeight: 650 } }, srcDoc.file)),
                    React.createElement("div", { className: "dim", style: { fontSize: 12.5, marginTop: 3 } },
                      "приложен " + (srcDoc.at || "") + " · абзацев: " + srcDoc.paras
                        + " · с переводом связано сегментов: " + srcDoc.segments)),
                  React.createElement(Btn, { variant: "secondary", size: "sm", icon: "upload",
                    disabled: attaching, onClick: () => fileRef.current && fileRef.current.click() },
                    attaching ? "Проверка…" : "Заменить"))
              : React.createElement("div", { className: "col", style: { gap: 10 } },
                  React.createElement("div", { style: { fontSize: 13, lineHeight: 1.55 } },
                    "К проекту не приложен исходный .docx, поэтому экспорт 1в1 собрать не из чего. ",
                    "Приложите тот самый файл, из которого проект импортирован: переводы, проверки и статусы не изменятся — ",
                    "сохранится только файл и разметка «абзац → сегмент»."),
                  React.createElement(Btn, { variant: "primary", size: "sm", icon: "upload",
                    disabled: attaching, onClick: () => fileRef.current && fileRef.current.click() },
                    attaching ? "Проверка файла…" : "Приложить исходник")),
            React.createElement("input", { ref: fileRef, type: "file", accept: ".docx", style: { display: "none" },
              onChange: (e) => doAttach(e.target.files && e.target.files[0], false) }))
        ),

        React.createElement(ImagesCard, { project, store, toast }),

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
          React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, "Пойдёт в файл"),
            React.createElement("strong", null, translated)),
          untranslated > 0 && React.createElement("div", { className: "row between" },
            React.createElement("span", { className: "muted" }, "Останется на языке оригинала"),
            React.createElement("strong", { style: { color: "var(--c-warning)" } }, untranslated)),
          React.createElement("div", { className: "row between" }, React.createElement("span", { className: "muted" }, "Формат"), React.createElement("strong", null, fmtLabel)),
          React.createElement(Btn, { variant: "primary", size: "lg", className: "btn-block", icon: busy ? null : "download", disabled: busy, onClick: doExport },
            busy ? React.createElement(React.Fragment, null, React.createElement(Spinner, null), "Сборка файла…")
                 : "Скачать " + fmtLabel)
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
