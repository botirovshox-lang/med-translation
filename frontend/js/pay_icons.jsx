/* ============================================================
   Знаки способов оплаты: Uzcard, Humo, Visa, Mastercard, Click, Payme, Kaspi.
   ОФИЦИАЛЬНЫЕ логотипы, файлами в vendor/paylogos/ (откуда взят каждый —
   SOURCES.txt рядом): банк-эквайер требует действующие знаки платёжных
   систем, а нарисованные «по мотивам» ими не являются. Свой хост, не чужой:
   чужой хост на экране оплаты — чужая авария в нашей кассе.
   ============================================================ */
function payIcon(file, label) {
  return React.createElement("span", { className: "pay-logo", title: label },
    React.createElement("img", { src: "vendor/paylogos/" + file, alt: label, "aria-label": label,
      loading: "lazy", decoding: "async" }));
}
function PayIconUzcard() { return payIcon("uzcard.svg", "Uzcard"); }
function PayIconHumo() { return payIcon("humo.png", "Humo"); }
function PayIconVisa() { return payIcon("visa.svg", "Visa"); }
function PayIconMastercard() { return payIcon("mastercard.svg", "Mastercard"); }
function PayIconClick() { return payIcon("click.svg", "Click"); }
function PayIconPayme() { return payIcon("payme.png", "Payme"); }
function PayIconKaspi() { return payIcon("kaspi.svg", "Kaspi"); }

/* Способ → знаки. У карты четыре знака — один способ (шлюз банка-эквайера). */
const PAY_METHOD_ICONS = {
  card: [PayIconUzcard, PayIconHumo, PayIconVisa, PayIconMastercard],
  click: [PayIconClick],
  payme: [PayIconPayme],
  kaspi: [PayIconKaspi],
};

function PayMethodIcons({ method }) {
  const list = PAY_METHOD_ICONS[method] || [];
  return React.createElement("span", { className: "row row-wrap", style: { gap: 6 } },
    list.map((C, i) => React.createElement(C, { key: i })));
}

/* Полоса знаков для подвала «Мы принимаем». */
function PayAcceptStrip() {
  return React.createElement("div", { className: "row row-wrap pay-strip", style: { gap: 8, alignItems: "center" } },
    [PayIconUzcard, PayIconHumo, PayIconVisa, PayIconMastercard, PayIconClick, PayIconPayme, PayIconKaspi].map((C, i) =>
      React.createElement(C, { key: i })));
}

Object.assign(window, { PayMethodIcons, PayAcceptStrip, PAY_METHOD_ICONS });
