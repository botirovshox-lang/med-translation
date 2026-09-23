/* Вкладка «Обучение»: пять шагов, частые вопросы и три действия.
 *
 * СОДЕРЖАНИЕ ПРИХОДИТ С СЕРВЕРА (`GET /api/tutorial`), и это несущее
 * решение: те же тексты и те же рисунки рисует публичная страница
 * `/tutorial` (`backend/tutorial.py`). Вторая копия здесь разошлась бы
 * с первой же правкой — а расхождение значит, что инструкция врёт
 * про наш же интерфейс. Язык сервер берёт из сессии сам.
 *
 * РИСУНКИ — ГОТОВЫЙ SVG с сервера, вставленный через dangerouslySetInnerHTML.
 * Слово страшное, но источник тут НАШ и единственный: строку собирает
 * `tutorial._shot` из закрытого списка схем, текста клиента в ней нет
 * ни байта, и наружу она не выходит. Рисовать те же рамки и стрелки
 * второй раз в браузере значило бы держать два рисовальщика на одну схему.
 * Цвета в SVG заданы через `var(--…)`, поэтому в светлой и тёмной теме
 * рисунок живёт сам.
 *
 * Облик — НАШ, а не как у страницы `/tutorial`: `.page`, `.card`, наши
 * переменные. Страница снаружи нарисована в облике анкет (рисованный
 * шрифт, тёмный фон) намеренно — её читают до входа, вперемешку
 * с письмами бота; внутри сервиса такой облик выглядел бы чужим.
 */

/* Одно нажатие — одно событие. Виджет поддержки и тур слушают их сами
   (onboarding.jsx): тянуть их состояние через App, Sidebar и вкладку
   значило бы связать три файла ради одной кнопки. */
function learnFire(name) {
  try { window.dispatchEvent(new Event(name)); } catch (e) { /* очень старый браузер */ }
}

function LearnStep({ n, word, step }) {
  return React.createElement("article", { className: "card card-pad learn-step" },
    React.createElement("div", { className: "learn-n" },
      React.createElement("span", null, String(n).padStart(2, "0"))),
    React.createElement("div", { className: "learn-body" },
      React.createElement("p", { className: "learn-kicker" }, word + " " + n),
      React.createElement("h2", null, step.title),
      /* Абзацы приходят уже с <b> внутри — это наш текст из tutorial.py,
         а не ввод человека. */
      step.paras.map((p, i) => React.createElement("p", {
        key: i, className: "learn-p", dangerouslySetInnerHTML: { __html: p },
      })),
      step.svg && React.createElement("div", {
        className: "learn-shot", dangerouslySetInnerHTML: { __html: step.svg },
      })));
}

function LearnFaq({ head, items }) {
  if (!items || !items.length) return null;
  /* Раскрывашка — ОБЩАЯ (`Expander` из ui.jsx), а не своя: у неё уже есть
     и облик, и поворот стрелки, и aria-expanded. Своя копия разошлась бы
     с остальными экранами первой же правкой облика. */
  return React.createElement("section", { className: "learn-faq" },
    React.createElement("h2", { className: "learn-h2" }, head),
    items.map((it, i) => React.createElement(Expander, { key: i, title: it.q },
      React.createElement("p", { className: "learn-a" }, it.a))));
}

function LearnActions({ a }) {
  if (!a) return null;
  /* Три действия в ряд. «Знакомство» первым: это самое частое, зачем
     сюда приходят второй раз. */
  const items = [
    { icon: "target", label: a.tour, note: a.tourNote,
      onClick: () => learnFire("mct-tour-open") },
    { icon: "message", label: a.support, note: a.supportNote,
      onClick: () => learnFire("mct-support-open") },
    { icon: "link", label: a.print, note: a.printNote,
      href: "/tutorial" },
  ];
  return React.createElement("div", { className: "learn-acts" },
    items.map((it, i) => {
      const inner = [
        React.createElement("span", { key: "i", className: "learn-act-ic" },
          React.createElement(Icon, { name: it.icon, size: 16 })),
        React.createElement("span", { key: "t", className: "learn-act-t" },
          React.createElement("b", null, it.label),
          React.createElement("span", null, it.note)),
      ];
      return it.href
        ? React.createElement("a", {
            key: i, className: "card card-pad-sm card-hover learn-act",
            href: it.href, target: "_blank", rel: "noopener",
          }, inner)
        : React.createElement("button", {
            key: i, className: "card card-pad-sm card-hover learn-act",
            onClick: it.onClick,
          }, inner);
    }));
}

function TabLearn({ store, toast }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let dead = false;
    window.API.tutorial().then(r => {
      if (dead) return;
      if (r && r.ok) setData(r); else setFailed(true);
    }, () => { if (!dead) setFailed(true); });
    return () => { dead = true; };
  }, []);

  if (failed) {
    /* Молчать нельзя: пустой экран неотличим от «инструкции нет».
       Ссылка на страницу остаётся — она не зависит от этой двери. */
    return React.createElement("div", { className: "page" },
      React.createElement("div", { className: "page-head" },
        React.createElement("h1", null, TR("Обучение"))),
      React.createElement("p", { className: "dim" },
        TR("Не удалось загрузить инструкцию.")),
      React.createElement("a", { className: "btn", href: "/tutorial", target: "_blank", rel: "noopener" },
        TR("Открыть отдельной страницей")));
  }
  if (!data) return React.createElement("div", { className: "page" },
    React.createElement("p", { className: "dim" }, TR("Загружаем инструкцию…")));

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, data.h1),
      React.createElement("p", { className: "lead" }, data.lede)),
    data.facts && data.facts.length > 0 && React.createElement("ul", { className: "learn-facts" },
      data.facts.map((f, i) => React.createElement("li", { key: i }, f))),
    React.createElement(LearnActions, { a: data.actions }),
    React.createElement("div", { className: "col learn-steps", style: { gap: 12 } },
      (data.steps || []).map((s, i) => React.createElement(LearnStep, {
        key: s.key || i, n: i + 1, word: data.stepWord, step: s }))),
    React.createElement(LearnFaq, { head: data.faqHead, items: data.faq }));
}

window.TabLearn = TabLearn;
