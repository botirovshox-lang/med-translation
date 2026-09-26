/* ============================================================
   Видео: мини-редактор при загрузке и субтитры В КАДРЕ
   ============================================================
   Два экрана с одним сердцем — формой стиля субтитров (`VidStyleForm`).

   1) `VideoEditor` открывается, как только человек выбрал видео. Файл в это
      время уже грузится на сервер (кусками, `uploadMedia` с `noFinish`), а
      человек смотрит ролик прямо из памяти вкладки: обрезает начало и конец
      и выбирает шрифт, размер, цвет и место субтитров. «Готово» уходит на
      сервер ВМЕСТЕ с обрезкой и стилем: распознаётся, списывается и потом
      собирается только выбранный отрезок.
      Браузер показывает не всё (mkv, avi, wmv, HEVC…). Тогда кадр рисует
      СЕРВЕР, когда файл догрузится (`mediaUploadPreview`), а обрезка
      задаётся цифрами — длительность сервер тоже скажет сам.

   2) `VidBurnDialog` — перед сборкой видео с субтитрами в кадре. Здесь
      перевод уже есть, и кадр предпросмотра рисует сервер ТЕМ ЖЕ фильтром,
      тем же шрифтом и тем же документом, что сборка: «подтвердить размер
      и шрифт» значит подтвердить то, что окажется в файле.

   Предпросмотр в браузере (`VidOverlay`) — те же файлы шрифтов
   (vendor/fonts/sub, их же берёт ffmpeg) и те же доли кегля, что отдаёт
   сервер (`metrics`, `emRatio`): вторая копия этих чисел в .jsx разошлась
   бы с впечатыванием. Но это всё равно приближение (перенос строк браузер
   считает сам) — поэтому окончательный ответ даёт кадр с сервера. */
const vidE = React.createElement;

const VID_AUDIO_RE = /\.(mp3|wav|m4a|aac|ogg|oga|opus|flac|wma|amr)$/i;
const VID_COLORS = ["#FFFFFF", "#FFE14D", "#9BE7FF", "#000000"];

function vidTime(sec) {
  const t = Math.max(0, sec || 0), m = Math.floor(t / 60), s = t - m * 60;
  return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1);
}
/* «1:05.5», «65.5», «1:02:03» → секунды; мусор — NaN. */
function vidParseTime(str) {
  const parts = String(str || "").trim().replace(",", ".").split(":");
  if (!parts.length || parts.length > 3) return NaN;
  let t = 0;
  for (const p of parts) {
    if (!/^\d+(\.\d+)?$/.test(p.trim())) return NaN;
    t = t * 60 + parseFloat(p);
  }
  return t;
}

/* Шрифты регистрируются в браузере по одному разу на вкладку — те же файлы,
   что у ffmpeg. Жирное начертание — отдельной семьёй: иначе браузер
   дорисовал бы жирность сам и предпросмотр разошёлся бы с впечатанным. */
const vidFontLoads = {};
function vidFamily(font, bold) { return "mct-sub-" + (font ? font.id : "x") + (bold ? "-b" : ""); }
function vidLoadFonts(fonts) {
  if (!window.FontFace || !document.fonts) return;
  const v = (window.BOOT && window.BOOT.v) || "0";
  (fonts || []).forEach(f => [false, true].forEach(b => {
    const fam = vidFamily(f, b);
    if (vidFontLoads[fam]) return;
    try {
      const ff = new FontFace(fam, "url(vendor/fonts/sub/" + encodeURIComponent(b ? f.bold : f.regular) + "?v=" + v + ")");
      vidFontLoads[fam] = ff.load().then(x => { document.fonts.add(x); return true; }).catch(() => false);
    } catch (e) { vidFontLoads[fam] = Promise.resolve(false); }
  }));
}

/* Каталог шрифтов, умолчание стиля, доли кегля и образец текста — с сервера,
   по языку перевода: покрывает ли шрифт его буквы, знает только сервер. */
function useVidFonts(lang) {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    let dead = false, tries = 0;
    /* Сбой сети — несколько повторов, потом слова и кнопка, а не вечный
       «Загружаем шрифты…» с погашенной кнопкой: без стиля видео
       не подтвердить. */
    const go = () => window.API.safeCall(() => window.API.mediaFonts(lang)).then(r => {
      if (dead) return;
      if (!r) {
        tries++;
        if (tries < 5) { setTimeout(() => { if (!dead) go(); }, 1500 * tries); return; }
        setInfo({ failed: true, retry: () => { tries = 0; setInfo(null); go(); } });
        return;
      }
      vidLoadFonts(r.fonts);
      setInfo(r);
    });
    go();
    return () => { dead = true; };
  }, [lang]);
  return info;
}

/* Размер отрисованной картинки: субтитры считаются от НЕЁ, как libass
   считает от кадра. */
function useVidBoxSize(ref) {
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const upd = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    upd();
    if (!window.ResizeObserver) return;
    const ro = new ResizeObserver(upd);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref.current]);
  return size;
}

function vidHexRgb(hex) {
  const c = (hex || "#000000").replace("#", "");
  return [parseInt(c.slice(0, 2), 16), parseInt(c.slice(2, 4), 16), parseInt(c.slice(4, 6), 16)];
}

/* Субтитр поверх картинки W×H — теми же числами, что `media.style_numbers`
   и `media.ass_document`: кегль — доля короткой стороны, обводка, тень
   и плашка — доли кегля, поля — доли кадра. */
function VidOverlay({ style, text, info, w, h }) {
  if (!info || !w || !h || !text) return null;
  const font = (info.fonts || []).find(f => f.id === style.font) || (info.fonts || [])[0];
  const m = info.metrics || {};
  const fsAss = style.size / 100 * Math.min(w, h);
  const fs = fsAss * (font ? font.emRatio : 0.66);
  const edge = (style.color || "").toUpperCase() === "#000000" ? [255, 255, 255] : [0, 0, 0];
  const rgba = (a) => "rgba(" + edge.join(",") + "," + a + ")";
  const span = { fontFamily: "'" + vidFamily(font, style.bold) + "', sans-serif", fontSize: fs + "px",
    lineHeight: fsAss + "px", color: style.color, whiteSpace: "pre-wrap", fontWeight: 400 };
  if (style.bg === "box") {
    const pad = Math.max(2, fsAss * (m.boxPad || 0.2));
    Object.assign(span, { background: rgba(1 - (m.boxAlpha || 0.25)), padding: (pad * 0.35) + "px " + pad + "px",
      boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone" });
  } else {
    const ol = Math.max(1, fsAss * (style.bg === "shadow" ? (m.shadowOutline || 0.03) : (m.outline || 0.07)));
    Object.assign(span, { WebkitTextStroke: (2 * ol) + "px " + rgba(1), paintOrder: "stroke fill" });
    if (style.bg === "shadow") {
      const sh = Math.max(1, fsAss * (m.shadow || 0.06));
      span.textShadow = sh + "px " + sh + "px 0 " + rgba(1 - (m.shadowAlpha || 0.45));
    }
  }
  /* Безопасная область — как у сборки (`media.style_numbers`): ширина —
     доля кадра, сбоку ещё обводка или поле плашки, высота — число строк.
     Рамка пунктиром: за неё субтитр не выйдет — лишнее уменьшится или
     разделится при сборке (точный ответ — кадр с сервера). */
  const areaW = (style.boxW || 100) / 100 * w;
  const out = style.bg === "box" ? Math.max(2, fsAss * (m.boxPad || 0.2))
    : Math.max(1, fsAss * (style.bg === "shadow" ? (m.shadowOutline || 0.03) : (m.outline || 0.07)));
  const side = (w - areaW) / 2 + out;
  const box = { position: "absolute", left: side, right: side, textAlign: "center", pointerEvents: "none" };
  const edgeKey = style.position === "top" ? "top" : "bottom";
  box[edgeKey] = style.margin / 100 * h;
  const frameBox = { position: "absolute", left: (w - areaW) / 2, width: areaW, pointerEvents: "none",
    /* Строка у libass — высотой в кегль ASS (winAscent+winDescent), а не
       в em: рамка той же высоты, что займут строки в кадре. */
    height: (style.maxLines || 2) * fsAss + 2 * out, border: "1px dashed rgba(255,255,255,0.7)",
    outline: "1px dashed rgba(0,0,0,0.5)", borderRadius: 2 };
  frameBox[edgeKey] = style.margin / 100 * h - out;
  return vidE(React.Fragment, null,
    vidE("div", { style: frameBox, "data-sub-area": "1" }),
    vidE("div", { style: box }, vidE("span", { style: span }, text)));
}

/* Кнопки-переключатели «одно из»: меньше чтения, чем у списка (инв. 32). */
function VidSeg({ value, options, onChange }) {
  return vidE("div", { className: "row", style: { gap: 4, flexWrap: "wrap" } },
    options.map(([v, label]) => vidE(Btn, { key: v, size: "sm", variant: v === value ? "primary" : "ghost",
      onClick: () => onChange(v) }, label)));
}

function VidStyleForm({ style, onChange, info }) {
  if (!info) return vidE("div", { className: "dim", style: { fontSize: 13 } }, vidE(Spinner, null), " ", TR("Загружаем шрифты…"));
  if (info.failed) return vidE("div", { className: "row", style: { gap: 8, alignItems: "center", flexWrap: "wrap" } },
    vidE("span", { style: { color: "var(--c-danger)", fontSize: 13 } }, TR("Шрифты не загрузились — проверьте связь.")),
    vidE(Btn, { size: "sm", variant: "secondary", icon: "repeat", onClick: info.retry }, TR("Повторить")));
  const set = (k, v) => onChange(Object.assign({}, style, { [k]: v }));
  const lim = info.limits || { size: [2.5, 12], margin: [2, 30] };
  const font = (info.fonts || []).find(f => f.id === style.font);
  return vidE("div", { className: "col", style: { gap: 12 } },
    vidE(Field, { label: TR("Шрифт") },
      vidE(Select, { value: style.font, onChange: (e) => set("font", e.target.value) },
        (info.fonts || []).map(f => vidE("option", { key: f.id, value: f.id },
          f.name + (f.covers ? "" : TR(" — нет букв языка перевода")))))),
    font && !font.covers && vidE("div", { style: { fontSize: 12, color: "var(--c-warning)" } },
      TR("В этом шрифте нет букв языка перевода. Выберите другой или проверьте кадр с сервера.")),
    vidE(Field, { label: TR("Размер текста") + " · " + style.size + "%" },
      vidE("input", { type: "range", min: lim.size[0], max: lim.size[1], step: 0.5, value: style.size,
        style: { width: "100%" }, onChange: (e) => set("size", parseFloat(e.target.value)) })),
    vidE("div", { className: "row", style: { gap: 16, flexWrap: "wrap", alignItems: "flex-start" } },
      vidE(Field, { label: TR("Цвет") },
        vidE("div", { className: "row", style: { gap: 6 } },
          VID_COLORS.map(c => vidE("button", { key: c, type: "button", "aria-label": c, title: c,
            onClick: () => set("color", c),
            style: { width: 28, height: 28, borderRadius: 6, background: c, cursor: "pointer",
              border: style.color === c ? "3px solid var(--c-primary)" : "1px solid var(--c-border)" } })))),
      vidE(Field, { label: TR("Начертание") },
        vidE(VidSeg, { value: style.bold ? "b" : "n", onChange: (v) => set("bold", v === "b"),
          options: [["n", TR("Обычный")], ["b", TR("Жирный")]] }))),
    vidE(Field, { label: TR("Фон под текстом") },
      vidE(VidSeg, { value: style.bg, onChange: (v) => set("bg", v),
        options: [["outline", TR("Обводка")], ["shadow", TR("Тень")], ["box", TR("Плашка")]] })),
    vidE("div", { className: "row", style: { gap: 16, flexWrap: "wrap", alignItems: "flex-start" } },
      vidE(Field, { label: TR("Где") },
        vidE(VidSeg, { value: style.position, onChange: (v) => set("position", v),
          options: [["bottom", TR("Снизу")], ["top", TR("Сверху")]] })),
      vidE("div", { style: { flex: "1 1 160px" } },
        vidE(Field, { label: TR("Отступ от края") + " · " + style.margin + "%" },
          vidE("input", { type: "range", min: lim.margin[0], max: lim.margin[1], step: 0.5, value: style.margin,
            style: { width: "100%" }, onChange: (e) => set("margin", parseFloat(e.target.value)) })))),
    vidE("div", { style: { fontWeight: 600, fontSize: 14, marginTop: 4 } }, TR("Область текста")),
    vidE("div", { className: "row", style: { gap: 16, flexWrap: "wrap", alignItems: "flex-start" } },
      vidE("div", { style: { flex: "1 1 160px" } },
        vidE(Field, { label: TR("Ширина") + " · " + style.boxW + "%" },
          vidE("input", { type: "range", min: (lim.boxW || [30, 100])[0], max: (lim.boxW || [30, 100])[1], step: 1,
            value: style.boxW, style: { width: "100%" }, onChange: (e) => set("boxW", parseFloat(e.target.value)) }))),
      vidE(Field, { label: TR("Строк не больше") },
        vidE(VidSeg, { value: String(style.maxLines), onChange: (v) => set("maxLines", parseInt(v, 10)),
          options: [["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"]] }))),
    vidE(Field, { label: TR("Если реплика не влезает") },
      vidE(VidSeg, { value: style.fit, onChange: (v) => set("fit", v),
        options: [["both", TR("Уменьшить, потом разделить")], ["shrink", TR("Уменьшить шрифт")],
                  ["split", TR("Разделить реплику")], ["none", TR("Только показать")]] })),
    vidE("div", { className: "dim", style: { fontSize: 12 } },
      style.fit === "none" ? TR("Ничего не меняем — покажем, какие реплики вылезают за рамку, чтобы сократить их вручную.")
      : TR("Шрифт уменьшаем не сильнее чем до ") + Math.round((lim.minScale || 0.7) * 100)
        + TR("%; делим реплику на части по времени, если каждой хватает хотя бы ") + (lim.splitMinSec || 0.8)
        + TR(" с. Что не уместится и так — покажем списком.")));
}

/* Кадр с сервера: картинка приходит адресом blob:, старый освобождается. */
function useVidServerFrame() {
  const [url, setUrl] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const seq = useRef(0);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  const load = async (fn) => {
    const my = ++seq.current;
    setBusy(true); setErr("");
    for (let i = 0; ; i++) {
      try {
        const u = await fn();
        if (my !== seq.current) { URL.revokeObjectURL(u); return; }
        setUrl(u);
        break;
      } catch (e) {
        if (my !== seq.current) return;
        /* 429 — слот кадра занят (он один на сервис). Спросить ещё раз:
           иначе на экране остался бы кадр ПРЕЖНЕГО стиля, и человек
           подтвердил бы то, чего не видел. */
        if (e.status === 429 && i < 5) { await new Promise(r => setTimeout(r, 1200)); continue; }
        setErr(e.message || String(e));
        break;
      }
    }
    if (my === seq.current) setBusy(false);
  };
  return { url, busy, err, load };
}

function VidTimeInput({ label, value, onChange, max }) {
  const [txt, setTxt] = useState(vidTime(value));
  useEffect(() => { setTxt(vidTime(value)); }, [value]);
  const commit = () => {
    const t = vidParseTime(txt);
    if (isNaN(t)) { setTxt(vidTime(value)); return; }
    onChange(Math.max(0, max ? Math.min(max, t) : t));
  };
  return vidE(Field, { label },
    vidE(Input, { value: txt, style: { width: 110 }, onChange: (e) => setTxt(e.target.value), onBlur: commit,
      onKeyDown: (e) => { if (e.key === "Enter") commit(); } }));
}

/* Сколько минут спишется за выбранный отрезок (инвариант 39): неполная
   минута — минута. Кошелька минут нет — видео идёт страницами, строки нет.
   Остаток — из кэша сессии (`window._mcat_minutes`, его кладёт /auth/me):
   своего запроса здесь нет, а решает всё равно сервер при «готово». */
function vidMinutesLine(sec) {
  const m = window._mcat_minutes;
  if (!m || !m.wallet || !(sec > 0)) return null;
  const need = Math.max(1, Math.ceil(sec / 60 - 1e-9));
  const left = Math.max(0, Number(m.left || 0));
  const short = left < need;
  return vidE("div", { style: { fontSize: 12, color: short ? "var(--c-danger)" : undefined },
    className: short ? undefined : "dim" },
    TR("Спишется минут: ") + need + TR(" · на балансе: ") + left
    + (short ? (left >= 1 ? TR(" — распознаем начало на ") + Math.floor(left) + TR(" мин") : TR(" — не хватает")) : ""),
    short ? vidE("button", { className: "btn btn-ghost btn-sm", style: { marginLeft: 8 },
      onClick: () => { try { window.dispatchEvent(new CustomEvent("mct-pay-need",
        { detail: { kind: "minutes", need, left } })); } catch (e) {} } }, TR("Пополнить")) : null);
}

function VideoEditor({ file, meta, onCancel, onDone, toast }) {
  const isAudio = VID_AUDIO_RE.test(file.name || "");
  const info = useVidFonts(meta.tgt);
  const [style, setStyle] = useState(null);
  const [sample, setSample] = useState("");
  const [prog, setProg] = useState({ done: 0, total: file.size });
  const [token, setToken] = useState(null);
  const [upErr, setUpErr] = useState("");
  const [playable, setPlayable] = useState(null);     // null — ещё не знаем
  const [dur, setDur] = useState(0);
  const [probe, setProbe] = useState(null);
  const [trim, setTrim] = useState({ start: 0, end: 0 });
  const [cur, setCur] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [finErr, setFinErr] = useState("");
  const [attempt, setAttempt] = useState(0);
  const url = useMemo(() => URL.createObjectURL(file), [file]);
  const videoRef = useRef(null);
  const boxRef = useRef(null);
  const ctlRef = useRef(null);
  /* То, что нужно «готово» и ПОСЛЕ закрытия окна: подтвердили — файл
     догрузится и проект заведётся, даже если человек ушёл на другую
     вкладку. Состояние React к тому времени уже недоступно. */
  const live = useRef({});
  Object.assign(live.current, { trim, style, dur, onDone, toast });
  const box = useVidBoxSize(boxRef);
  const frame = useVidServerFrame();
  useEffect(() => () => URL.revokeObjectURL(url), [url]);
  useEffect(() => {
    if (info && !info.failed && !style) { setStyle(Object.assign({}, info.style, meta.style || {})); setSample(info.sample || ""); }
  }, [info]);
  /* Загрузка стартует сразу: пока человек обрезает и выбирает шрифт,
     гигабайты уже едут. Закрыли экран, не отменяя, — загрузка на сервере
     остаётся и продолжится с того же места при повторном выборе файла. */
  const doFinish = (tok) => {
    const L = live.current;
    if (L.finishing) return;
    L.finishing = true;
    if (L.mounted) { setFinishing(true); setFinErr(""); }
    const full = !L.dur || (L.trim.start <= 0.05 && L.trim.end >= L.dur - 0.05);
    window.API.mediaFinish(tok, { trim: full ? null : { start: L.trim.start, end: L.trim.end },
      style: isAudio ? null : L.style })
      .then(project => L.onDone(project, L.mounted))
      .catch(e => {
        L.finishing = false; L.confirmed = false;
        if (L.mounted) { setFinErr(e.message || String(e)); setConfirmed(false); setFinishing(false); return; }
        /* Окно уже закрыто, а человек думает, что проект заведётся: сказать
           вслух. Файл на сервере целиком — повторный выбор его доведёт. */
        if (L.toast) L.toast.error(TR("Видео не добавлено"), (e.message || String(e))
          + TR(" Выберите тот же файл ещё раз — загружать заново не придётся."));
      });
  };
  useEffect(() => {
    const ctl = { cancelled: false, stopped: false, noFinish: true };
    ctlRef.current = ctl;
    live.current.mounted = true;
    window.API.uploadMedia(file, { title: meta.title, src: meta.src, tgt: meta.tgt, domain: meta.domain,
      folder: meta.folder }, (p) => { if (p && p.total && live.current.mounted) setProg(p); }, ctl)
      .then(r => {
        if (ctl.cancelled) return;
        if (live.current.mounted) setToken(r.token);
        if (live.current.confirmed) doFinish(r.token);
      })
      .catch(e => {
        if (e.cancelled) return;
        live.current.confirmed = false;
        if (live.current.mounted) { setUpErr(e.message || String(e)); setConfirmed(false); }
      });
    /* Уход с экрана приостанавливает загрузку — кроме уже подтверждённой:
       её доводим до проекта. */
    return () => { live.current.mounted = false; if (!ctl.cancelled && !live.current.confirmed) ctl.stopped = true; };
  }, [file, attempt]);
  /* Браузер файл не показал — длительность и кадр узнаём у сервера. */
  useEffect(() => {
    if (!token || playable !== false) return;
    window.API.safeCall(() => window.API.mediaUploadProbe(token)).then(p => {
      if (!p) return;
      setProbe(p);
      if (!dur && p.duration) { setDur(p.duration); setTrim({ start: 0, end: p.duration }); }
    });
  }, [token, playable]);
  const serverFrame = (t) => {
    if (!token || isAudio) return;
    frame.load(() => window.API.mediaUploadPreview(token, { t: t != null ? t : cur, style, text: sample }));
  };
  useEffect(() => { if (token && playable === false && style && probe) serverFrame(trim.start + 1); }, [token, probe]);
  /* Подтвердили: файл уже здесь — «готово» сразу, иначе его позовёт
     загрузчик, когда догрузит (см. выше). */
  const confirm = () => {
    setConfirmed(true);
    live.current.confirmed = true;
    if (token) doFinish(token);
  };

  const onMeta = (e) => {
    const d = e.target.duration;
    if (isFinite(d) && d > 0) { setDur(d); setTrim({ start: 0, end: d }); setPlayable(true); }
  };
  const onTime = (e) => {
    const t = e.target.currentTime;
    setCur(t);
    if (t >= trim.end && !e.target.paused) e.target.pause();
  };
  const seek = (t) => { const v = videoRef.current; if (v && playable) v.currentTime = t; setCur(t); };
  const setStart = (t) => setTrim(x => ({ start: Math.min(Math.max(0, t), Math.max(0, x.end - 1)), end: x.end }));
  const setEnd = (t) => setTrim(x => ({ start: x.start, end: Math.max(Math.min(dur || t, t), x.start + 1) }));
  /* Крестик и Esc — «потом»: загрузка остаётся на сервере и продолжится
     с того же места, когда этот файл выберут снова. Удаляет её только
     «Отменить» — случайный Esc не должен выбрасывать гигабайты. */
  const close = () => {
    if (ctlRef.current && !live.current.confirmed) ctlRef.current.stopped = true;
    onCancel();
  };
  const cancel = () => {
    const ctl = ctlRef.current;
    live.current.confirmed = false;
    if (ctl) ctl.cancelled = true;
    /* Номер загрузки загрузчик кладёт в ctl сразу после старта: отменённая
       ПОСРЕДИ загрузки тоже удаляется, а не лежит на сервере сутки. */
    const tok = (ctl && ctl.token) || token;
    if (tok) window.API.safeCall(() => window.API.mediaUploadCancel(tok));
    onCancel();
  };
  const pct = prog.total ? Math.round(prog.done / prog.total * 100) : 0;
  const len = Math.max(0, trim.end - trim.start);
  const shownText = sample;
  const media = isAudio
    ? vidE("audio", { ref: videoRef, src: url, controls: true, style: { width: "100%" },
        onLoadedMetadata: onMeta, onTimeUpdate: onTime, onError: () => setPlayable(false) })
    : playable === false
      ? vidE("div", { className: "col", style: { gap: 8 } },
          vidE("div", { className: "dim", style: { fontSize: 13 } },
            TR("Браузер не показывает видео в этом формате. Кадр с субтитрами нарисует сервер, когда файл загрузится.")),
          frame.url
            ? vidE("img", { src: frame.url, alt: "", style: { maxWidth: "100%", maxHeight: "52vh", borderRadius: 8, display: "block" } })
            : vidE("div", { style: { aspectRatio: probe && probe.video ? (probe.video.width + "/" + probe.video.height) : "16/9",
                maxHeight: "52vh", background: "#111", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center",
                color: "#bbb", fontSize: 13 } }, token ? (frame.busy ? TR("Рисуем кадр…") : "") : TR("Файл загружается…")))
      : vidE("div", { ref: boxRef, style: { position: "relative", display: "inline-block", maxWidth: "100%", lineHeight: 0 } },
          vidE("video", { ref: videoRef, src: url, controls: true, playsInline: true, preload: "metadata",
            style: { display: "block", maxWidth: "100%", maxHeight: "52vh", borderRadius: 8, background: "#000" },
            onLoadedMetadata: onMeta, onTimeUpdate: onTime, onError: () => setPlayable(false) }),
          style && vidE("div", { style: { position: "absolute", inset: 0, lineHeight: "normal" } },
            vidE(VidOverlay, { style, text: shownText, info, w: box.w, h: box.h })));
  const footer = vidE("div", { className: "row between row-wrap", style: { gap: 10, width: "100%" } },
    vidE("div", { className: "col", style: { gap: 4, minWidth: 200, flex: "1 1 200px" } },
      upErr
        ? vidE("div", { className: "row", style: { gap: 8, alignItems: "center", flexWrap: "wrap" } },
            vidE("span", { style: { color: "var(--c-danger)", fontSize: 13 } }, upErr),
            vidE(Btn, { size: "sm", variant: "secondary", icon: "repeat",
              onClick: () => { setUpErr(""); setAttempt(a => a + 1); } }, TR("Повторить")))
        : token
          ? vidE("div", { className: "dim", style: { fontSize: 13 } }, TR("Файл загружен"))
          : vidE(React.Fragment, null,
              vidE("div", { className: "dim", style: { fontSize: 12 } }, TR("Отправляем файл") + " · " + pct + "%"),
              vidE(ProgressBar, { value: pct })),
      finErr && vidE("div", { style: { color: "var(--c-danger)", fontSize: 13 } }, finErr),
      vidMinutesLine(dur > 0 ? len : 0)),
    vidE("div", { className: "row", style: { gap: 8 } },
      vidE(Btn, { variant: "ghost", disabled: finishing, onClick: cancel }, TR("Отменить")),
      vidE(Btn, { variant: "primary", icon: finishing ? null : "check",
        disabled: !!upErr || confirmed || finishing || (!isAudio && !style),
        onClick: confirm },
        finishing ? vidE(React.Fragment, null, vidE(Spinner, null), TR("Запускаем…"))
          : confirmed ? TR("Запустим, как только файл загрузится")
          : TR("Подтвердить и распознать речь"))));
  return vidE(Modal, { title: TR("Видео перед переводом"), icon: "scissors", width: 980, onClose: close, footer },
    vidE("div", { className: "col", style: { gap: 16 } },
      vidE("div", { className: "dim", style: { fontSize: 13 } },
        TR("Обрежьте лишнее и выберите, как будут выглядеть субтитры. Речь распознаем только на выбранном отрезке — тайминг встанет под неё сам.")),
      vidE("div", { className: "grid", style: { gridTemplateColumns: "repeat(auto-fit, minmax(min(360px, 100%), 1fr))", gap: 18, alignItems: "start" } },
        vidE("div", { className: "col", style: { gap: 12 } },
          media,
          dur > 0 && vidE("div", { className: "col", style: { gap: 8 } },
            vidE("div", { style: { fontWeight: 600, fontSize: 14 } }, TR("Обрезка")),
            vidE("div", { className: "row", style: { gap: 12, flexWrap: "wrap", alignItems: "flex-end" } },
              vidE(VidTimeInput, { label: TR("Начало"), value: trim.start, max: dur, onChange: (t) => { setStart(t); seek(t); } }),
              vidE(VidTimeInput, { label: TR("Конец"), value: trim.end, max: dur, onChange: (t) => { setEnd(t); seek(t); } }),
              playable && vidE(Btn, { size: "sm", variant: "secondary", onClick: () => setStart(cur) }, TR("Начало здесь")),
              playable && vidE(Btn, { size: "sm", variant: "secondary", onClick: () => setEnd(cur) }, TR("Конец здесь"))),
            vidE("input", { type: "range", min: 0, max: dur, step: 0.1, value: trim.start, "aria-label": TR("Начало"),
              style: { width: "100%" }, onChange: (e) => { setStart(parseFloat(e.target.value)); seek(parseFloat(e.target.value)); } }),
            vidE("input", { type: "range", min: 0, max: dur, step: 0.1, value: trim.end, "aria-label": TR("Конец"),
              style: { width: "100%" }, onChange: (e) => { setEnd(parseFloat(e.target.value)); seek(parseFloat(e.target.value)); } }),
            vidE("div", { className: "dim", style: { fontSize: 13 } },
              TR("Возьмём ") + vidTime(len) + TR(" из ") + vidTime(dur)
              + (len < dur - 0.1 ? TR(" — платите только за этот отрезок") : "")))),
        !isAudio && vidE("div", { className: "col", style: { gap: 12 } },
          vidE("div", { style: { fontWeight: 600, fontSize: 14 } }, TR("Субтитры")),
          style && vidE(VidStyleForm, { style, onChange: setStyle, info }),
          vidE(Field, { label: TR("Текст для примера") },
            vidE(Input, { value: sample, onChange: (e) => setSample(e.target.value) })),
          playable !== false && vidE("div", { className: "col", style: { gap: 6 } },
            vidE(Btn, { size: "sm", variant: "secondary", icon: "image", disabled: !token || frame.busy || !style,
              onClick: () => serverFrame(cur) },
              token ? TR("Как будет в файле — кадр с сервера") : TR("Кадр с сервера — после загрузки")),
            frame.url && vidE("img", { src: frame.url, alt: "", style: { maxWidth: "100%", borderRadius: 8 } })),
          playable === false && token && vidE(Btn, { size: "sm", variant: "secondary", icon: "repeat",
            disabled: frame.busy || !style, onClick: () => serverFrame(trim.start + 1) }, TR("Обновить кадр")),
          frame.err && vidE("div", { style: { color: "var(--c-danger)", fontSize: 12 } }, frame.err),
          vidE("div", { className: "dim", style: { fontSize: 12 } },
            TR("Стиль можно поменять и позже, перед сборкой видео: там будет кадр с настоящим переводом."))))));
}

/* Перед сборкой видео с субтитрами в кадре: стиль, кадр с настоящим
   переводом с сервера, качество с оценкой времени — и одна кнопка. */
function VidBurnDialog({ project, onClose, onStarted, toast, store }) {
  const pid = project.id;
  const info = useVidFonts(project.tgt);
  const [bi, setBi] = useState(null);
  const [style, setStyle] = useState(null);
  const [quality, setQuality] = useState("src");
  const [t, setT] = useState(0);
  const [busy, setBusy] = useState(false);
  const frame = useVidServerFrame();
  const [biErr, setBiErr] = useState("");
  const [biTry, setBiTry] = useState(0);
  const [fit, setFit] = useState(null);
  useEffect(() => {
    let dead = false;
    setBiErr("");
    window.API.mediaBurnInfo(pid).catch(e => { if (!dead) setBiErr(e.message || String(e)); return null; }).then(r => {
      if (dead || !r) return;
      setBi(r);
      setStyle(r.style);
      const first = (r.cues || []).find(c => c.tr) || (r.cues || [])[0];
      setT(first ? (first.start + first.end) / 2 : Math.min(1, r.span || 0));
    });
    return () => { dead = true; };
  }, [pid, biTry]);
  /* Кадр перерисовывается сам, когда стиль или место меняются и человек
     на полсекунды остановился: запрос — это декодирование кадра сервером. */
  useEffect(() => {
    if (!style || !bi) return;
    const id = setTimeout(() => frame.load(() => window.API.mediaPreview(pid, { t, style, quality })), 500);
    return () => clearTimeout(id);
  }, [style, t, quality, bi]);
  /* Что не влезет в область при этом стиле — по ВСЕМ репликам, без кадров. */
  useEffect(() => {
    if (!style || !bi) return;
    let dead = false;
    const id = setTimeout(() => window.API.safeCall(() => window.API.mediaFit(pid, { style, quality }))
      .then(r => { if (!dead && r) setFit(r); }), 500);
    return () => { dead = true; clearTimeout(id); };
  }, [style, quality, bi]);
  const showRows = (ids, label) => {
    if (!store || !store.setSegmentFilter) return;
    store.setSegmentFilter(ids || [], { label });
    onClose();
    store.go("editor");
  };
  const trCues = bi ? (bi.cues || []).filter(c => c.tr) : [];
  const untranslated = bi ? (bi.cues || []).length - trCues.length : 0;
  const jump = (dir) => {
    const list = trCues.length ? trCues : (bi.cues || []);
    const c = dir > 0 ? list.find(x => x.start > t + 0.05) : [...list].reverse().find(x => x.end < t - 0.05);
    if (c) setT((c.start + c.end) / 2);
  };
  const qs = bi ? bi.qualities || {} : {};
  const qLabel = (k) => (k === "src" ? TR("Как в оригинале") : k + "p")
    + (qs[k] ? " · " + qs[k].frame[0] + "×" + qs[k].frame[1] + " · ≈ " + Math.max(1, Math.round(qs[k].etaSec / 60)) + TR(" мин") : "");
  const start = async (saveOnly) => {
    setBusy(true);
    try {
      if (saveOnly) {
        await window.API.mediaStyle(pid, style);
        toast.success(TR("Стиль запомнен"), TR("Соберём видео с ним, когда нажмёте «Собрать»."));
        onClose();
      } else {
        const r = await window.API.mediaRender(pid, "burn", undefined, { style, quality });
        onStarted(r.job, r.etaSec);
      }
    } catch (e) { toast.error(saveOnly ? TR("Не сохранено") : TR("Не запущено"), e.message || String(e)); }
    setBusy(false);
  };
  const footer = vidE("div", { className: "row", style: { gap: 8, justifyContent: "flex-end", width: "100%", flexWrap: "wrap" } },
    vidE(Btn, { variant: "ghost", onClick: onClose }, TR("Закрыть")),
    vidE(Btn, { variant: "secondary", disabled: busy || !style, onClick: () => start(true) }, TR("Только запомнить стиль")),
    vidE(Btn, { variant: "primary", icon: "check", disabled: busy || !style || !bi || bi.tooLong || !bi.kept || !trCues.length,
      onClick: () => start(false) }, TR("Подтвердить и собрать")));
  return vidE(Modal, { title: TR("Субтитры в кадре"), icon: "sliders", width: 1040, onClose, footer },
    biErr
      ? vidE("div", { className: "row", style: { gap: 8, alignItems: "center", flexWrap: "wrap" } },
          vidE("span", { style: { color: "var(--c-danger)", fontSize: 13 } }, biErr),
          vidE(Btn, { size: "sm", variant: "secondary", icon: "repeat", onClick: () => setBiTry(x => x + 1) }, TR("Повторить")))
    : !bi || !style
      ? vidE("div", { className: "dim" }, vidE(Spinner, null), " ", TR("Загружаем…"))
      : vidE("div", { className: "grid", style: { gridTemplateColumns: "repeat(auto-fit, minmax(min(380px, 100%), 1fr))", gap: 18, alignItems: "start" } },
          vidE("div", { className: "col", style: { gap: 10 } },
            vidE("div", { style: { position: "relative", background: "#111", borderRadius: 8, minHeight: 180,
              display: "flex", alignItems: "center", justifyContent: "center" } },
              frame.url
                ? vidE("img", { src: frame.url, alt: "", style: { maxWidth: "100%", maxHeight: "56vh", display: "block", borderRadius: 8,
                    opacity: frame.busy ? 0.6 : 1 } })
                : vidE("span", { style: { color: "#bbb", fontSize: 13 } }, frame.busy ? TR("Рисуем кадр…") : "")),
            frame.err && vidE("div", { style: { color: "var(--c-danger)", fontSize: 12 } }, frame.err),
            vidE("input", { type: "range", min: 0, max: Math.max(0.1, bi.span - 0.1), step: 0.1, value: t,
              "aria-label": TR("Место в видео"), style: { width: "100%" }, onChange: (e) => setT(parseFloat(e.target.value)) }),
            vidE("div", { className: "row between", style: { gap: 8 } },
              vidE(Btn, { size: "sm", variant: "ghost", icon: "chevL", onClick: () => jump(-1) }, TR("Предыдущая реплика")),
              vidE("span", { className: "dim", style: { fontSize: 13 } }, vidTime(t) + " / " + vidTime(bi.span)),
              vidE(Btn, { size: "sm", variant: "ghost", iconRight: "chevR", onClick: () => jump(1) }, TR("Следующая реплика"))),
            vidE("div", { className: "dim", style: { fontSize: 12 } },
              TR("Это настоящий кадр из файла: тот же шрифт, размер и перенос строк, что будут в готовом видео.")),
            fit && fit.measured && fit.cues > 0 && (fit.shrunk + fit.split === 0 && !fit.over
              ? vidE("div", { className: "dim", style: { fontSize: 12 } }, TR("Все реплики умещаются в область."))
              : vidE("div", { className: "col", style: { gap: 4, fontSize: 13 } },
                  (fit.shrunk || fit.split) ? vidE("div", { className: "dim" },
                    (fit.shrunk ? TR("Уменьшим шрифт: ") + fit.shrunk + TR(" реплик") : "")
                    + (fit.shrunk && fit.split ? " · " : "")
                    + (fit.split ? TR("разделим по времени: ") + fit.split : "")) : null,
                  fit.over > 0 && vidE("div", { className: "row between row-wrap", style: { gap: 8, color: "var(--c-warning)" } },
                    vidE("span", null, fit.over + TR(" реплик не уместятся в область — сократите перевод или выберите другой вариант.")),
                    store && vidE(Btn, { size: "sm", variant: "ghost", onClick: () => showRows(fit.overIds, TR("Не умещаются в область субтитров")) },
                      TR("Показать строки"))))),
            untranslated > 0 && vidE("div", { style: { fontSize: 13, color: "var(--c-warning)" } },
              untranslated + TR(" реплик ещё не переведены — в кадр попадут только переведённые.")),
            bi.hdr && vidE("div", { className: "dim", style: { fontSize: 12 } },
              TR("Видео снято в HDR (10 бит): в готовом файле цвета могут стать чуть бледнее.")),
            info && !info.failed && !info.covered && vidE("div", { style: { fontSize: 13, color: "var(--c-warning)" } },
              TR("У нас нет шрифта с буквами этого языка — проверьте кадр: вместо букв могут быть квадраты.")),
            bi.tooLong && vidE("div", { style: { fontSize: 13, color: "var(--c-danger)" } },
              TR("Видео длиннее ") + bi.maxBurnMinutes + TR(" мин: в кадр впечатываем только ролики короче. Скачайте видео с субтитрами дорожкой.")),
            !bi.kept && vidE("div", { style: { fontSize: 13, color: "var(--c-danger)" } },
              TR("Исходное видео удалено по сроку хранения — загрузите его заново на этом экране."))),
          vidE("div", { className: "col", style: { gap: 14 } },
            vidE(VidStyleForm, { style, onChange: setStyle, info }),
            vidE(Field, { label: TR("Качество видео") },
              vidE(Select, { value: quality, onChange: (e) => setQuality(e.target.value) },
                Object.keys(qs).map(k => vidE("option", { key: k, value: k }, qLabel(k))))),
            vidE("div", { className: "dim", style: { fontSize: 12 } },
              TR("Каждый кадр перерисовывается, поэтому сборка идёт дольше, чем у дорожки субтитров. Время — оценка; страницу можно закрыть, готовый файл появится здесь.")))));
}

Object.assign(window, { VideoEditor, VidBurnDialog, VidStyleForm, VidOverlay, vidParseTime, vidTime });
