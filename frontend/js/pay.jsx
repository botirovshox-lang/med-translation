/* ============================================================
   Оплата (инвариант 39): карточка «Пополнить баланс» на экране организации
   и полоса «нечем платить — пополните» в оболочке.
   Суммы, курсы и цены считает СЕРВЕР (/api/pay, /api/pay/quote): цена
   в .jsx была бы вторым прайс-листом рядом с настоящим. Здесь — только
   показ и выбор. Право СДЕЛАТЬ (завести заказ) — у владельца, на сервере.
   ============================================================ */

/* Сумма с разрядами и валютой. Сервер отдаёт строку: сумы и тенге целые,
   доллары — с центами. */
function payFmt(amount, cur) {
  const n = Number(amount || 0);
  const s = cur === "USD" ? n.toFixed(2) : String(Math.round(n));
  const [a, b] = s.split(".");
  const g = a.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const num = b ? g + "." + b : g;
  return cur === "USD" ? "$" + num : cur === "KZT" ? num + " ₸" : num + " " + TR("сум");
}

const PAY_METHOD_LABEL = {
  card: () => TR("Банковская карта"),
  click: () => "Click",
  payme: () => "Payme",
  kaspi: () => "Kaspi",
};

/* Статус заказа — код с сервера, подпись даёт браузер (инвариант 17). */
function payStatusText(st) {
  return st === "paid" ? TR("оплачен") : st === "cancelled" ? TR("отменён")
    : st === "expired" ? TR("срок истёк") : TR("ждёт оплаты");
}

function PayCard({ toast, onPaid, onState }) {
  const [st, setSt] = useState(null);
  const [pages, setPages] = useState(0);
  const [minutes, setMinutes] = useState(0);
  const [method, setMethod] = useState("");
  const [quote, setQuote] = useState(null);
  const [qErr, setQErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  /* Согласие с офертой ДО перехода к оплате — требование банка-эквайера
     (Октобанк, «Процедура подключения», п. IV.7). Не запоминается: это
     акцепт конкретного заказа, а не настройка. */
  const [agree, setAgree] = useState(false);
  const ref = useRef(null);
  const reload = () => window.API.safeCall(() => window.API.payState()).then(r => {
    if (!r || !r.ok) return;
    setSt(r);
    if (onState) onState(r);
    setMethod(m => m || (((r.methods || []).find(x => x.online) || (r.methods || [])[0] || {}).id || ""));
  });
  useEffect(() => { reload(); }, []);
  /* Пришли с отказа «нечем платить»: подставить нехватку и показать карточку. */
  useEffect(() => {
    const take = (d) => {
      if (!d) return;
      if (d.minutes) setMinutes(Math.max(1, Math.ceil(Number(d.minutes))));
      if (d.pages) setPages(Math.max(1, Math.ceil(Number(d.pages))));
      setTimeout(() => { try { ref.current && ref.current.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (e) {} }, 50);
    };
    take(window._mcat_payIntent); window._mcat_payIntent = null;
    const h = (e) => take(e.detail || {});
    window.addEventListener("mct-pay-open", h);
    return () => window.removeEventListener("mct-pay-open", h);
  }, []);
  useEffect(() => {
    if (!st || !method || (!pages && !minutes)) { setQuote(null); setQErr(""); return; }
    let alive = true;
    const t = setTimeout(() => {
      window.API.payQuote({ pages: pages || 0, minutes: minutes || 0, method })
        .then(r => {
          if (alive) { setQuote(r.quote); setQErr(""); }
          /* Сумму к оплате увидели (`ui.pay.quote`) — против заявок это
             «сколько посмотрели цену и ушли». */
          if (window.TELEMETRY) window.TELEMETRY.ui("pay.quote");
        })
        .catch(e => { if (alive) { setQuote(null); setQErr(e.message || String(e)); } });
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [pages, minutes, method, st]);

  if (!st) return null;
  const methods = st.methods || [], packs = st.packs || {};
  const pay = async () => {
    setBusy(true);
    try {
      const r = await window.API.payOrder({ pages: pages || 0, minutes: minutes || 0, method });
      const o = r.order;
      setDone(o);
      reload();
      if (o.url && o.online) { window.location.assign(o.url); return; }
      if (o.online && !o.url) toast.error(TR("Платёжная страница не открылась"),
        TR("Нажмите «Оплатить» у заказа ниже через минуту или выберите другой способ."));
      if (o.url) window.open(o.url, "_blank", "noopener");
    } catch (e) { toast.error(TR("Заказ не создан"), e.message || String(e)); }
    setBusy(false);
  };
  const payable = st.payable || {};
  const head = React.createElement("div", { className: "row between row-wrap", style: { gap: 8 } },
    React.createElement("h2", { className: "section-title", style: { margin: 0 } }, TR("Пополнить баланс")),
    React.createElement(PayAcceptStrip, null));
  if (!payable.pages && !payable.minutes)
    return React.createElement("div", { ref, className: "card card-pad pay-card", style: { fontSize: 13 } }, head,
      React.createElement("p", { className: "dim", style: { margin: "8px 0 0" } },
        TR("Ваша организация работает без предоплаты: оплата — по договору с администратором сервиса.")));
  const chip = (v, cur, set) => React.createElement("button", {
    key: v, className: "btn btn-ghost btn-sm" + (cur === v ? " is-on" : ""), "aria-pressed": cur === v,
    onClick: () => set(cur === v ? 0 : v) }, String(v));
  const qty = (label, val, set, packs, max, on) => React.createElement(Field, { label },
    React.createElement("div", { className: "row row-wrap", style: { gap: 6, alignItems: "center" } },
      React.createElement(Input, { type: "number", min: 0, max, step: 1, value: val || "", disabled: !on,
        placeholder: "0", style: { width: 110, fontSize: 16 },
        onChange: (e) => set(Math.max(0, Math.min(max, parseInt(e.target.value || "0", 10) || 0))) }),
      on ? (packs || []).map(v => chip(v, val, set)) : null));
  const meth = methods.find(x => x.id === method) || {};
  return React.createElement("div", { ref, className: "card card-pad pay-card", style: { display: "flex", flexDirection: "column", gap: 12, fontSize: 13 } },
    head,
    React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
      qty(TR("1. Сколько страниц купить"), pages, setPages, packs.pages, (st.limits || {}).pages || 10000, payable.pages),
      qty(TR("Сколько минут видео купить"), minutes, setMinutes, packs.minutes, (st.limits || {}).minutes || 3000, payable.minutes)),
    React.createElement("div", { className: "dim", style: { fontSize: 12 } },
      TR("Страница — 250 слов исходника. Видео считается минутами распознаваемого отрезка: неполная минута — минута, озвучка входит в цену.")
      + (st.wpmMax ? TR(" Если речь быстрее ") + st.wpmMax + TR(" слов в минуту, минуты считаются по словам.") : "")),
    React.createElement("div", { className: "pay-step" }, TR("2. Как заплатить")),
    React.createElement("div", { role: "radiogroup", "aria-label": TR("Способ оплаты"), className: "pay-methods" },
      methods.map(x => React.createElement("label", { key: x.id, className: "pay-method" + (method === x.id ? " is-on" : "") },
        React.createElement("input", { type: "radio", name: "pay-method", value: x.id, checked: method === x.id,
          onChange: () => setMethod(x.id) }),
        React.createElement("span", { className: "pay-method-text" },
          React.createElement(PayMethodIcons, { method: x.id }),
          React.createElement("b", null, (PAY_METHOD_LABEL[x.id] || (() => x.id))()),
          React.createElement("span", { className: "dim" },
            x.online ? TR("онлайн, сразу") : TR("по счёту: подтвердим после поступления")))))),
    meth.note && !meth.online ? React.createElement("div", { className: "dim", style: { whiteSpace: "pre-wrap" } }, meth.note) : null,
    React.createElement("div", { className: "pay-step" }, TR("3. Подтвердите и оплатите")),
    React.createElement("label", { className: "row", style: { gap: 8, alignItems: "flex-start", fontSize: 14 } },
      React.createElement("input", { type: "checkbox", checked: agree, style: { marginTop: 3 },
        onChange: (e) => setAgree(e.target.checked) }),
      React.createElement("span", null, TR("Я ознакомлен(а) и принимаю условия "),
        React.createElement("a", { href: "/terms", target: "_blank", rel: "noopener" }, TR("публичной оферты")),
        TR(", включая порядок оплаты и возврата средств"))),
    /* Итог — отдельной плашкой, крупно, и кнопка рядом с суммой: это
       то, ради чего человек пришёл на экран, и найти его глазами надо
       сразу, а не строкой среди подсказок. */
    React.createElement("div", { className: "pay-total" + (quote ? " is-ready" : "") },
      React.createElement("div", { className: "pay-total-l" },
        React.createElement("span", { className: "pay-total-k" }, TR("К оплате")),
        React.createElement("span", { className: "pay-total-v" }, quote ? payFmt(quote.amount, quote.currency) : "—"),
        React.createElement("span", { className: "pay-total-hint" },
          quote ? [pages ? pages + TR(" стр.") : "", minutes ? minutes + TR(" мин") : ""].filter(Boolean).join(" + ")
                  + (meth.id ? " · " + (PAY_METHOD_LABEL[meth.id] || (() => meth.id))() : "")
                : (qErr || TR("Выберите, сколько страниц или минут покупаете")))),
      React.createElement(Btn, { variant: "primary", size: "lg", disabled: !quote || busy || !agree, onClick: pay },
        busy ? TR("Создаём заказ…") : TR("Оплатить"))),
    quote && !agree ? React.createElement("div", { className: "dim", style: { textAlign: "right" } },
      TR("Поставьте галочку согласия — кнопка «Оплатить» станет доступна.")) : null,
    done && !done.online ? React.createElement("div", { className: "pay-done" },
      TR("Заявка №") + done.id + TR(" принята: ") + payFmt(done.amount, done.currency) + ". "
      + (done.url ? TR("Ссылка на оплату открыта в новой вкладке.") : TR("Мы пришлём ссылку или реквизиты для оплаты."))
      + TR(" Баланс пополнится после поступления оплаты.")) : null,
    null);
}

/* Полоса в оболочке: отказ «нечем платить» с любого экрана и возврат
   с кассы платёжной системы (`/?pay=N`). */
function PayNeedBar({ store, toast }) {
  const [need, setNeed] = useState(null);
  const [ret, setRet] = useState(null);
  useEffect(() => {
    const h = (e) => setNeed(e.detail || { kind: "pages" });
    window.addEventListener("mct-pay-need", h);
    return () => window.removeEventListener("mct-pay-need", h);
  }, []);
  /* Возврат с кассы: номер заказа в адресе. Статус спрашиваем несколько раз —
     колбэк платёжной системы приходит чуть позже человека. */
  useEffect(() => {
    let oid = null;
    try { oid = new URLSearchParams(window.location.search).get("pay"); } catch (e) { oid = null; }
    if (!oid || !/^\d+$/.test(oid)) return;
    try {
      const u = new URL(window.location.href); u.searchParams.delete("pay");
      window.history.replaceState(null, "", u.pathname + u.search + u.hash);
    } catch (e) { /* адрес не поправили — не беда */ }
    let tries = 0, alive = true;
    const tick = () => window.API.payOrderGet(oid).then(r => {
      if (!alive || !r || !r.order) return;
      setRet(r.order);
      /* Оплата прошла — то, что ждало её (файл, перевод), продолжается само. */
      if (r.order.status === "paid") {
        if (window.MCT_HANDOFF) window.MCT_HANDOFF.markPaid();
        try { window.dispatchEvent(new CustomEvent("mct-pay-paid", { detail: { order: r.order.id } })); } catch (e) {}
      }
      if (r.order.status === "new" && ++tries < 20) setTimeout(tick, 3000);
    }).catch(() => {});
    tick();
    return () => { alive = false; };
  }, []);
  const owner = !!(store.can && store.can.owner);
  const open = () => {
    window._mcat_payIntent = need && need.kind === "minutes" && need.need
      ? { minutes: Math.max(1, Number(need.need) - Math.max(0, Number(need.left || 0))) }
      : need && need.kind === "pages" && need.short ? { pages: need.short } : null;
    setNeed(null);
    store.go("pay");
    try { window.dispatchEvent(new CustomEvent("mct-pay-open", { detail: window._mcat_payIntent || {} })); } catch (e) {}
  };
  const close = (set) => React.createElement("button", { className: "btn btn-ghost btn-sm", "aria-label": TR("Закрыть"),
    onClick: () => set(null) }, "×");
  const bars = [];
  if (need) {
    const what = need.kind === "minutes" ? TR("Минут видео не хватает")
      + (need.need != null ? ": " + TR("нужно ") + need.need + TR(" мин, осталось ") + Math.max(0, Number(need.left || 0)) : "") + "."
      : need.kind === "spend" ? TR("Перевод сейчас приостановлен. Пополнение баланса снимает остановку.")
      : TR("Страницы на балансе закончились.");
    bars.push(React.createElement("div", { key: "need", className: "pay-bar", role: "status" },
      React.createElement("span", null, what + " "
        + (owner ? "" : TR("Попросите владельца организации пополнить баланс."))),
      owner ? React.createElement(Btn, { variant: "primary", size: "sm", onClick: open }, TR("Пополнить")) : null,
      close(setNeed)));
  }
  if (ret) {
    const txt = ret.status === "paid" ? TR("Оплата №") + ret.id + TR(" прошла — баланс пополнен.")
      : ret.status === "new" ? TR("Оплата №") + ret.id + TR(": ждём подтверждения от платёжной системы. Обычно это минута.")
      : TR("Оплата №") + ret.id + ": " + payStatusText(ret.status) + ".";
    bars.push(React.createElement("div", { key: "ret", className: "pay-bar" + (ret.status === "paid" ? " is-ok" : ""), role: "status" },
      React.createElement("span", null, txt), close(setRet)));
  }
  return bars.length ? React.createElement(React.Fragment, null, bars) : null;
}

/* ---------- Сколько стоит остаток ----------
   Денег-кошелька в системе нет: клиент покупает страницы и минуты. «Баланс
   в деньгах» — это ОСТАТОК, пересчитанный СЕРВЕРОМ по нынешней цене
   пополнения (/api/pay/quote, итог в валюте способа). Своей цены в .jsx нет:
   вторая копия разошлась бы с той, по которой списывают. Спрашивать вправе
   только владелец (`/api/pay` — его дверь), остальным сумма не рисуется. */
const PAY_VAL = { st: null, at: 0, cache: {} };
function payStateCached() {
  if (PAY_VAL.st && Date.now() - PAY_VAL.at < 60000) return PAY_VAL.st;
  PAY_VAL.at = Date.now();
  /* Сбой не кэшируется: следующий показ спросит снова, а не через минуту. */
  PAY_VAL.st = window.API.payState().catch(() => { PAY_VAL.st = null; return null; });
  return PAY_VAL.st;
}
function payValueOf(pages, minutes) {
  const p = Math.max(0, Math.ceil(Number(pages || 0))), m = Math.max(0, Math.ceil(Number(minutes || 0)));
  if (!p && !m) return Promise.resolve(null);
  const key = p + ":" + m;
  if (PAY_VAL.cache[key]) return PAY_VAL.cache[key];
  const pr = payStateCached().then(st => {
    if (!st || !st.ok) return null;
    const meth = (st.methods || []).find(x => x.online) || (st.methods || [])[0];
    if (!meth) return null;
    return window.API.payQuote({ pages: p, minutes: m, method: meth.id })
      .then(r => r && r.quote ? { amount: r.quote.amount, currency: r.quote.currency } : null);
  }).catch(() => null);
  PAY_VAL.cache[key] = pr;
  setTimeout(() => { delete PAY_VAL.cache[key]; }, 60000);
  return pr;
}
/* Сумма за число страниц/минут: null — ещё не знаем или не владелец. */
function usePayValue(store, pages, minutes) {
  const [v, setV] = useState(null);
  const owner = !!(store && store.can && store.can.owner);
  const p = Math.ceil(Number(pages || 0)), m = Math.ceil(Number(minutes || 0));
  useEffect(() => {
    if (!owner || !window.API || !window.API.payState) { setV(null); return; }
    let alive = true;
    payValueOf(p, m).then(r => { if (alive) setV(r); });
    return () => { alive = false; };
  }, [owner, p, m]);
  return v;
}

/* Остаток страниц и минут — тем, что знает /auth/me (store.caps/usage/wallet). */
function payBalance(store) {
  const caps = store.caps || null, usage = store.usage || null;
  const w = store.wallet || {};
  const limited = !!(caps && caps.pagesLimited);
  /* Остаток считает сервер (`usage.left`): в нём учтены и страницы
     картинок, и ручные правки. Своя разность — только запасной ход. */
  const raw = usage && usage.left != null ? Number(usage.left) : (caps && caps.maxPages || 0) - ((usage && usage.pages) || 0);
  const pagesLeft = limited ? Math.max(0, Math.round(raw * 10) / 10) : null;
  const m = w.minutes || null;
  return { limited, pagesLeft, minutes: m && m.wallet ? m : null, over: !!(w.spend && w.spend.over) };
}

/* Плитки «На вашем счёте»: страницы (и минуты) — и сколько это в деньгах.
   Одна плитка на кошелёк: страницы и их стоимость — одно и то же число
   в двух единицах, и разводить их по разным плиткам значило бы считать
   их двумя разными остатками. */
function PayBalanceTiles({ store, onPay }) {
  const b = payBalance(store);
  const pv = usePayValue(store, b.pagesLeft || 0, 0);
  const mv = usePayValue(store, 0, b.minutes ? b.minutes.left : 0);
  const owner = !!(store.can && store.can.owner);
  const tile = (key, label, big, sub, low) => React.createElement("div", { key, className: "bal-tile" + (low ? " is-low" : "") },
    React.createElement("div", { className: "bal-label" }, label),
    React.createElement("div", { className: "bal-big" }, big),
    sub ? React.createElement("div", { className: "bal-sub" }, sub) : null);
  const tiles = [
    tile("p", TR("Страниц на счёте"),
      b.limited ? String(b.pagesLeft) : TR("без ограничения"),
      pv ? "≈ " + payFmt(pv.amount, pv.currency) : null,
      b.limited && b.pagesLeft < 5),
  ];
  if (b.minutes) tiles.push(tile("m", TR("Минут видео на счёте"), String(b.minutes.left),
    mv ? "≈ " + payFmt(mv.amount, mv.currency) : null, b.minutes.left < 1));
  return React.createElement("div", { className: "bal-tiles" }, tiles,
    owner && onPay ? React.createElement("div", { className: "bal-act" },
      React.createElement(Btn, { variant: "secondary", icon: "wallet", onClick: onPay }, TR("Пополнить"))) : null);
}

/* Внизу меню: тот же остаток, коротко. Владельцу — дверь в «Оплату». */
function PaySideBalance({ store }) {
  const b = payBalance(store);
  const pv = usePayValue(store, b.pagesLeft || 0, 0);
  const owner = !!(store.can && store.can.owner);
  if (!b.limited && !b.minutes) return null;
  const caps = store.caps || {}, used = (store.usage && store.usage.pages) || 0;
  const body = [
    React.createElement("div", { key: "p", className: "sf-row" },
      React.createElement("span", null, TR("Страницы")),
      React.createElement("b", null, b.limited ? b.pagesLeft + TR(" осталось") : TR("без ограничения"))),
    pv ? React.createElement("div", { key: "v", className: "sf-row" },
      React.createElement("span", null, TR("это примерно")),
      React.createElement("b", null, payFmt(pv.amount, pv.currency))) : null,
    b.limited && caps.maxPages > 0 ? React.createElement("div", { key: "m", className: "sf-meter" },
      React.createElement("i", { style: { width: Math.min(100, used / caps.maxPages * 100) + "%" } })) : null,
    b.minutes ? React.createElement("div", { key: "mn", className: "sf-row" },
      React.createElement("span", null, TR("Минуты видео")),
      React.createElement("b", null, b.minutes.left + TR(" осталось"))) : null,
    b.limited && b.pagesLeft < 5 && owner ? React.createElement("div", { key: "low", className: "sf-low" }, TR("Мало — пополнить")) : null,
  ];
  return owner
    ? React.createElement("button", { type: "button", className: "side-foot side-foot-btn", onClick: () => store.go("pay"),
        title: TR("Оплата") }, body)
    : React.createElement("div", { className: "side-foot" }, body);
}

/* Перевод остановлен внутренним ограничением (402 spend). Сумм и слова
   «лимит» нет (22а): человеку нужно, что делать, а не устройство. */
function PaySpendNote({ store }) {
  const b = payBalance(store);
  if (!b.over) return null;
  const owner = !!(store.can && store.can.owner);
  return React.createElement("div", { className: "pay-bar", role: "status" },
    React.createElement("span", null,
      React.createElement("b", null, TR("Новые переводы сейчас приостановлены.")), " ",
      owner ? TR("Пополните баланс — работа продолжится. Если после оплаты не заработало, напишите в поддержку.")
            : TR("Попросите владельца организации пополнить баланс.")),
    owner && store.tab !== "pay" ? React.createElement(Btn, { variant: "primary", size: "sm", onClick: () => store.go("pay") }, TR("Оплатить")) : null,
    React.createElement(Btn, { variant: "ghost", size: "sm",
      onClick: () => window.dispatchEvent(new Event("mct-support-open")) }, TR("Написать в поддержку")));
}

/* Мои заказы — таблицей с названиями колонок. */
function PayOrders({ orders, onChanged, toast }) {
  if (!orders || !orders.length) return React.createElement("p", { className: "dim", style: { margin: 0 } },
    TR("Заказов пока нет."));
  const cancel = async (o) => {
    try { await window.API.payOrderCancel(o.id); if (onChanged) onChanged(); }
    catch (e) { toast.error(TR("Не отменён"), e.message || String(e)); }
  };
  return React.createElement("div", { className: "tbl-fit" }, React.createElement("table", { className: "tbl" },
    React.createElement("thead", null, React.createElement("tr", null,
      [TR("Заказ"), TR("Дата"), TR("Что купили"), TR("Сумма"), TR("Способ"), TR("Состояние"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
    React.createElement("tbody", null, orders.map(o => React.createElement("tr", { key: o.id },
      React.createElement("td", null, "№" + o.id),
      React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap" } }, o.at),
      React.createElement("td", null, [o.pages ? o.pages + TR(" стр.") : "", o.minutes ? o.minutes + TR(" мин") : ""].filter(Boolean).join(" + ")),
      React.createElement("td", { style: { whiteSpace: "nowrap" } }, payFmt(o.amount, o.currency)),
      React.createElement("td", null, (PAY_METHOD_LABEL[o.method] || (() => o.method))()),
      React.createElement("td", { style: { color: o.status === "paid" ? "var(--c-ok, #1a7f37)" : undefined } }, payStatusText(o.status)),
      React.createElement("td", { style: { textAlign: "right", whiteSpace: "nowrap" } },
        o.status === "new" && o.url ? React.createElement("a", { href: o.url, className: "btn btn-ghost btn-sm",
          target: o.online ? undefined : "_blank", rel: "noopener" }, TR("Оплатить")) : null,
        o.status === "new" ? React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => cancel(o) }, TR("Отменить")) : null))))));
}

/* Вид записи журнала страниц — код с сервера, подпись даёт браузер. */
function payLogKind(k) {
  return k === "credit" ? TR("пополнение") : k === "repeat" ? TR("повтор файла, без списания")
    : k === "init" ? TR("стартовый объём по проектам")
    : k === "reimport" ? TR("новая версия файла, за добавленные строки")
    : k === "excerpt" ? TR("пробный фрагмент")
    : k === "images" ? TR("текст с картинок")
    : k === "media" ? TR("речь из видео")
    : k === "edit" ? TR("дописано руками сверх файла")
    : k === "refund" ? TR("возврат") : TR("списание за файл");
}
function payLogNote(n) {
  return n === "env" ? TR("стартовый объём") : n === "signup" ? TR("подарок при регистрации") : n;
}
function payLogPlus(e) {
  const v = Number(e.pages != null ? e.pages : e.minutes || 0);
  return (e.kind === "credit" || e.kind === "refund") && v >= 0;
}

/* История: сколько получено, потрачено и осталось — и сам журнал, свёрнутым. */
function PayHistory({ store }) {
  const [open, setOpen] = useState(false);
  const w = store.wallet || {};
  const log = (w.pagesLog || []).slice().reverse();
  const mlog = (w.minutesLog || []).slice().reverse();
  const b = payBalance(store);
  const caps = store.caps || {}, usage = store.usage || {};
  if (!log.length && !mlog.length && !b.limited) return null;
  const row = (e, i, unit) => React.createElement("tr", { key: unit + i },
    React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap" } }, e.at),
    React.createElement("td", null, payLogKind(e.kind) + (e.note ? " · " + payLogNote(e.note) : "")),
    React.createElement("td", null, e.title || "—"),
    React.createElement("td", { style: { whiteSpace: "nowrap", textAlign: "right",
      color: payLogPlus(e) ? "var(--c-ok, #1a7f37)" : undefined } },
      (payLogPlus(e) ? "+" : "−") + Math.abs(Number(e.pages != null ? e.pages : e.minutes || 0)) + " " + unit));
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
    React.createElement("div", { className: "row between row-wrap", style: { gap: 8, alignItems: "center" } },
      React.createElement("h3", { className: "pf-sub-title" }, TR("Куда ушли страницы")),
      (log.length || mlog.length) ? React.createElement(Btn, { variant: "secondary", size: "sm", icon: open ? "chevD" : "chevR",
        "aria-expanded": open, onClick: () => setOpen(!open) }, open ? TR("Свернуть") : TR("Показать историю")) : null),
    b.limited && React.createElement("div", { className: "pay-sum" },
      React.createElement("div", null, React.createElement("span", null, TR("Получено всего")), React.createElement("b", null, (caps.maxPages || 0) + TR(" стр."))),
      React.createElement("div", null, React.createElement("span", null, TR("Потрачено")), React.createElement("b", null, (usage.pages || 0) + TR(" стр."))),
      React.createElement("div", null, React.createElement("span", null, TR("Осталось")), React.createElement("b", null, b.pagesLeft + TR(" стр.")))),
    open && React.createElement("div", { className: "tbl-fit" }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Дата"), TR("Что произошло"), TR("Файл"), TR("Сколько")].map((h, i) => React.createElement("th", { key: i, style: i === 3 ? { textAlign: "right" } : null }, h)))),
      React.createElement("tbody", null,
        log.map((e, i) => row(e, i, TR("стр."))),
        mlog.map((e, i) => row(e, i, TR("мин")))))),
    React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 13 } },
      TR("Страницы списываются, когда вы добавляете файл: 250 слов — одна страница.")));
}

/* ---------- Вкладка «Оплата» ---------- */
function TabPay({ store, toast }) {
  const [st, setSt] = useState(null);
  const [key, setKey] = useState(0);
  const changed = () => { setKey(k => k + 1); PAY_VAL.cache = {}; PAY_VAL.st = null; if (store.refreshMe) store.refreshMe(); };
  useEffect(() => {
    const h = () => changed();
    window.addEventListener("mct-pay-paid", h);
    return () => window.removeEventListener("mct-pay-paid", h);
  }, []);
  if (!(store.can && store.can.owner))
    return React.createElement("div", { className: "page" },
      React.createElement("p", { className: "dim" }, TR("Оплачивает владелец организации — попросите его пополнить баланс.")));
  return React.createElement("div", { className: "page page-narrow" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, TR("Оплата")),
      React.createElement("p", { className: "lead" }, TR("Сколько у вас осталось, пополнение и ваши заказы."))),
    React.createElement("div", { className: "col", style: { gap: 18 } },
      React.createElement(PaySpendNote, { store }),
      React.createElement(PayBalanceTiles, { store }),
      React.createElement(PayCard, { key, toast, onState: setSt, onPaid: changed }),
      /* Заказы и списания — СПРАВКА, а не часть формы: своей зоной на
         подложке и с заголовком, иначе таблицы читались продолжением
         пополнения и спорили с кнопкой «Оплатить». */
      React.createElement("section", { className: "pay-archive", "aria-label": TR("История") },
        React.createElement("div", { className: "pay-archive-head" },
          React.createElement(Icon, { name: "clock", size: 18 }),
          React.createElement("div", null,
            React.createElement("h2", { className: "section-title", style: { margin: 0 } }, TR("История")),
            React.createElement("p", { className: "dim", style: { margin: "2px 0 0", fontSize: 13.5 } },
              TR("Ваши заказы и куда ушли страницы — для справки.")))),
        React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 12 } },
          React.createElement("h3", { className: "pf-sub-title" }, TR("Мои заказы")),
          React.createElement(PayOrders, { orders: st && st.orders, toast, onChanged: changed })),
        React.createElement(PayHistory, { store }))));
}

/* На window, а не только объявлением: `const` верхнего уровня одного файла
   виден другим тегам <script>, но не наборам рендер-тестов. */
Object.assign(window, { PayCard, PayNeedBar, payFmt, PAY_METHOD_LABEL, TabPay, PayBalanceTiles, PaySideBalance,
  PaySpendNote, PayOrders, PayHistory, usePayValue, payBalance });
