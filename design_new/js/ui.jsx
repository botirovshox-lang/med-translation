/* ============================================================
   Shared UI kit — Icon, Btn, Badge, inputs, Modal, Toast, etc.
   Exposes components on window for cross-file use.
   ============================================================ */
const { useState, useEffect, useRef, useCallback, createContext, useContext } = React;

/* ---------- Icons (functional line icons, 24x24 stroke) ---------- */
const ICONS = {
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.3-4.3",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z|M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7 19.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 14a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 10 3.6V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z",
  user: "M20 21a8 8 0 1 0-16 0|M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4|M16 17l5-5-5-5|M21 12H9",
  lock: "M5 11h14a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2Z|M8 11V7a4 4 0 0 1 8 0v4",
  unlock: "M5 11h14a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2Z|M8 11V7a4 4 0 0 1 7.9-1",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z|M12 1v2|M12 21v2|M4.2 4.2l1.4 1.4|M18.4 18.4l1.4 1.4|M1 12h2|M21 12h2|M4.2 19.8l1.4-1.4|M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z",
  upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4|M17 8l-5-5-5 5|M12 3v12",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4|M7 10l5 5 5-5|M12 15V3",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z|M14 2v6h6",
  edit: "M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7|M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4z",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20|M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z",
  repeat: "M17 1l4 4-4 4|M3 11V9a4 4 0 0 1 4-4h14|M7 23l-4-4 4-4|M21 13v2a4 4 0 0 1-4 4H3",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z",
  check: "M20 6L9 17l-5-5",
  checkCircle: "M22 11.1V12a10 10 0 1 1-5.9-9.1|M22 4L12 14.1l-3-3",
  clipboard: "M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2|M9 2h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z",
  chart: "M3 3v18h18|M18 17V9|M13 17V5|M8 17v-3",
  bar: "M12 20V10|M18 20V4|M6 20v-4",
  pie: "M21.2 15.9A10 10 0 1 1 8.1 2.8|M22 12A10 10 0 0 0 12 2v10z",
  plus: "M12 5v14|M5 12h14",
  close: "M18 6L6 18|M6 6l12 12",
  chevR: "M9 18l6-6-6-6",
  chevD: "M6 9l6 6 6-6",
  chevL: "M15 18l-6-6 6-6",
  trash: "M3 6h18|M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2",
  copy: "M9 9h11a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-1|M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
  globe: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z|M2 12h20|M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20Z",
  cpu: "M6 6h12v12H6z|M9 9h6v6H9z|M9 1v3|M15 1v3|M9 20v3|M15 20v3|M20 9h3|M20 14h3|M1 9h3|M1 14h3",
  alert: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z|M12 9v4|M12 17h.01",
  warn: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z|M12 8v4|M12 16h.01",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z|M12 16v-4|M12 8h.01",
  list: "M8 6h13|M8 12h13|M8 18h13|M3 6h.01|M3 12h.01|M3 18h.01",
  columns: "M4 4h7v16H4z|M13 4h7v16h-7z",
  calendar: "M5 4h14a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z|M16 2v4|M8 2v4|M3 10h18",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z|M12 6v6l4 2",
  filter: "M22 3H2l8 9.5V19l4 2v-8.5L22 3Z",
  message: "M21 11.5a8.4 8.4 0 0 1-9 8.4 8.4 8.4 0 0 1-4-1L3 21l1.9-5a8.4 8.4 0 0 1 16.1-4.5Z",
  send: "M22 2 11 13|M22 2l-7 20-4-9-9-4 20-7Z",
  hospital: "M3 21h18|M5 21V7l7-4 7 4v14|M9 9h6|M12 6v6|M9 21v-4h6v4",
  zap: "M13 2 3 14h9l-1 8 10-12h-9l1-8Z",
  target: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z|M12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12Z|M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
  dots: "M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z|M19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z|M5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z",
  arrowR: "M5 12h14|M12 5l7 7-7 7",
  folder: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z",
  sliders: "M4 21v-7|M4 10V3|M12 21v-9|M12 8V3|M20 21v-5|M20 12V3|M1 14h6|M9 8h6|M17 16h6",
};

function Icon({ name, size = 18, stroke = 2, className = "", style }) {
  const d = ICONS[name];
  if (!d) return null;
  const parts = d.split("|");
  return (
    React.createElement("svg", {
      className: "ic " + className, width: size, height: size, viewBox: "0 0 24 24",
      fill: "none", stroke: "currentColor", strokeWidth: stroke,
      strokeLinecap: "round", strokeLinejoin: "round", style, "aria-hidden": "true",
    }, parts.map((p, i) => React.createElement("path", { key: i, d: p })))
  );
}

/* ---------- Buttons ---------- */
function Btn({ variant = "primary", size, icon, iconRight, children, className = "", ...rest }) {
  const cls = ["btn", "btn-" + variant, size === "sm" ? "btn-sm" : size === "lg" ? "btn-lg" : "", className].filter(Boolean).join(" ");
  return React.createElement("button", { className: cls, ...rest },
    icon && React.createElement(Icon, { name: icon, size: size === "sm" ? 15 : 17 }),
    children,
    iconRight && React.createElement(Icon, { name: iconRight, size: size === "sm" ? 15 : 17 })
  );
}
function IconBtn({ icon, label, active, sm, size, className = "", ...rest }) {
  return React.createElement("button", {
    className: ["iconbtn", sm ? "sm" : "", active ? "active" : "", className].filter(Boolean).join(" "),
    "aria-label": label, title: label, ...rest,
  }, React.createElement(Icon, { name: icon, size: size || (sm ? 17 : 19) }));
}

/* ---------- Badge ---------- */
const STATUS_META = {
  new:        { cls: "badge-new",        label: "Новый",       icon: "file" },
  translated: { cls: "badge-translated", label: "Переведён",   icon: "globe" },
  qa:         { cls: "badge-qa",         label: "QA",          icon: "shield" },
  confirmed:  { cls: "badge-confirmed",  label: "Подтверждён", icon: "checkCircle" },
  failed:     { cls: "badge-failed",     label: "Ошибка",      icon: "alert" },
  review:     { cls: "badge-review",     label: "На проверке", icon: "warn" },
};
function StatusBadge({ status, withIcon = true }) {
  const m = STATUS_META[status] || STATUS_META.new;
  return React.createElement("span", { className: "badge " + m.cls },
    withIcon ? React.createElement(Icon, { name: m.icon, size: 13, stroke: 2.4 }) : React.createElement("span", { className: "dot" }),
    m.label
  );
}
function Badge({ variant = "soft", icon, children }) {
  return React.createElement("span", { className: "badge badge-" + variant },
    icon && React.createElement(Icon, { name: icon, size: 13 }), children);
}

/* ---------- Form fields ---------- */
function Field({ label, hint, children, htmlFor }) {
  return React.createElement("div", { className: "field" },
    label && React.createElement("label", { className: "label", htmlFor }, label),
    children,
    hint && React.createElement("span", { className: "hint" }, hint)
  );
}
function Input(props) { return React.createElement("input", { className: "input", ...props }); }
function Textarea(props) { return React.createElement("textarea", { className: "textarea", ...props }); }
function Select({ children, ...props }) { return React.createElement("select", { className: "select", ...props }, children); }
function SearchInput({ value, onChange, placeholder }) {
  return React.createElement("div", { className: "search", style: { flex: 1 } },
    React.createElement(Icon, { name: "search", size: 17 }),
    React.createElement("input", { className: "input", value, onChange, placeholder, "aria-label": placeholder })
  );
}
function Checkbox({ checked, onChange, children }) {
  return React.createElement("label", { className: "check" },
    React.createElement("input", { type: "checkbox", checked, onChange }),
    React.createElement("span", { className: "box" }, React.createElement(Icon, { name: "check", size: 13, stroke: 3 })),
    children && React.createElement("span", null, children)
  );
}
function Radio({ checked, onChange, name, children }) {
  return React.createElement("label", { className: "radio" },
    React.createElement("input", { type: "radio", checked, onChange, name }),
    React.createElement("span", { className: "ring" }),
    children && React.createElement("span", null, children)
  );
}
function Switch({ on, onClick, label }) {
  return React.createElement("button", { className: "switch" + (on ? " on" : ""), onClick, role: "switch",
    "aria-checked": on, "aria-label": label },
    React.createElement("span", { className: "knob" }));
}

/* ---------- Expander ---------- */
function Expander({ title, icon, right, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return React.createElement("div", { className: "expander" + (open ? " open" : "") },
    React.createElement("button", { className: "expander-head", onClick: () => setOpen(o => !o), "aria-expanded": open },
      React.createElement(Icon, { name: "chevR", size: 18, className: "chev" }),
      React.createElement("span", { className: "ex-title" },
        icon && React.createElement(Icon, { name: icon, size: 17 }), title),
      right && React.createElement("span", { className: "dim", style: { fontSize: 13, fontWeight: 600 } }, right)
    ),
    open && React.createElement("div", { className: "expander-body" }, children)
  );
}

/* ---------- Modal ---------- */
function Modal({ title, icon, onClose, children, footer, width }) {
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return React.createElement("div", { className: "overlay", onMouseDown: (e) => { if (e.target === e.currentTarget) onClose(); } },
    React.createElement("div", { className: "modal", style: width ? { maxWidth: width } : null, role: "dialog", "aria-modal": "true" },
      React.createElement("div", { className: "modal-head" },
        icon && React.createElement(Icon, { name: icon, size: 20, style: { color: "var(--c-primary)" } }),
        React.createElement("h3", null, title),
        React.createElement(IconBtn, { icon: "close", label: "Закрыть", sm: true, onClick: onClose })
      ),
      React.createElement("div", { className: "modal-body" }, children),
      footer && React.createElement("div", { className: "modal-foot" }, footer)
    )
  );
}

/* ---------- Toast system ---------- */
const ToastCtx = createContext(null);
function useToast() { return useContext(ToastCtx); }
function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const remove = useCallback((id) => setItems(l => l.filter(t => t.id !== id)), []);
  const push = useCallback((type, title, msg) => {
    const id = Math.random().toString(36).slice(2);
    setItems(l => [...l, { id, type, title, msg }]);
    setTimeout(() => remove(id), 5000);
  }, [remove]);
  const api = {
    success: (t, m) => push("success", t, m),
    error: (t, m) => push("error", t, m),
    warning: (t, m) => push("warning", t, m),
    info: (t, m) => push("info", t, m),
  };
  const tIcon = { success: "check", error: "close", warning: "warn", info: "info" };
  return React.createElement(ToastCtx.Provider, { value: api },
    children,
    React.createElement("div", { className: "toasts", "aria-live": "polite" },
      items.map(t => React.createElement("div", { className: "toast " + t.type, key: t.id },
        React.createElement("span", { className: "t-ic" }, React.createElement(Icon, { name: tIcon[t.type], size: 17, stroke: 2.6 })),
        React.createElement("div", { style: { flex: 1, minWidth: 0 } },
          React.createElement("div", { className: "t-title" }, t.title),
          t.msg && React.createElement("div", { className: "t-msg" }, t.msg)
        ),
        React.createElement("button", { className: "t-close iconbtn sm", onClick: () => remove(t.id), "aria-label": "Закрыть" },
          React.createElement(Icon, { name: "close", size: 15 }))
      ))
    )
  );
}

/* ---------- Progress ---------- */
function ProgressBar({ value }) {
  return React.createElement("div", { className: "pbar" }, React.createElement("span", { style: { width: Math.max(0, Math.min(100, value)) + "%" } }));
}
function Ring({ value, size = 140, stroke = 12, color = "var(--c-primary)", label }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, off = c * (1 - value / 100);
  return React.createElement("div", { className: "ring-wrap", style: { width: size, height: size } },
    React.createElement("svg", { width: size, height: size, style: { transform: "rotate(-90deg)" } },
      React.createElement("circle", { cx: size / 2, cy: size / 2, r, fill: "none", stroke: "var(--bg-sunken)", strokeWidth: stroke }),
      React.createElement("circle", { cx: size / 2, cy: size / 2, r, fill: "none", stroke: color, strokeWidth: stroke,
        strokeLinecap: "round", strokeDasharray: c, strokeDashoffset: off, style: { transition: "stroke-dashoffset .6s ease" } })
    ),
    React.createElement("div", { className: "ring-center" },
      React.createElement("div", { className: "rc-val" }, value + "%"),
      label && React.createElement("div", { className: "rc-lab" }, label)
    )
  );
}
function Spinner({ lg }) { return React.createElement("div", { className: "spinner" + (lg ? " lg" : "") }); }

function Avatar({ person, size = 30 }) {
  return React.createElement("span", { className: "avatar", title: person.name,
    style: { background: person.color, width: size, height: size, fontSize: size * 0.4 } }, person.initials);
}
function EmptyState({ icon, title, sub, action }) {
  return React.createElement("div", { className: "empty" },
    React.createElement(Icon, { name: icon || "folder", size: 44, className: "e-ic", stroke: 1.6 }),
    React.createElement("h3", null, title),
    sub && React.createElement("p", null, sub),
    action && React.createElement("div", { style: { marginTop: 18 } }, action)
  );
}

const FLAGS = { RU: "🇷🇺", EN: "🇬🇧", DE: "🇩🇪", FR: "🇫🇷", ES: "🇪🇸" };
function LangPair({ src, tgt }) {
  return React.createElement("span", { className: "badge badge-lang" }, (FLAGS[src] || src) + " " + src + " → " + (FLAGS[tgt] || tgt) + " " + tgt);
}

/* ---------- TM match chip (MemSource-style) ---------- */
function tmChipFor(score) {
  if (score == null) return { cls: "none", text: "—", tip: "Нет совпадения в TM" };
  if (score === 101) return { cls: "fresh", text: "101", tip: "Новый сегмент — нет совпадения в TM" };
  if (score >= 100) return { cls: "exact", text: "100", tip: "TM match: 100% — exact" };
  if (score >= 95) return { cls: "high", text: String(score), tip: "TM match: " + score + "% — high fuzzy" };
  if (score >= 85) return { cls: "mid", text: String(score), tip: "TM match: " + score + "% — medium fuzzy" };
  return { cls: "low", text: String(score), tip: "TM match: " + score + "% — low fuzzy" };
}
function TMChip({ score }) {
  const c = tmChipFor(score);
  return React.createElement("span", { className: "tmchip " + c.cls, title: c.tip }, c.text);
}
/* ---------- Cost estimate formatting ---------- */
function fmtCost(v) {
  if (v > 10) return "$" + v.toFixed(1);
  if (v > 1) return "$" + v.toFixed(2);
  if (v < 0.0001) return "< $0.0001";
  return "$" + v.toFixed(4);
}

/* ---------- InfoTip (ⓘ + hover/focus tooltip, portal, 300ms) ---------- */
function InfoTip({ title, body, code, size = 14, className = "" }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ left: 0, top: 0, above: false });
  const ref = useRef(null);
  const timer = useRef(null);
  const place = () => {
    const r = ref.current.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    const left = Math.min(Math.max(r.left + r.width / 2, 170), vw - 170);
    const above = r.bottom + 170 > vh;
    setPos({ left, top: above ? r.top - 8 : r.bottom + 8, above });
  };
  const show = () => { timer.current = setTimeout(() => { place(); setOpen(true); }, 300); };
  const showNow = () => { place(); setOpen(true); };
  const hide = () => { clearTimeout(timer.current); setOpen(false); };
  useEffect(() => () => clearTimeout(timer.current), []);
  return React.createElement("span", {
    ref, className: "infotip " + className, tabIndex: 0, role: "button",
    "aria-label": title, onMouseEnter: show, onMouseLeave: hide,
    onFocus: showNow, onBlur: hide,
    onClick: (e) => { e.stopPropagation(); open ? hide() : showNow(); },
  },
    React.createElement(Icon, { name: "info", size }),
    open && ReactDOM.createPortal(
      React.createElement("div", {
        className: "tooltip", role: "tooltip",
        style: { left: pos.left, top: pos.top, transform: "translateX(-50%)" + (pos.above ? " translateY(-100%)" : "") },
      },
        title && React.createElement("div", { className: "tt-title" }, title),
        body && React.createElement("div", { className: "tt-body" }, body),
        code && React.createElement("span", { className: "tt-code" }, code)
      ), document.body)
  );
}

/* ---------- Route + Risk metadata (RU label + EN code + tooltip) ---------- */
const ROUTE_INFO = {
  EXACT_TM: { label: "Точное TM", code: "EXACT_TM", color: "var(--route-tm)",
    tip: "Точное совпадение в Translation Memory (99%+) — использовать существующий перевод. Стоимость: $0. Не требует вызова API." },
  DUPLICATE: { label: "Представитель дубликатов", code: "DUPLICATE_REPRESENTATIVE", color: "var(--route-dup)",
    tip: "Первый сегмент в группе дубликатов — перевести один раз через GPT. Остальные сегменты группы получат копию. Стоимость: только за representative." },
  DUPLICATE_PROPAGATION_PENDING: { label: "Копия из дубликата", code: "DUPLICATE_PROPAGATION_PENDING", color: "var(--c-purple)",
    tip: "Дубликат другого сегмента — скопировать перевод от representative после его подтверждения. Стоимость: $0. Не требует вызова API." },
  GOOGLE_SAFE: { label: "Google безопасно", code: "GOOGLE_SAFE", color: "var(--route-google)",
    tip: "Низкий риск, нет анатомии — использовать Google Translate (бесплатный tier до 500K символов/месяц). Подходит для простых сегментов без медицинской критичности." },
  GPT_REQUIRED: { label: "Требуется GPT", code: "GPT_REQUIRED", color: "var(--route-gpt)",
    tip: "Требуется OpenAI GPT для перевода и QA. Стандартный маршрут для большинства медицинских сегментов." },
  GPT_WITH_GLOSSARY_REQUIRED: { label: "GPT + Глоссарий", code: "GPT_WITH_GLOSSARY_REQUIRED", color: "var(--c-warning)",
    tip: "Требуется OpenAI GPT с инъекцией глоссария в промпт. Применяется для сегментов с большим количеством медицинских терминов (3+) или с риском HIGH." },
  HUMAN_REVIEW: { label: "Ручной перевод", code: "HUMAN_REVIEW_REQUIRED", color: "var(--route-human)",
    tip: "Критичный или высокий риск без глоссария — требуется человеческий перевод/review. API не вызывается до решения переводчика." },
};
const RISK_INFO = {
  low: { label: "Низкий", range: "0–24", color: "var(--c-success)",
    tip: "Скор риска 0–24. Метаданные, простые предложения, заголовки.\n→ Маршрут: GOOGLE_SAFE.\n→ QA политика: auto_pass." },
  medium: { label: "Средний", range: "25–49", color: "#ca8a04",
    tip: "Скор риска 25–49. Стандартный медицинский контент, отчёты, описания.\n→ Маршрут: GPT_REQUIRED.\n→ QA политика: manual." },
  high: { label: "Высокий", range: "50–74", color: "var(--c-warning)",
    tip: "Скор риска 50–74. Сложная медицинская терминология, анатомия, диагнозы.\n→ Маршрут: GPT_WITH_GLOSSARY_REQUIRED.\n→ QA политика: strict." },
  critical: { label: "Критический", range: "75–100", color: "var(--c-error)",
    tip: "Скор риска 75–100. Содержит критичную медицинскую информацию: дозировки, противопоказания, реанимация.\n→ Маршрут: HUMAN_REVIEW_REQUIRED.\n→ QA политика: strict." },
};
function RouteLabel({ route, withTip = true }) {
  const r = ROUTE_INFO[route] || { label: route, code: route, color: "var(--text-3)", tip: "" };
  return React.createElement("span", { className: "route-label" },
    React.createElement("span", { className: "rl-dot", style: { background: r.color } }),
    React.createElement("span", { className: "rl-name" }, r.label),
    React.createElement("span", { className: "rl-code mono" }, "(" + r.code + ")"),
    withTip && r.tip && React.createElement(InfoTip, { title: r.label, body: r.tip, code: r.code })
  );
}
function RiskLabel({ risk, withTip = true }) {
  const r = RISK_INFO[risk] || RISK_INFO.low;
  return React.createElement("span", { className: "route-label" },
    React.createElement("span", { className: "rl-dot", style: { background: r.color } }),
    React.createElement("span", { className: "rl-name" }, r.label),
    React.createElement("span", { className: "rl-code mono" }, "(" + r.range + ")"),
    withTip && React.createElement(InfoTip, { title: r.label + " (" + r.range + ")", body: r.tip })
  );
}

Object.assign(window, {
  Icon, Btn, IconBtn, StatusBadge, Badge, STATUS_META,
  Field, Input, Textarea, Select, SearchInput, Checkbox, Radio, Switch,
  Expander, Modal, ToastProvider, useToast,
  ProgressBar, Ring, Spinner, Avatar, EmptyState, LangPair, FLAGS,
  TMChip, tmChipFor, fmtCost, InfoTip, ROUTE_INFO, RISK_INFO, RouteLabel, RiskLabel,
});
