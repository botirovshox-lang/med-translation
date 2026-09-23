/* Знакомство и поддержка: два виджета, которые живут ПОВЕРХ вкладок.
   Оба рисуются из App (app.jsx) рядом с оболочкой, а не внутри вкладки:
   тур показывает ПУНКТЫ МЕНЮ, то есть то, что вкладке не принадлежит,
   а виджет поддержки обязан быть виден на любом экране.

   ─── Знакомство (WelcomeTour) ───────────────────────────────────────
   Четыре шага, и каждый ПОДСВЕЧИВАЕТ настоящий элемент интерфейса:
   затемнение с дырой ровно по его рамке и подсказка рядом. Модальное окно
   с четырьмя картинками было бы проще, но оно отвечает на вопрос «что умеет
   сервис», а человеку в первый раз нужен другой ответ — «куда нажать».

   Три правила, которые нельзя ослаблять:

   1. **«Прошёл» лежит НА УЧЁТНОЙ ЗАПИСИ** (`me.tourDone`), а не
      в localStorage: тур встречал бы человека заново на каждом новом
      компьютере — тот же закон, что у языка интерфейса (инвариант 19).
      Крестик — тоже ответ, и он пишется туда же: «не хочу» система обязана
      запомнить с первого раза.

   2. **Шаг без цели ПРОПУСКАЕТСЯ, а не показывает дыру в пустоте.**
      Пункты меню зависят от роли (у переводчика нет «Организации»),
      вёрстка — от ширины окна, а на телефоне меню вообще лежит лентой.
      Цель ищется по `data-tour` в живом DOM на каждом шаге; не нашлась —
      подсказка встаёт по центру экрана без подсветки. Врать стрелкой,
      указывающей в пустоту, хуже, чем не указывать вовсе.

   3. **Рамка цели пересчитывается на прокрутку и на смену размера окна.**
      Дыра, застывшая на месте, — это подсветка чужого элемента.

   ─── Поддержка (SupportWidget) ──────────────────────────────────────
   Диалог за входом: человек известен, организация известна (инвариант 11).
   История живёт на сервере (`backend/support.py`), владелец отвечает
   из Telegram, ответ приходит в тот же тред.

   Опрос — ТОЛЬКО когда есть чего ждать и только пока вкладка видна:
   воркер один (инвариант 1), и виджет, опрашивающий сервер всегда,
   держал бы его ради экрана, на котором ничего не происходит. */

/* Сколько ждать между опросами, пока окно открыто. 12 с — это «ответ
   виден почти сразу» и при этом пять запросов в минуту на человека,
   а не тридцать. */
const SUP_POLL_MS = 12000;

function supTime(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (e) { return ""; }
}

function SupportWidget({ store, toast }) {
  const [open, setOpen] = useState(false);
  const [thread, setThread] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(true);
  const bodyRef = useRef(null);

  const unread = (thread && thread.unread) || 0;
  const msgs = (thread && thread.msgs) || [];

  /* Первый заход — один запрос при монтировании: значок обязан показать
     непрочитанный ответ ДО того, как виджет откроют. */
  useEffect(() => {
    let dead = false;
    window.API.support().then(r => {
      if (dead || !r || !r.ok) return;
      setThread(r.thread); setLive(r.live !== false);
    }, () => {});
    return () => { dead = true; };
  }, []);

  /* Опрос: пока окно открыто ИЛИ пока ждём ответа на своё последнее
     сообщение. Закрытый виджет без заданного вопроса не опрашивает
     ничего — там и ждать нечего. */
  const waiting = msgs.length > 0 && msgs[msgs.length - 1].by === "user";
  useEffect(() => {
    if (!open && !waiting) return;
    let dead = false, timer = null;
    const tick = () => {
      if (dead || document.hidden) { timer = setTimeout(tick, SUP_POLL_MS); return; }
      window.API.support().then(r => {
        if (dead || !r || !r.ok) return;
        setThread(r.thread); setLive(r.live !== false);
        timer = setTimeout(tick, SUP_POLL_MS);
      }, () => { if (!dead) timer = setTimeout(tick, SUP_POLL_MS); });
    };
    timer = setTimeout(tick, SUP_POLL_MS);
    return () => { dead = true; clearTimeout(timer); };
  }, [open, waiting]);

  /* Открыть виджет умеет любой экран: событие, а не проп через всю
     оболочку. Кнопка «Написать в поддержку» стоит на вкладке «Обучение»
     (и встанет ещё где-нибудь), а тянуть состояние виджета через App,
     Sidebar и вкладку значило бы связать их всех ради одного нажатия. */
  useEffect(() => {
    const h = () => setOpen(true);
    window.addEventListener("mct-support-open", h);
    return () => window.removeEventListener("mct-support-open", h);
  }, []);

  /* Открыли — гасим счётчик непрочитанного: человек их видит. */
  useEffect(() => {
    if (!open || !unread) return;
    window.API.supportRead().then(r => { if (r && r.ok) setThread(r.thread); }, () => {});
  }, [open, unread]);

  /* Прокрутка к последнему сообщению. Не «плавно»: при открытии плавная
     прокрутка показывает середину переписки, а нужен конец. */
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [open, msgs.length]);

  const send = () => {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    window.API.supportSend(t).then(r => {
      setBusy(false);
      if (r && r.ok) { setThread(r.thread); setText(""); }
    }, (e) => {
      setBusy(false);
      toast && toast.error(TR("Не отправилось"), (e && e.message) || TR("Попробуйте ещё раз."));
    });
  };

  return React.createElement("div", { className: "sup" },
    React.createElement("button", {
      className: "sup-fab", onClick: () => setOpen(v => !v),
      "aria-label": open ? TR("Закрыть поддержку") : TR("Написать в поддержку"),
      "aria-expanded": open,
    },
      React.createElement(Icon, { name: open ? "close" : "message", size: 21 }),
      !open && unread > 0 && React.createElement("i", { className: "sup-dot" }, unread)),
    open && React.createElement("section", { className: "sup-panel", "aria-label": TR("Поддержка") },
      React.createElement("header", { className: "sup-head" },
        React.createElement("div", null,
          React.createElement("b", null, TR("Поддержка")),
          React.createElement("span", null, live
            ? TR("Обычно отвечаем в течение рабочего дня.")
            : TR("Ответ придёт на вашу почту."))),
        React.createElement(IconBtn, {
          icon: "close", label: TR("Закрыть"), sm: true, onClick: () => setOpen(false) })),
      React.createElement("div", { className: "sup-body", ref: bodyRef },
        msgs.length === 0 && React.createElement("p", { className: "sup-empty" },
          TR("Напишите, что не получается. Мы читаем каждое сообщение.")),
        msgs.map((m, i) => React.createElement("div", {
          key: i, className: "sup-msg " + (m.by === "user" ? "mine" : "theirs"),
        },
          React.createElement("p", null, m.text),
          React.createElement("time", null, supTime(m.at))))),
      React.createElement("form", {
        className: "sup-form",
        onSubmit: (e) => { e.preventDefault(); send(); },
      },
        React.createElement("textarea", {
          value: text, rows: 2, placeholder: TR("Ваше сообщение"),
          onChange: (e) => setText(e.target.value),
          /* Enter отправляет, Shift+Enter — перенос строки: так ведут себя
             все мессенджеры, и переучивать человека тут не за чем. */
          onKeyDown: (e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
          },
        }),
        React.createElement("button", {
          className: "btn btn-primary", type: "submit", disabled: busy || !text.trim(),
          "aria-label": TR("Отправить"),
        }, React.createElement(Icon, { name: "send", size: 16 })))));
}

/* ─── Знакомство ───────────────────────────────────────────────────── */

/* Шаги. `sel` — что подсветить (ищется в живом DOM по data-tour),
   и шаг без найденной цели показывается по центру, а не пропадает:
   текст шага полезен и без указателя. */
const TOUR_STEPS = [
  {
    sel: "import",
    title: TR("Принесите файл"),
    text: TR("Word, PDF, Excel, PowerPoint, картинки и сканы. Формат не важен — документ вернётся в своём."),
  },
  {
    sel: "editor",
    title: TR("Нажмите одну кнопку"),
    text: TR("Перевод и все проверки идут одной командой. Вкладку можно закрыть: работа идёт на сервере."),
  },
  {
    sel: "preflight",
    title: TR("Посмотрите, что вышло"),
    text: TR("Крупный процент готовности и три корзины: что готово, что машина доделает сама и о чём спросит вас."),
  },
  {
    sel: "export",
    title: TR("Заберите документ"),
    text: TR("Файл возвращается в исходном оформлении: стили, таблицы, рисунки и оглавление на своих местах."),
  },
];

/* Рамка цели в координатах окна. null — цели нет (роль не та, узкий экран,
   вкладка ещё не нарисована): тогда подсказка встаёт по центру. */
function tourRect(sel) {
  const el = document.querySelector('[data-tour="' + sel + '"]');
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

function WelcomeTour({ store, onDone }) {
  const [i, setI] = useState(0);
  const step = TOUR_STEPS[i];
  const [rect, setRect] = useState(() => tourRect(step.sel));

  /* Рамка пересчитывается на смене шага, на прокрутке и на смене размера:
     застывшая дыра подсвечивает чужой элемент. */
  useEffect(() => {
    const recalc = () => setRect(tourRect(TOUR_STEPS[i].sel));
    recalc();
    /* Ещё раз следующим кадром: вкладка могла ещё не дорисоваться. */
    const raf = requestAnimationFrame(recalc);
    window.addEventListener("resize", recalc);
    window.addEventListener("scroll", recalc, true);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", recalc);
      window.removeEventListener("scroll", recalc, true);
    };
  }, [i]);

  useEffect(() => {
    const h = (e) => {
      if (e.key === "Escape") onDone();
      if (e.key === "ArrowRight" || e.key === "Enter") next();
      if (e.key === "ArrowLeft") setI(v => Math.max(0, v - 1));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  const last = i === TOUR_STEPS.length - 1;
  const next = () => { if (last) onDone(); else setI(v => v + 1); };

  const PAD = 6;
  const hole = rect ? {
    top: rect.top - PAD, left: rect.left - PAD,
    width: rect.width + PAD * 2, height: rect.height + PAD * 2,
  } : null;

  /* Подсказка рядом с целью: под ней, если внизу есть место, иначе над.
     Без цели — по центру экрана. */
  let tipStyle = { left: "50%", top: "50%", transform: "translate(-50%,-50%)" };
  if (hole) {
    const below = hole.top + hole.height + 14;
    const room = window.innerHeight - below > 190;
    tipStyle = room
      ? { top: below + "px", left: Math.max(12, hole.left) + "px" }
      : { top: Math.max(12, hole.top - 190) + "px", left: Math.max(12, hole.left) + "px" };
  }

  return React.createElement("div", { className: "tour", role: "dialog", "aria-modal": "true" },
    /* Затемнение дырой: четыре прямоугольника вокруг цели, а не clip-path —
       так подсвеченный элемент остаётся НАЖИМАЕМЫМ, и человек может
       попробовать прямо сейчас. */
    hole
      ? [
        { key: "t", top: 0, left: 0, right: 0, height: Math.max(0, hole.top) },
        { key: "b", top: hole.top + hole.height, left: 0, right: 0, bottom: 0 },
        { key: "l", top: hole.top, left: 0, width: Math.max(0, hole.left), height: hole.height },
        { key: "r", top: hole.top, left: hole.left + hole.width, right: 0, height: hole.height },
      ].map(s => React.createElement("div", { key: s.key, className: "tour-veil", style: s }))
      : React.createElement("div", {
        className: "tour-veil", style: { inset: 0 },
      }),
    hole && React.createElement("div", {
      className: "tour-ring", "aria-hidden": "true",
      style: { top: hole.top + "px", left: hole.left + "px",
               width: hole.width + "px", height: hole.height + "px" },
    }),
    React.createElement("div", { className: "tour-tip", style: tipStyle },
      React.createElement("p", { className: "tour-n" },
        TRS ? TR("Шаг") + " " + (i + 1) + " / " + TOUR_STEPS.length
            : (i + 1) + " / " + TOUR_STEPS.length),
      React.createElement("h3", null, step.title),
      React.createElement("p", { className: "tour-txt" }, step.text),
      React.createElement("div", { className: "tour-act" },
        React.createElement("button", { className: "btn btn-ghost", onClick: onDone },
          TR("Пропустить")),
        React.createElement("button", { className: "btn btn-primary", onClick: next },
          last ? TR("Понятно") : TR("Далее")))));
}

/* Показываем один раз и только когда знаем ответ: `me` ещё не приехал —
   ждём. Нарисовать тур и тут же убрать его, когда придёт `tourDone: true`,
   значит мигнуть затемнением на весь экран человеку, который его уже
   закрывал. */
function OnboardingLayer({ store, toast }) {
  const me = store.me || null;
  const [done, setDone] = useState(false);
  /* Показ ПО ПРОСЬБЕ — отдельно от «ещё не видел». Кнопка «Показать
     знакомство заново» на вкладке «Обучение» шлёт событие, и тур идёт
     поверх любого экрана; сбрасывать ради этого `tourDone` на записи
     нельзя — флаг отвечает на вопрос «видел ли человек тур», а не
     «показываем ли его сейчас». */
  const [asked, setAsked] = useState(false);
  const show = asked || (!!me && !me.tourDone && !done);

  useEffect(() => {
    const h = () => { setAsked(true); setDone(false); };
    window.addEventListener("mct-tour-open", h);
    return () => window.removeEventListener("mct-tour-open", h);
  }, []);

  const finish = () => {
    setAsked(false);
    setDone(true);
    /* Ответ сервера не ждём и ошибку не показываем: тур закрыт в браузере
       в любом случае, а не записавшийся флаг покажет его ещё раз — это
       досадно, но не потеря работы. */
    /* Запись трогаем только когда тур шёл САМ: повторный показ
       по просьбе ничего не меняет — человек его и так уже видел. */
    if (me && !me.tourDone) {
      window.API.profileSave({ tourDone: true }).then(
        r => { if (r && r.ok && store.setMe) store.setMe(r.me); }, () => {});
    }
  };

  return React.createElement(React.Fragment, null,
    show && React.createElement(WelcomeTour, { store, onDone: finish }),
    React.createElement(SupportWidget, { store, toast }));
}
