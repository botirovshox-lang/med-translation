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
  card: () => TR("Карта Visa / Mastercard"),
  click: () => "Click",
  payme: () => "Payme",
  kaspi: () => "Kaspi",
};

/* Статус заказа — код с сервера, подпись даёт браузер (инвариант 17). */
function payStatusText(st) {
  return st === "paid" ? TR("оплачен") : st === "cancelled" ? TR("отменён")
    : st === "expired" ? TR("срок истёк") : TR("ждёт оплаты");
}

function PayCard({ toast, onPaid }) {
  const [st, setSt] = useState(null);
  const [pages, setPages] = useState(0);
  const [minutes, setMinutes] = useState(0);
  const [method, setMethod] = useState("");
  const [quote, setQuote] = useState(null);
  const [qErr, setQErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const ref = useRef(null);
  const reload = () => window.API.safeCall(() => window.API.payState()).then(r => {
    if (!r || !r.ok) return;
    setSt(r);
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
        .then(r => { if (alive) { setQuote(r.quote); setQErr(""); } })
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
      if (o.url) window.open(o.url, "_blank", "noopener");
    } catch (e) { toast.error(TR("Заказ не создан"), e.message || String(e)); }
    setBusy(false);
  };
  const cancel = async (o) => {
    try { await window.API.payOrderCancel(o.id); reload(); }
    catch (e) { toast.error(TR("Не отменён"), e.message || String(e)); }
  };
  const payable = st.payable || {};
  const u = st.usage || {}, m = st.minutes || {};
  const bal = [
    u.left != null ? TR("Страниц осталось: ") + u.left : null,
    m.wallet ? TR("Минут видео осталось: ") + m.left : null,
  ].filter(Boolean).join(" · ");
  const head = React.createElement("div", { className: "row between row-wrap", style: { gap: 8 } },
    React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Пополнить баланс")),
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
    bal ? React.createElement("div", { style: { fontWeight: 600 } }, bal) : null,
    React.createElement("div", { className: "grid grid-2", style: { gap: 10 } },
      qty(TR("Страниц перевода"), pages, setPages, packs.pages, (st.limits || {}).pages || 10000, payable.pages),
      qty(TR("Минут видео и звука"), minutes, setMinutes, packs.minutes, (st.limits || {}).minutes || 3000, payable.minutes)),
    React.createElement("div", { className: "dim", style: { fontSize: 12 } },
      TR("Страница — 250 слов исходника. Видео считается минутами распознаваемого отрезка: неполная минута — минута, озвучка входит в цену.")
      + (st.wpmMax ? TR(" Если речь быстрее ") + st.wpmMax + TR(" слов в минуту, минуты считаются по словам.") : "")),
    React.createElement("div", { role: "radiogroup", "aria-label": TR("Способ оплаты"), className: "pay-methods" },
      methods.map(x => React.createElement("label", { key: x.id, className: "pay-method" + (method === x.id ? " is-on" : "") },
        React.createElement("input", { type: "radio", name: "pay-method", value: x.id, checked: method === x.id,
          onChange: () => setMethod(x.id) }),
        React.createElement(PayMethodIcons, { method: x.id }),
        React.createElement("span", { className: "pay-method-text" },
          React.createElement("b", null, (PAY_METHOD_LABEL[x.id] || (() => x.id))()),
          React.createElement("span", { className: "dim" },
            (x.online ? TR("онлайн, сразу") : TR("по счёту: подтвердим после поступления"))
            + " · " + payFmt(x.page, x.currency) + TR(" за стр.")))))),
    meth.note && !meth.online ? React.createElement("div", { className: "dim", style: { whiteSpace: "pre-wrap" } }, meth.note) : null,
    React.createElement("div", { className: "row between row-wrap", style: { gap: 10, alignItems: "center" } },
      React.createElement("div", { style: { fontSize: 16, fontWeight: 700 } },
        quote ? TR("К оплате: ") + payFmt(quote.amount, quote.currency)
          : React.createElement("span", { className: "dim", style: { fontWeight: 400, fontSize: 13 } },
              qErr || TR("Выберите, сколько страниц или минут покупаете"))),
      React.createElement(Btn, { variant: "primary", disabled: !quote || busy, onClick: pay },
        busy ? TR("Создаём заказ…") : TR("Оплатить"))),
    done && !done.online ? React.createElement("div", { className: "pay-done" },
      TR("Заявка №") + done.id + TR(" принята: ") + payFmt(done.amount, done.currency) + ". "
      + (done.url ? TR("Ссылка на оплату открыта в новой вкладке.") : TR("Мы пришлём ссылку или реквизиты для оплаты."))
      + TR(" Баланс пополнится после поступления оплаты.")) : null,
    (st.orders || []).length ? React.createElement("div", null,
      React.createElement("div", { className: "eyebrow", style: { margin: "4px 0 6px" } }, TR("Мои заказы")),
      React.createElement("div", { className: "tbl-fit" }, React.createElement("table", { className: "tbl" },
        React.createElement("tbody", null, st.orders.map(o => React.createElement("tr", { key: o.id },
          React.createElement("td", null, "№" + o.id),
          React.createElement("td", { className: "dim" }, o.at),
          React.createElement("td", null, [o.pages ? o.pages + TR(" стр.") : "", o.minutes ? o.minutes + TR(" мин") : ""].filter(Boolean).join(" + ")),
          React.createElement("td", null, payFmt(o.amount, o.currency)),
          React.createElement("td", null, (PAY_METHOD_LABEL[o.method] || (() => o.method))()),
          React.createElement("td", { style: { color: o.status === "paid" ? "var(--c-ok, #1a7f37)" : undefined } }, payStatusText(o.status)),
          React.createElement("td", { style: { textAlign: "right", whiteSpace: "nowrap" } },
            o.status === "new" && o.url ? React.createElement("a", { href: o.url, className: "btn btn-ghost btn-sm",
              target: o.online ? undefined : "_blank", rel: "noopener" }, TR("Оплатить")) : null,
            o.status === "new" ? React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => cancel(o) }, TR("Отменить")) : null)))))))
      : null);
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
      if (r.order.status === "new" && ++tries < 6) setTimeout(tick, 3000);
    }).catch(() => {});
    tick();
    return () => { alive = false; };
  }, []);
  const owner = !!(store.can && store.can.owner);
  const open = () => {
    window._mcat_payIntent = need && need.kind === "minutes" && need.need
      ? { minutes: Math.max(1, Number(need.need) - Math.max(0, Number(need.left || 0))) } : null;
    setNeed(null);
    store.go("org");
    try { window.dispatchEvent(new CustomEvent("mct-pay-open", { detail: window._mcat_payIntent || {} })); } catch (e) {}
  };
  const close = (set) => React.createElement("button", { className: "btn btn-ghost btn-sm", "aria-label": TR("Закрыть"),
    onClick: () => set(null) }, "×");
  const bars = [];
  if (need) {
    const what = need.kind === "minutes" ? TR("Минут видео не хватает")
      + (need.need != null ? ": " + TR("нужно ") + need.need + TR(" мин, осталось ") + Math.max(0, Number(need.left || 0)) : "") + "."
      : need.kind === "spend" ? TR("Лимит работы на этот месяц исчерпан.")
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

/* На window, а не только объявлением: `const` верхнего уровня одного файла
   виден другим тегам <script>, но не наборам рендер-тестов. */
Object.assign(window, { PayCard, PayNeedBar, payFmt, PAY_METHOD_LABEL });
