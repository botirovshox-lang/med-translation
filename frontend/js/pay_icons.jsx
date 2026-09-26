/* ============================================================
   Знаки способов оплаты: Visa, Mastercard, Click, Payme, Kaspi.
   Инлайн-SVG, без внешних файлов и шрифтов: чужой хост на экране оплаты —
   это чужая авария в нашей кассе (тот же закон, что у React в vendor/).
   Знаки упрощённые — цвет и начертание марки, а не её точная копия; этого
   хватает, чтобы человек узнал свой способ, и не требует файлов от банков.
   ============================================================ */
function payIconSvg(children, label, bg) {
  return React.createElement("svg", {
    viewBox: "0 0 64 40", width: 56, height: 35, role: "img", "aria-label": label,
    style: { display: "block", borderRadius: 6, background: bg || "#fff",
             boxShadow: "inset 0 0 0 1px rgba(0,0,0,.12)" } },
    React.createElement("title", null, label), ...children);
}
const PAY_FONT = "Arial, Helvetica, sans-serif";

function PayIconVisa() {
  return payIconSvg([
    React.createElement("text", { key: "t", x: 32, y: 26, textAnchor: "middle", fontFamily: PAY_FONT,
      fontSize: 17, fontWeight: 900, fontStyle: "italic", fill: "#1A1F71", letterSpacing: 0.5 }, "VISA"),
    React.createElement("rect", { key: "b", x: 14, y: 29, width: 36, height: 2.4, fill: "#F7B600" })], "Visa");
}
function PayIconMastercard() {
  return payIconSvg([
    React.createElement("circle", { key: "r", cx: 26, cy: 18, r: 11, fill: "#EB001B" }),
    React.createElement("circle", { key: "y", cx: 38, cy: 18, r: 11, fill: "#F79E1B" }),
    React.createElement("path", { key: "o", fill: "#FF5F00",
      d: "M32 8.8a11 11 0 0 1 0 18.4a11 11 0 0 1 0-18.4Z" }),
    React.createElement("text", { key: "t", x: 32, y: 36.5, textAnchor: "middle", fontFamily: PAY_FONT,
      fontSize: 5.6, fontWeight: 700, fill: "#231F20" }, "mastercard")], "Mastercard");
}
function PayIconClick() {
  return payIconSvg([
    React.createElement("circle", { key: "c", cx: 15, cy: 20, r: 7.5, fill: "none", stroke: "#fff", strokeWidth: 3 }),
    React.createElement("circle", { key: "d", cx: 15, cy: 20, r: 2.4, fill: "#fff" }),
    React.createElement("text", { key: "t", x: 40, y: 25.5, textAnchor: "middle", fontFamily: PAY_FONT,
      fontSize: 15, fontWeight: 700, fill: "#fff" }, "click")], "Click", "#0073FF");
}
function PayIconPayme() {
  return payIconSvg([
    React.createElement("text", { key: "t", x: 32, y: 25.5, textAnchor: "middle", fontFamily: PAY_FONT,
      fontSize: 16, fontWeight: 800 },
      React.createElement("tspan", { fill: "#33CCCC" }, "pay"),
      React.createElement("tspan", { fill: "#fff" }, "me"))], "Payme", "#0E2A3B");
}
function PayIconKaspi() {
  return payIconSvg([
    React.createElement("text", { key: "t", x: 32, y: 25.5, textAnchor: "middle", fontFamily: PAY_FONT,
      fontSize: 16, fontWeight: 800, fill: "#fff" }, "Kaspi")], "Kaspi", "#F14635");
}

/* Способ → знаки. У карты два знака: Visa и Mastercard — один способ. */
const PAY_METHOD_ICONS = {
  card: [PayIconVisa, PayIconMastercard],
  click: [PayIconClick],
  payme: [PayIconPayme],
  kaspi: [PayIconKaspi],
};

function PayMethodIcons({ method }) {
  const list = PAY_METHOD_ICONS[method] || [];
  return React.createElement("span", { className: "row", style: { gap: 6 }, "aria-hidden": false },
    list.map((C, i) => React.createElement(C, { key: i })));
}

/* Полоса знаков для подвала «Мы принимаем». */
function PayAcceptStrip() {
  return React.createElement("div", { className: "row row-wrap pay-strip", style: { gap: 8, alignItems: "center" } },
    [PayIconVisa, PayIconMastercard, PayIconClick, PayIconPayme, PayIconKaspi].map((C, i) =>
      React.createElement(C, { key: i })));
}

Object.assign(window, { PayMethodIcons, PayAcceptStrip, PAY_METHOD_ICONS });
