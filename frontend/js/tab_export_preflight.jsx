/* ── Текст, впечатанный в картинки ───────────────────────────────────
   Часть текста учебника живёт только в картинках: подписи под рисунками,
   схемы, куски отсканированных страниц. Абзацного якоря у него нет, поэтому
   до разбора он не переводится вовсе и в выгрузке «1в1» остаётся на языке
   оригинала.

   Карточка не прячется, когда находок ноль: пропавшее с экрана выглядит
   благополучнее, чем есть, а ноль здесь бывает и настоящим (в документе
   действительно нет надписей), и следствием того, что разбор не запускали. */
function ImagesCard({ project, toast }) {
  const [rep, setRep] = useState(null);
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    if (!window.API || !window.API.imagesReport) return;
    const r = await window.API.safeCall(() => window.API.imagesReport(project.id));
    if (r) setRep(r);
  };
  useEffect(() => { load(); }, [project.id]);

  /* Опрос идёт, только пока задача жива: разбор 158 картинок — это минуты,
     и держать вкладку открытой не обязано быть условием. */
  useEffect(() => {
    if (!job || !window.API) return;
    const timer = setInterval(async () => {
      const list = await window.API.safeCall(() => window.API.listJobs(project.id));
      const j = ((list && list.jobs) || []).find(x => x.id === job.id);
      if (!j) return;
      if (j.status === "queued" || j.status === "running") { setJob(j); return; }
      setJob(null);
      load();
      const c = j.counters || {};
      if (j.status === "error") toast.error("Разбор картинок прерван", j.error || "");
      else toast.success("Разбор картинок закончен",
        "картинок: " + (j.done || 0) + " · надписей: " + (c.blocks || 0)
        + (c.segments ? " · сегментов заведено: " + c.segments : "")
        + (c.unreadable ? " · не читаются: " + c.unreadable : ""));
    }, 2500);
    return () => clearInterval(timer);
  }, [job && job.id]);

  const start = async (dry) => {
    if (!window.API) return;
    setBusy(true);
    const r = await window.API.safeCall(
      () => window.API.createJob(project.id, "images", [], { dry_run: !!dry }));
    setBusy(false);
    if (!r || !r.ok) { toast.error("Разбор не запущен", "Сервер отказал."); return; }
    setJob(r.job);
    toast.info(dry ? "Ищем надписи" : "Читаем надписи",
      "Работа идёт на сервере — вкладку можно закрыть.");
  };
  const forget = async () => {
    setBusy(true);
    const r = await window.API.safeCall(() => window.API.imagesForget(project.id, false));
    setBusy(false);
    if (!r) { toast.error("Не удалось", "Сервер недоступен."); return; }
    load();
    toast.success("Распознанное снято", "сегментов убрано: " + r.removed
      + (r.keptTranslated && r.keptTranslated.length
         ? " · с переводом оставлено: " + r.keptTranslated.length : ""));
  };

  const st = (rep && rep.stats) || null;
  const running = !!job;
  const row = (label, value, color) => React.createElement("div", { className: "row between" },
    React.createElement("span", { className: "muted" }, label),
    React.createElement("strong", color ? { style: { color } } : null, value));

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

      !st && project.sourceDocx && React.createElement("div", { className: "hint" },
        "Разбор ещё не делался."),

      st && React.createElement(React.Fragment, null,
        row("Картинок в документе", st.images),
        row("С надписями", st.withText),
        row("Надписей найдено", st.blocks),
        st.segments > 0 && row("Стали сегментами", st.segments, "var(--c-success)"),
        st.text > 0 && row("Вернём в картинку при экспорте", st.repaintable),
        st.captioned > 0 && row("Уйдут подписью под картинкой", st.captioned, "var(--c-warning)"),
        (st.overlay > 0 || st.noise > 0) && row("Отсеяно (надпечатка аппарата, шум)",
          st.overlay + st.noise),
        st.unread > 0 && row("Не прочитано", st.unread, "var(--c-warning)"),
        st.unreadable > 0 && row("Картинки не читаются", st.unreadable, "var(--c-warning)")),

      running && React.createElement("div", { className: "col", style: { gap: 8 } },
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement(Spinner, null),
          React.createElement("span", { style: { fontSize: 13 } },
            "картинка " + (job.done || 0) + " из " + (job.total || 0))),
        React.createElement(Btn, { variant: "secondary", size: "sm",
          onClick: () => window.API.safeCall(() => window.API.stopJob(job.id)) },
          "Остановить")),

      !running && project.sourceDocx && React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
        React.createElement(Btn, { variant: "secondary", size: "sm", icon: "search",
          disabled: busy, onClick: () => start(true) }, "Найти надписи"),
        /* Чтение платное, поэтому смета стоит прямо на кнопке. Ноль — это
           «всё уже прочитано», а не «бесплатно». */
        React.createElement(Btn, { variant: "primary", size: "sm", icon: "sparkles",
          disabled: busy || !st || !st.blocks || (rep && rep.est === 0),
          onClick: () => start(false) },
          "Прочитать и завести сегменты"
            + (rep && rep.est ? " (~$" + rep.est.toFixed(2) + ")" : "")),
        st && st.segments > 0 && React.createElement(Btn, { variant: "ghost", size: "sm",
          disabled: busy, onClick: forget }, "Забыть распознанное")),

      rep && rep.at && React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        "разбор: " + rep.at + " · модель чтения: " + (rep.model || "")
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
      toast.success("Файл готов", st.written != null
        ? (result.file + " · переведено абзацев: " + st.written
           + (st.untranslated ? " · без перевода: " + st.untranslated : "")
           + (st.inline ? " · выделений перенесено: " + st.inline : "")
           + (st.approx ? " (из них приблизительно: " + st.approx + ")" : ""))
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

        React.createElement(ImagesCard, { project, toast }),

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

/* ============================================================
   Tab: Preflight — pre-translation analysis
   ============================================================ */
function TabPreflightOld({ store, toast }) {
  const project = store.activeProject;
  const [analyzing, setAnalyzing] = useState(false);
  if (!project) return React.createElement("div", { className: "page" }, React.createElement(NoProject, { store }));

  const total = project.segments.length;
  const byRoute = {};
  project.segments.forEach(s => { byRoute[s.route] = (byRoute[s.route] || 0) + 1; });
  const routes = [
    ["EXACT_TM", "Точное TM", "var(--route-tm)", 0],
    ["DUPLICATE", "Дубликаты", "var(--route-dup)", 0],
    ["GOOGLE_SAFE", "Google", "var(--route-google)", 0],
    ["GPT_REQUIRED", "GPT-4", "var(--route-gpt)", 0.19],
    ["HUMAN_REVIEW", "Проверка", "var(--route-human)", 0],
  ].map(([k, l, c, cost]) => ({ k, l, c, n: byRoute[k] || 0, cost: (byRoute[k] || 0) * cost }));
  const estCost = routes.reduce((a, r) => a + r.cost, 0);
  const tmMatches = byRoute["EXACT_TM"] || 0;
  const riskCounts = { low: 0, medium: 0, high: 0, critical: 0 };
  project.segments.forEach(s => riskCounts[s.risk]++);
  const glossCovered = project.segments.filter(s => store.glossary.some(g => s.source.toLowerCase().includes(g.src.toLowerCase()))).length;
  const coverage = Math.round(glossCovered / total * 100);

  const analyze = () => { setAnalyzing(true); setTimeout(() => { setAnalyzing(false); toast.success("Анализ завершён", total + " сегментов проанализировано."); }, 1500); };

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "row between page-head", style: { alignItems: "flex-end" } },
      React.createElement("div", null,
        React.createElement("h1", null, "Предполётный анализ"),
        React.createElement("p", { className: "lead", style: { marginBottom: 0 } }, "Маршрутизация, стоимость и риски до запуска перевода.")),
      React.createElement(Btn, { variant: "primary", icon: analyzing ? null : "target", disabled: analyzing, onClick: analyze },
        analyzing ? React.createElement(React.Fragment, null, React.createElement(Spinner, null), "Анализ…") : "Анализировать")),
    React.createElement("div", { className: "dim", style: { marginTop: -16, marginBottom: 24, fontSize: 13 } }, "Последний анализ: 2 часа назад · " + total + " сегментов"),

    React.createElement("div", { className: "grid grid-4 section" },
      React.createElement(Metric, { icon: "list", label: "Всего сегментов", value: total }),
      React.createElement(Metric, { icon: "repeat", label: "Точные TM", value: tmMatches, sub: Math.round(tmMatches / total * 100) + "% покрытия" }),
      React.createElement(Metric, { icon: "zap", label: "Оценка стоимости", value: "$" + estCost.toFixed(2), color: "var(--c-purple)" }),
      React.createElement(Metric, { icon: "target", label: "Сложность", value: "Средняя", sub: riskCounts.high + riskCounts.critical + " высокого риска" })),

    React.createElement("div", { className: "section" },
      React.createElement("h2", { className: "section-title" }, "Маршрутизация сегментов"),
      React.createElement("div", { className: "card card-pad" },
        routes.map(r => React.createElement("div", { key: r.k, className: "hbar-row" },
          React.createElement("div", { className: "row", style: { gap: 8 } },
            React.createElement("span", { style: { width: 10, height: 10, borderRadius: 3, background: r.c } }),
            React.createElement("span", { style: { fontWeight: 600, fontSize: 13 } }, r.l)),
          React.createElement("div", { className: "hbar-track" },
            React.createElement("div", { className: "hbar-fill", style: { width: Math.max(6, r.n / total * 100) + "%", background: r.c } }, r.n + " сегм.")),
          React.createElement("div", { className: "hbar-cost dim", style: { textAlign: "right", fontWeight: 600 } }, r.cost ? "$" + r.cost.toFixed(2) : "$0"))))),

    React.createElement("div", { className: "grid grid-2 section" },
      React.createElement(Expander, { title: "Сводка по рискам", icon: "shield", right: total + " сегментов", defaultOpen: true },
        React.createElement("div", { className: "col", style: { gap: 12 } },
          [["low", "Низкий", "var(--c-success)"], ["medium", "Средний", "#ca8a04"], ["high", "Высокий", "var(--c-warning)"], ["critical", "Критический", "var(--c-error)"]]
            .map(([k, l, c]) => React.createElement("div", { key: k, className: "row between" },
              React.createElement("div", { className: "row", style: { gap: 8 } }, React.createElement("span", { style: { width: 9, height: 9, borderRadius: "50%", background: c } }), l),
              React.createElement("strong", null, riskCounts[k]))))),
      React.createElement("div", { className: "card card-pad col", style: { gap: 14 } },
        React.createElement("h3", { style: { fontSize: 17, fontWeight: 650 } }, "Покрытие глоссарием"),
        React.createElement(Ring, { value: coverage, size: 120, label: "покрыто" }),
        React.createElement("div", { className: "col", style: { gap: 6, width: "100%" } },
          React.createElement("div", { className: "row between" }, React.createElement("span", { className: "muted" }, "Сегментов с терминами"), React.createElement("strong", null, glossCovered)),
          React.createElement("div", { className: "row between" }, React.createElement("span", { className: "muted" }, "Отсутствующих терминов"), React.createElement("strong", { style: { color: "var(--c-warning)" } }, "15"))),
        React.createElement("div", { className: "card", style: { padding: "10px 12px", background: "var(--st-qa-bg)", color: "var(--st-qa-fg)", fontSize: 13 } },
          "Рекомендуется добавить 5 ключевых терминов в глоссарий."))
    )
  );
}

function Metric({ icon, label, value, sub, color }) {
  return React.createElement("div", { className: "card metric" },
    React.createElement("div", { className: "m-label" }, React.createElement(Icon, { name: icon, size: 16, style: { color: color || "var(--c-primary)" } }), label),
    React.createElement("div", { className: "m-value", style: color ? { color } : null }, value),
    sub && React.createElement("div", { className: "m-sub" }, sub));
}
window.Metric = Metric;
