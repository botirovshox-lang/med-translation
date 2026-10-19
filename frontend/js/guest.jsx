/* ============================================================
   Гостевой режим (инвариант 43): первая страница БЕЗ регистрации,
   регистрация — только чтобы СКАЧАТЬ файл (почта → код, пароль потом).

   Экран живёт ОТДЕЛЬНО от оболочки приложения: человеку, который пришёл
   перевести файл, меню из девяти вкладок не нужно (инвариант 32 — один
   вопрос в фокусе, одна главная кнопка). Сервер считает всё сам:
   страницу, потолки, деньги; здесь — только показ и порядок шагов.

   Файл грузится до App (см. загрузчик index.html): экран гостя рисуется
   без токена, как экран входа, и вкладок не ждёт.
   ============================================================ */

/* Ключ возобновления: сессия живёт в памяти сервера и выкат её гасит,
   а результат обещан на сутки. Почты у гостя нет — вернуть его можно
   только этим ключом из его же браузера. */
const GUEST_LS = "mct-guest";
const GUEST_VIEW_SS = "mct-guest-view";
const GUEST_OFF_SS = "mct-guest-off";
const GUEST_REST_LS = "mct-guest-rest";
const GUEST_MEDIA_RE = /\.(mp4|mov|m4v|mkv|webm|avi|wmv|flv|mpg|mpeg|ts|mts|3gp|mp3|wav|m4a|aac|ogg|oga|opus|flac|wma|amr)$/i;

function guestRead() {
  try { return JSON.parse(localStorage.getItem(GUEST_LS) || "null") || null; } catch (e) { return null; }
}
function guestWrite(rec) {
  try { rec ? localStorage.setItem(GUEST_LS, JSON.stringify(rec)) : localStorage.removeItem(GUEST_LS); } catch (e) {}
}
function guestViewOn() { try { sessionStorage.setItem(GUEST_VIEW_SS, "1"); sessionStorage.removeItem(GUEST_OFF_SS); } catch (e) {} }
function guestViewOff() {
  try { sessionStorage.removeItem(GUEST_VIEW_SS); sessionStorage.setItem(GUEST_OFF_SS, "1"); } catch (e) {}
}

/* Показывать ли экран гостя вместо входа. Пришёл с лендинга
   (`?start=translate`), по ссылке «бесплатно» (`?try=1`) или уже начал
   гостем в этом браузере. «У меня есть аккаунт» гасит это до конца вкладки. */
function guestWanted() {
  try {
    if (sessionStorage.getItem(GUEST_VIEW_SS) === "1") return true;
    if (window.API && window.API.hasToken()) return false;
    if (sessionStorage.getItem(GUEST_OFF_SS) === "1") return false;
    const q = new URLSearchParams(window.location.search || "");
    if (q.get("try") === "1" || q.get("start") === "translate") return true;
    const g = guestRead();
    return !!(g && g.key && !g.converted);
  } catch (e) { return false; }
}

function guestLangCode(v) {
  const s = String(v || "").toUpperCase();
  return /^[A-Z]{2}(-[A-Z]{4})?$/.test(s) ? s : "";
}

/* Пара языков с лендинга: адрес, а после перезагрузки — sessionStorage
   (тот же ключ `mct-intent`, что у экрана входа). */
function guestIntent() {
  try {
    const q = new URLSearchParams(window.location.search || "");
    if (q.get("start") === "translate" || q.get("try") === "1")
      return { src: guestLangCode(q.get("src")), tgt: guestLangCode(q.get("tgt")) };
    const it = JSON.parse(sessionStorage.getItem("mct-intent") || "null");
    if (it) return { src: guestLangCode(it.src), tgt: guestLangCode(it.tgt) };
  } catch (e) {}
  return { src: "", tgt: "" };
}

function guestSleep(ms) { return new Promise(r => setTimeout(r, ms)); }

/* Метка приглашения/партнёра — та же, что уходит с регистрацией. */
function guestRef() {
  let ref = "", at = 0;
  try {
    const m = /[?&]ref=([^&#]+)/.exec(window.location.search || "");
    ref = m ? decodeURIComponent(m[1]).toUpperCase().replace(/-/g, "") : (localStorage.getItem("mct-ref") || "");
    if (m && /^[A-Z2-9]{4,16}$/.test(ref)) {
      localStorage.setItem("mct-ref", ref); localStorage.setItem("mct-ref-at", String(Date.now()));
    }
    at = Number(localStorage.getItem("mct-ref-at") || 0);
  } catch (e) {}
  return { ref: /^[A-Z2-9]{4,16}$/.test(ref) ? ref : "", refAt: at };
}

/* Какой файл отдавать: «как в оригинале» там, где он есть. */
function guestFormat(p) {
  if (!p) return "docx";
  if (p.media) return "original";
  const kind = p.importKind || "";
  if (kind === "pdf" || kind === "scan" || kind === "image") return "pdf";
  if (/\.docx$/i.test(p.fileName || "")) return "docx_layout";
  if (p.writeback) return "original";
  return "docx";
}

/* Капча Cloudflare Turnstile — только когда сервер дал ключ. Скрипт
   грузится по требованию: на экране входа его нет вовсе. */
function GuestCaptcha({ sitekey, onToken }) {
  const box = useRef(null);
  useEffect(() => {
    if (!sitekey) return;
    let alive = true, wid = null;
    const draw = () => {
      if (!alive || !window.turnstile || !box.current) return;
      wid = window.turnstile.render(box.current, {
        sitekey, language: (window.I18N && window.I18N.lang) || "auto",
        callback: (t) => onToken(t || ""), "expired-callback": () => onToken(""),
        "error-callback": () => onToken(""),
      });
    };
    if (window.turnstile) draw();
    else {
      let s = document.getElementById("mct-turnstile");
      if (!s) {
        s = document.createElement("script");
        s.id = "mct-turnstile";
        s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
        s.async = true;
        document.head.appendChild(s);
      }
      s.addEventListener("load", draw);
    }
    return () => { alive = false; try { if (wid != null && window.turnstile) window.turnstile.remove(wid); } catch (e) {} };
  }, [sitekey]);
  if (!sitekey) return null;
  return React.createElement("div", { ref: box, className: "guest-captcha" });
}

/* Ход работы — словами, без выдуманных процентов (инвариант 32): процент
   есть только у отправки файла. */
function guestPhaseText(ph) {
  switch (ph) {
    case "upload": return TR("Отправляем файл");
    case "parse": return TR("Читаем файл");
    case "listen": return TR("Распознаём речь");
    case "read": return TR("Читаем текст с картинок");
    case "translate": return TR("Переводим");
    case "queue": return TR("Ждём очереди — сейчас много переводов");
    default: return TR("Минуту…");
  }
}

function guestPartNote(p, info) {
  if (!p) return "";
  if (p.guestCut) return TR("Переведена страница ") + p.guestCut.page + TR(" из ") + p.guestCut.pdfPages + ".";
  if (p.trialExcerpt) return TR("Переведена первая страница из ") + (Math.round((p.trialExcerpt.filePages || 0) * 10) / 10) + ".";
  if (p.media && p.media.trim) return TR("Переведена первая минута видео.");
  return TR("Переведён весь файл.");
}

/* Почему перевод не дошёл до конца — по КОДАМ сервера (`stopReason` задачи,
   `imagesSkipped` проекта), фразу собирает браузер (инвариант 17). */
function guestWhyText(why) {
  switch (why) {
    case "limit": case "fnlimit": case "budget":
      return TR("Бесплатный лимит на этот файл закончился — зарегистрируйтесь, чтобы продолжить.");
    case "provider_quota": case "no_key": case "no_engine":
      return TR("Ошибка на стороне провайдера. Обратитесь в поддержку") + ".";
    case "error":
      return TR("Перевод прервался — попробуйте ещё раз позже.");
    default: return "";
  }
}

/* Строк в результате на экране — не больше: после «перевести весь документ»
   там может быть книга, а таблица без страниц вешает телефон. */
const GUEST_ROWS_MAX = 200;

/* Почта → код: поверх результата, без ухода со страницы. */
function GuestClaim({ onClose, onDone, onLogin }) {
  const [step, setStep] = useState("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [taken, setTaken] = useState(false);
  const ask = async () => {
    setBusy(true); setErr(""); setTaken(false);
    try {
      const r = await window.API.guestClaim(email.trim());
      setNote(r.mailSent ? TR("Код отправлен на ") + r.email : TRS(r.note || ""));
      setStep("code");
    } catch (e) {
      setErr(e.message || String(e));
      if (e.status === 409) setTaken(true);
    }
    setBusy(false);
  };
  const verify = async () => {
    setBusy(true); setErr("");
    try {
      const g = guestRef();
      const r = await window.API.guestVerify(code.trim(), g.ref, g.refAt);
      onDone(r.me);
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(false);
  };
  const submit = (e) => { e.preventDefault(); if (!busy) (step === "email" ? ask() : verify()); };
  return React.createElement(Modal, { title: TR("Скачать перевод"), icon: "download", onClose },
    React.createElement("form", { className: "col", style: { gap: 12 }, onSubmit: submit },
      step === "email" && React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13.5 } },
        TR("Укажите почту — пришлём код. Пароль не нужен: задать его можно потом.")),
      step === "email" && React.createElement(Input, { type: "email", autoComplete: "email", inputMode: "email",
        value: email, autoFocus: true, placeholder: "name@mail.com", "aria-label": TR("Почта"),
        onChange: (e) => setEmail(e.target.value), style: { fontSize: 16 } }),
      step === "code" && React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13.5 } }, note),
      step === "code" && React.createElement(Input, { inputMode: "numeric", autoComplete: "one-time-code",
        maxLength: 6, value: code, autoFocus: true, placeholder: "000000", "aria-label": TR("Код из письма"),
        onChange: (e) => setCode(e.target.value.replace(/\D/g, "")), style: { fontSize: 22, letterSpacing: 6, textAlign: "center" } }),
      err && React.createElement("div", { className: "guest-err", role: "alert" }, err),
      taken && React.createElement("button", { type: "button", className: "linklike", onClick: onLogin },
        TR("Войти в свой аккаунт")),
      React.createElement(Btn, { variant: "primary", type: "submit", className: "btn-block",
        disabled: busy || (step === "email" ? !/@/.test(email) : code.length < 6) },
        busy ? TR("Минуту…") : step === "email" ? TR("Получить код") : TR("Подтвердить и скачать")),
      step === "code" && React.createElement("button", { type: "button", className: "linklike",
        onClick: () => { setStep("email"); setCode(""); setErr(""); } }, TR("Другая почта или код не пришёл"))));
}

/* Перевести весь документ: сервер называет, сколько страниц докупить
   (`rest-quote`); не нужно — дописываем сразу, нужно — карточка оплаты
   (pay.jsx) с подставленной нехваткой, а после кассы — само. */
function GuestRest({ project, toast, onRun }) {
  const [q, setQ] = useState(null);
  const [pay, setPay] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    window.API.safeCall(() => window.API.restQuote(project.id)).then(r => { if (alive) setQ(r || null); });
    return () => { alive = false; };
  }, [project.id]);
  if (!q || !(q.add > 0)) return null;
  const go = async () => {
    if (q.need > 0) {
      try { localStorage.setItem(GUEST_REST_LS, String(project.id)); } catch (e) {}
      window._mcat_payIntent = { pages: q.need };
      await tabsReadyGuest();
      setPay(true);
      return;
    }
    setBusy(true);
    try { await onRun(); } catch (e) { toast.error(TR("Не получилось"), e.message || String(e)); }
    setBusy(false);
  };
  return React.createElement("div", { className: "card card-pad guest-rest" },
    React.createElement("div", { className: "row between row-wrap", style: { gap: 10 } },
      React.createElement("div", null,
        React.createElement("b", null, TR("Весь документ")),
        React.createElement("div", { className: "dim", style: { fontSize: 13 } },
          (q.estimate ? "≈ " : "") + q.filePages + TR(" стр.") + (q.need > 0 ? TR(" · докупить ") + q.need + TR(" стр.") : ""))),
      React.createElement(Btn, { variant: "primary", icon: "zap", disabled: busy, onClick: go },
        busy ? TR("Минуту…") : TR("Перевести весь документ"))),
    pay && typeof PayCard === "function" && React.createElement("div", { style: { marginTop: 12 } },
      React.createElement(PayCard, { toast, onPaid: () => setPay(false) })));
}

function tabsReadyGuest() {
  return (window.BOOT && window.BOOT.tabs()) || Promise.resolve();
}

function GuestApp({ toast, onExit }) {
  const [info, setInfo] = useState(null);
  const [stage, setStage] = useState("boot");          // boot | pick | work | done | fail
  const [file, setFile] = useState(null);
  const [langs, setLangs] = useState(() => guestIntent());
  const [captcha, setCaptcha] = useState("");
  const [err, setErr] = useState("");
  const [phase, setPhase] = useState("");
  const [pct, setPct] = useState(null);
  const [project, setProject] = useState(null);
  const [me, setMe] = useState(null);
  const [claim, setClaim] = useState(false);
  const [view, setView] = useState("tgt");             // телефон: оригинал | перевод
  const [pw, setPw] = useState("");
  const alive = useRef(true);
  const [why, setWhy] = useState("");                  // код причины недоделанного
  useEffect(() => () => { alive.current = false; }, []);

  /* Довести файл до перевода: распознавание и чтение картинок ставит
     сервер сам, перевод — мы, когда строки готовы. Один заход перевода:
     что не перевелось — показывается как есть, а не крутится по кругу. */
  const run = async (pid) => {
    setStage("work");
    let asked = false;
    for (let i = 0; i < 2400 && alive.current; i++) {
      const p = await window.API.getProject(pid);
      if (!alive.current) return;
      setProject(p);
      if (p.media && p.mediaStatus === "transcribing") { setPhase("listen"); await guestSleep(3000); continue; }
      if (p.mediaStatus === "failed") throw new Error(TRS(p.mediaError || "") || TR("Речь не распознана"));
      const jobs = ((await window.API.listJobs(pid)) || {}).active || [];
      if (jobs.length) {
        const k = jobs[0].kind;
        setPhase(jobs[0].status === "queued" ? "queue" : k === "images" ? "read" : k === "translate" ? "translate" : "wait");
        await guestSleep(2500); continue;
      }
      const todo = (p.segments || []).filter(s => !(s.target || "").trim() && s.status !== "confirmed").map(s => s.id);
      if (!todo.length || asked) {
        /* Строк нет или задача кончилась не всем — спросим, почему. */
        let code = "";
        if (todo.length) {
          const all = ((await window.API.listJobs(pid)) || {}).jobs || [];
          const j = all.find(x => x.kind === "translate");
          if (j && j.status === "stopped") code = j.stopReason || "error";
          else if (j && j.status === "error") code = "error";
        } else if (!(p.segments || []).length && p.imagesSkipped) code = p.imagesSkipped;
        if (alive.current) setWhy(code);
        break;
      }
      try {
        await window.API.createJob(pid, "translate", todo, { force: false });
        asked = true; setPhase("translate");
      } catch (e) {
        if (e.status === 429) { setPhase("queue"); await guestSleep(10000); continue; }
        throw e;
      }
      await guestSleep(1500);
    }
    if (alive.current) setStage("done");
  };

  const fail = (e) => {
    if (!alive.current) return;
    setErr((e && e.message) || String(e)); setCaptcha(""); setStage("fail");
  };

  /* Вернуться к своему: токен ещё жив — сразу, нет — по ключу. */
  const resume = async (g) => {
    if (!window.API.hasToken() && g && g.key) {
      try { await window.API.guestResume(g.key); }
      catch (e) { guestWrite(null); return false; }
    }
    if (!window.API.hasToken()) return false;
    const r = await window.API.me().catch(() => null);
    if (!r || !r.me) return false;
    setMe(r.me);
    guestViewOn();
    const pid = g && g.pid;
    if (!pid) { setStage("pick"); return true; }
    let rest = null;
    try { rest = localStorage.getItem(GUEST_REST_LS); } catch (e) {}
    const paid = /[?&]pay=\d+/.test(window.location.search || "");
    if (rest && String(rest) === String(pid) && paid && !r.me.guest) {
      try { localStorage.removeItem(GUEST_REST_LS); } catch (e) {}
      try { await window.API.trialRest(pid); } catch (e) { toast.error(TR("Остальное не добавлено"), e.message || String(e)); }
    }
    run(pid).catch(fail);
    return true;
  };

  useEffect(() => {
    window.API.safeCall(() => window.API.guestInfo()).then(r => { if (r) setInfo(r); });
    resume(guestRead()).then(ok => {
      if (ok || !alive.current) return;
      setStage("pick");
      if (window.MCT_HANDOFF) window.MCT_HANDOFF.peek().then(rec => {
        if (!rec || !alive.current) return;
        if (rec.file) setFile(rec.file);
        setLangs(l => ({ src: l.src || guestLangCode(rec.src), tgt: l.tgt || guestLangCode(rec.tgt) }));
      });
    }).catch(fail);
    /* Сессия гостя истекла посреди работы (выкат) — возвращаемся по ключу. */
    const h = () => { resume(guestRead()).then(ok => { if (!ok) setStage("pick"); }).catch(fail); };
    window.addEventListener("mct-auth-expired", h);
    return () => window.removeEventListener("mct-auth-expired", h);
  }, []);

  const start = async () => {
    setErr("");
    if (!file) { setErr(TR("Выберите файл")); return; }
    if (!langs.src) { setErr(TR("Выберите язык оригинала")); return; }
    if (!langs.tgt) { setErr(TR("Выберите, на какой язык переводить")); return; }
    if (langs.src && langs.src === langs.tgt) { setErr(TR("Языки оригинала и перевода совпадают")); return; }
    const media = GUEST_MEDIA_RE.test(file.name || "");
    if (media && info && file.size > info.mediaMb * 1048576) { setErr(TR("Видео слишком большое для бесплатного перевода")); return; }
    if (!media && info && file.size > info.maxMb * 1048576) { setErr(TR("Файл слишком большой")); return; }
    setStage("work"); setPhase("upload"); setPct(0);
    try {
      let g = guestRead();
      if (!window.API.hasToken() || !g || !g.key) {
        const ref = guestRef();
        const r = await window.API.guestStart({ accept: true, captcha, ref: ref.ref, refAt: ref.refAt,
          srcPage: (window.TELEMETRY && window.TELEMETRY.entry && window.TELEMETRY.entry()) || "" });
        g = { key: r.key };
        guestWrite(g);
        setMe(r.me);
      }
      guestViewOn();
      const src = langs.src;
      const onProg = (pr) => {
        if (!alive.current || !pr) return;
        if (pr.phase === "upload" && pr.total) { setPhase("upload"); setPct(Math.round(pr.done / pr.total * 100)); }
        else { setPhase(pr.phase === "media" ? "listen" : "parse"); setPct(null); }
      };
      let p;
      if (media) {
        p = await window.API.uploadMedia(file, { title: "", src, tgt: langs.tgt, domain: "general" }, onProg,
          { finishBody: { trim: { start: 0, end: (info && info.mediaSec) || 60 } } });
      } else {
        try { p = await window.API.uploadProject(file, "", src, langs.tgt, "general", null, onProg); }
        catch (e) {
          /* Тот же файл тем же гостем — открываем готовый, а не отказ. */
          if (e.status === 409 && e.data && e.data.project && e.data.project.id) p = { id: e.data.project.id };
          else throw e;
        }
      }
      g.pid = p.id;
      guestWrite(g);
      if (window.MCT_HANDOFF) window.MCT_HANDOFF.drop();
      setPct(null);
      await run(p.id);
    } catch (e) { fail(e); }
  };

  const download = async (force) => {
    if (!force && me && me.guest) { setClaim(true); return; }
    try {
      const fmt = guestFormat(project);
      const r = await window.API.exportProject(project.id, fmt, false);
      if (!r || !r.ok) throw new Error((r && r.error) || TR("Не удалось собрать файл"));
      await window.API.downloadFile(r.url, r.file || "");
    } catch (e) { toast.error(TR("Не удалось скачать файл"), e.message || String(e)); }
  };

  const savePw = async () => {
    try {
      const r = await window.API.profileSave({ password: pw });
      setMe(r.me); setPw("");
      toast.success(TR("Пароль задан"), TR("Входите по почте и паролю."));
    } catch (e) { toast.error(TR("Пароль не сохранён"), e.message || String(e)); }
  };

  /* «У меня есть аккаунт»: сессию гостя закрываем (ключ остаётся — вернуться
     к переводу можно до конца суток), иначе оболочка открылась бы гостю. */
  const toLogin = async () => {
    if (window.API.hasToken() && (!me || me.guest)) { try { await window.API.logout(); } catch (e) {} }
    guestViewOff(); onExit();
  };
  const openApp = () => {
    guestWrite({ converted: true });
    try { sessionStorage.removeItem(GUEST_VIEW_SS); } catch (e) {}
    onExit();
  };

  const brand = (info && info.brand) || "CAT Translator";
  const head = React.createElement("div", { className: "auth-brand" },
    React.createElement("span", { className: "auth-logo" }, React.createElement(Icon, { name: "globe", size: 11 })),
    React.createElement("span", null, brand));

  if (stage === "boot")
    return React.createElement("div", { className: "auth-wrap" }, React.createElement(Spinner, { lg: true }));

  if (info && !info.enabled && stage === "pick")
    return React.createElement("div", { className: "auth-wrap" },
      React.createElement("div", { className: "auth-card" }, head,
        React.createElement("h1", null, TR("Бесплатный перевод сейчас недоступен")),
        React.createElement(Btn, { variant: "primary", className: "btn-block", onClick: toLogin }, TR("Войти или зарегистрироваться"))));

  if (stage === "pick") {
    const ls = (info && info.languages) || [];
    const opt = (l) => React.createElement("option", { key: l.code, value: l.code, lang: l.code.toLowerCase() }, l.native);
    const media = file && GUEST_MEDIA_RE.test(file.name || "");
    return React.createElement("div", { className: "auth-wrap" },
      React.createElement("div", { className: "auth-card guest-card" }, head,
        React.createElement("h1", null, TR("Переведём первую страницу бесплатно")),
        React.createElement("p", { className: "auth-sub" },
          TR("Без регистрации. Документ, скан, фото или видео — регистрация понадобится только чтобы скачать.")),
        React.createElement("label", { className: "guest-drop" + (file ? " has" : "") },
          React.createElement("input", { type: "file", style: { display: "none" },
            onChange: (e) => { const f = e.target.files && e.target.files[0]; if (f) { setFile(f); setErr(""); } } }),
          React.createElement(Icon, { name: file ? "file" : "upload", size: 22 }),
          React.createElement("span", null, file ? file.name : TR("Выберите файл"))),
        React.createElement("div", { className: "row", style: { gap: 8, marginTop: 10 } },
          React.createElement(Select, { value: langs.src, "aria-label": TR("Язык оригинала"),
            onChange: (e) => setLangs({ ...langs, src: e.target.value }) },
            React.createElement("option", { value: "" }, TR("Язык оригинала")), ls.map(opt)),
          React.createElement(Icon, { name: "chevR", size: 16 }),
          React.createElement(Select, { value: langs.tgt, "aria-label": TR("На какой язык"),
            onChange: (e) => setLangs({ ...langs, tgt: e.target.value }) },
            React.createElement("option", { value: "" }, TR("На какой язык?")), ls.map(opt))),
        media && info && React.createElement("div", { className: "dim", style: { fontSize: 12.5, marginTop: 8 } },
          TR("Бесплатно переводим первую минуту видео.")),
        React.createElement(GuestCaptcha, { sitekey: info && info.turnstile, onToken: setCaptcha }),
        err && React.createElement("div", { className: "guest-err", role: "alert" }, err),
        React.createElement(Btn, { variant: "primary", icon: "zap", className: "btn-block", style: { marginTop: 14 },
          disabled: !file || !langs.src || !langs.tgt || !info || (info.turnstile && !captcha), onClick: start },
          TR("Перевести бесплатно")),
        React.createElement("p", { className: "auth-foot" },
          TR("Нажимая «Перевести бесплатно», вы принимаете "),
          React.createElement("a", { href: "/terms", target: "_blank", rel: "noopener" }, TR("оферту")),
          TR(" и "),
          React.createElement("a", { href: "/privacy", target: "_blank", rel: "noopener" }, TR("политику обработки данных")),
          TR(": текст обрабатывают поставщики ИИ за рубежом, бесплатный перевод хранится сутки.")),
        React.createElement("div", { className: "row", style: { justifyContent: "center", marginTop: 12 } },
          React.createElement("button", { type: "button", className: "linklike", onClick: toLogin },
            TR("У меня есть аккаунт — войти")))));
  }

  if (stage === "work" || stage === "fail") {
    return React.createElement("div", { className: "auth-wrap" },
      React.createElement("div", { className: "auth-card guest-card" }, head,
        stage === "work" && React.createElement("h1", null, guestPhaseText(phase)),
        stage === "work" && React.createElement("p", { className: "auth-sub" },
          TR("Обычно это минута-две. Вкладку можно не держать открытой: перевод хранится сутки в этом браузере.")),
        stage === "work" && (pct != null
          ? React.createElement(ProgressBar, { value: pct })
          : React.createElement("div", { className: "pbar pbar-indet" }, React.createElement("span", null))),
        stage === "fail" && React.createElement("h1", null, TR("Не получилось")),
        stage === "fail" && React.createElement("div", { className: "guest-err", role: "alert" }, err),
        stage === "fail" && React.createElement(Btn, { variant: "primary", className: "btn-block", style: { marginTop: 14 },
          onClick: () => { setErr(""); setStage("pick"); } }, TR("Попробовать ещё раз")),
        stage === "fail" && React.createElement("div", { className: "row", style: { justifyContent: "center", marginTop: 12 } },
          React.createElement("button", { type: "button", className: "linklike", onClick: toLogin },
            TR("Зарегистрироваться")))));
  }

  /* Результат: оригинал и перевод рядом (на телефоне — вкладками). */
  const segs = (project && project.segments) || [];
  const empty = segs.filter(s => !(s.target || "").trim()).length;
  const guest = !!(me && me.guest);
  return React.createElement("div", { className: "guest-result" },
    React.createElement("div", { className: "guest-top" }, head,
      React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
        !guest && React.createElement("button", { type: "button", className: "linklike", onClick: openApp },
          TR("Открыть приложение")))),
    React.createElement("div", { className: "guest-bar card card-pad" },
      React.createElement("div", null,
        React.createElement("h1", { style: { margin: 0, fontSize: "var(--fs-h2, 20px)" } }, TR("Готово")),
        React.createElement("div", { className: "dim", style: { fontSize: 13.5, marginTop: 4 } },
          segs.length ? guestPartNote(project, info) : TR("Текста в файле не нашлось — попробуйте другой файл."),
          empty ? " " + TR("Не переведено строк: ") + empty + "." : "")),
      React.createElement(Btn, { variant: guest ? "primary" : "secondary", icon: "download", disabled: !segs.length,
        onClick: () => download() },
        guest ? TR("Скачать перевод") : TR("Скачать файл"))),
    why && React.createElement("div", { className: "guest-err", role: "alert", style: { marginTop: 0 } }, guestWhyText(why)),
    guest && React.createElement("p", { className: "dim guest-wall" },
      TR("Скачать файл в исходной вёрстке можно после короткой регистрации: почта и код из письма. ")
      + ((info && info.signupPages) ? TR("После неё — ещё ") + info.signupPages + TR(" стр. бесплатно.") : "")),
    !guest && project && React.createElement(GuestRest, { project, toast,
      onRun: async () => { await window.API.trialRest(project.id); await run(project.id); } }),
    !guest && me && me.noPassword && React.createElement("details", { className: "guest-pw" },
      React.createElement("summary", null, TR("Задайте пароль, чтобы вернуться")),
      React.createElement("div", { className: "row row-wrap", style: { gap: 8, marginTop: 8 } },
        React.createElement(Input, { type: "password", autoComplete: "new-password", value: pw, placeholder: TR("Новый пароль, от 8 знаков"),
          onChange: (e) => setPw(e.target.value), style: { flex: "1 1 220px", fontSize: 16 } }),
        React.createElement(Btn, { variant: "secondary", disabled: pw.length < 8, onClick: savePw }, TR("Сохранить"))),
      React.createElement("div", { className: "dim", style: { fontSize: 12, marginTop: 6 } },
        TR("Можно и потом: на экране входа — «Забыли пароль?», код придёт на почту."))),
    React.createElement("div", { className: "guest-tabs row", role: "tablist" },
      ["src", "tgt"].map(k => React.createElement("button", { key: k, role: "tab", "aria-selected": view === k,
        className: "btn btn-ghost btn-sm" + (view === k ? " is-on" : ""), onClick: () => setView(k) },
        k === "src" ? TR("Оригинал") : TR("Перевод")))),
    React.createElement("div", { className: "guest-cols card", "data-view": view },
      React.createElement("div", { className: "guest-row guest-headrow" },
        React.createElement("div", { className: "gc-src" }, TR("Оригинал")),
        React.createElement("div", { className: "gc-tgt" }, TR("Перевод"))),
      segs.slice(0, GUEST_ROWS_MAX).map(s => React.createElement("div", { key: s.id, className: "guest-row" },
        React.createElement("div", { className: "gc-src", lang: (project.src || "").toLowerCase() }, s.source),
        React.createElement("div", { className: "gc-tgt", dir: "auto", lang: (project.tgt || "").toLowerCase() },
          (s.target || "").trim() ? s.target : React.createElement("span", { className: "dim" }, "—")))),
      segs.length > GUEST_ROWS_MAX && React.createElement("div", { className: "guest-row" },
        React.createElement("div", { className: "dim" }, TR("Ещё строк: ") + (segs.length - GUEST_ROWS_MAX)
          + TR(" — весь текст в скачанном файле и в приложении.")))),
    claim && React.createElement(GuestClaim, { onClose: () => setClaim(false), onLogin: toLogin,
      onDone: (m) => { setMe(m); setClaim(false);
        const gr = guestRead() || {}; delete gr.key; gr.converted = true; guestWrite(gr); toast.success(TR("Готово"), TR("Почта подтверждена — файл скачивается."));
        setTimeout(() => { download(true); }, 50); } }));
}
