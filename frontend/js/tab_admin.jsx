/* ============================================================
   Tab: Админ — сводка администратора сервиса (только super).
   Организации, люди, прогоны всех организаций, расход, здоровье процесса.
   Сводку считает сервер (/api/admin/overview); обновляется раз в 10 с,
   пока вкладка открыта. Право ПОКАЗАТЬ — здесь, право СДЕЛАТЬ — на сервере.
   ============================================================ */
function fmtDur(sec) {
  if (sec == null) return "—";
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return (d ? d + TR(" д ") : "") + (h ? h + TR(" ч ") : "") + m + TR(" мин");
}
function fmtBytes(b) { return b == null ? "—" : b > 1e6 ? (b / 1e6).toFixed(1) + TR(" МБ") : Math.round(b / 1e3) + TR(" КБ"); }

function AdminStat({ label, value, warn }) {
  return React.createElement("div", { className: "card card-pad", style: { minWidth: 150 } },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 4px" } }, label),
    React.createElement("div", { style: { fontSize: 22, fontWeight: 500, letterSpacing: "-.02em", color: warn ? "var(--c-danger)" : undefined } }, value));
}

/* Потолок как текст: 0 и пусто — «без потолка». Своё значение организации
   (не унаследованное из окружения) помечается звёздочкой. */
function fmtCap(v) { return v ? String(v) : "∞"; }
function capSuffix(t, key) {
  const c = t.caps || {}; const own = c.own || {};
  // выдано 0 страниц — это исчерпано, а не «без потолка»: своё значение
  // показывается всегда; у проектов ноль по-прежнему «без потолка».
  const show = key === "maxPages" ? (c[key] || own[key] != null) : !!c[key];
  return (show ? " / " + c[key] : "") + (own[key] != null ? " ★" : "");
}
function capTitle(t, key) {
  const c = t.caps || {}; const own = c.own || {};
  return own[key] != null ? TR("своё значение организации") : (c[key] ? TR("по умолчанию из окружения") : TR("без потолка"));
}
function pagesTitle(t) {
  const u = t.usage || {};
  return TR("списано ") + (u.used != null ? u.used : "—") + TR(" · на картинках ") + (u.imagePages || 0)
    + (u.left != null ? TR(" · осталось ") + u.left : "") + " · " + capTitle(t, "maxPages");
}

function AdminTenants({ ov, toast, onChange }) {
  const setLimit = async (t) => {
    const v = prompt(TR("Месячный лимит для «") + t.name + TR("», $ (пусто — снять):"), t.limitUsd != null ? t.limitUsd : "");
    if (v === null) return;
    try { await window.API.tenantUpdate(t.id, v.trim() === "" ? { clearLimit: true } : { limitUsd: Number(v) }); toast.success(TR("Лимит обновлён"), t.name); onChange(); }
    catch (e) { toast.error(TR("Не обновлён"), e.message || String(e)); }
  };
  // Лимит страниц выдаётся ПОПОЛНЕНИЕМ (журнал на сервере), потолок проектов —
  // число: пусто — по умолчанию из окружения (ov.capDefaults), 0 — без потолка.
  const [logFor, setLogFor] = useState(null);
  const topUp = async (t) => {
    const u = t.usage || {};
    const v = prompt(TR("Сколько страниц добавить организации «") + t.name + TR("»? Отрицательное число — исправление. Выдано ")
      + (u.credit != null ? u.credit : fmtCap((ov.capDefaults || {}).maxPages)) + TR(", списано ") + (u.used != null ? u.used : "—") + ":", "");
    if (v === null || v.trim() === "" || !Number(v)) return;
    try { await window.API.tenantUpdate(t.id, { addPages: Number(v) }); toast.success(TR("Лимит страниц пополнен"), t.name); onChange(); }
    catch (e) { toast.error(TR("Не пополнен"), e.message || String(e)); }
  };
  const setCaps = async (t) => {
    const d = ov.capDefaults || {};
    const own = (t.caps && t.caps.own) || {};
    const p2 = prompt(TR("Потолок проектов для «") + t.name + TR("» (пусто — по умолчанию ") + fmtCap(d.maxProjects) + TR(", 0 — без потолка):"), own.maxProjects != null ? own.maxProjects : "");
    if (p2 === null) return;
    const body = p2.trim() === "" ? { clearMaxProjects: true } : { maxProjects: Number(p2) };
    try { await window.API.tenantUpdate(t.id, body); toast.success(TR("Потолки обновлены"), t.name); onChange(); }
    catch (e) { toast.error(TR("Не обновлены"), e.message || String(e)); }
  };
  const toggle = async (t) => {
    try { await window.API.tenantUpdate(t.id, { active: !t.active }); toast.success(t.active ? TR("Отключена") : TR("Включена"), t.name); onChange(); }
    catch (e) { toast.error(TR("Не удалось"), e.message || String(e)); }
  };
  /* Упрощённый режим: ни сумм, ни выбора моделей на экране организации,
     а модели шагов назначает ОНА, а не браузер. Модели спрашиваем сразу
     после включения: включить режим и не назначить модели — значит отдать
     все шаги умолчаниям сервера, о чём администратор потом не вспомнит. */
  const simpleMode = async (t) => {
    const on = !t.simple;
    if (!on) {
      try { await window.API.tenantUpdate(t.id, { simple: false }); toast.success(TR("Обычный режим"), t.name); onChange(); }
      catch (e) { toast.error(TR("Не удалось"), e.message || String(e)); }
      return;
    }
    const cur = t.models || {};
    const list = (ov.models || []).map(m => m.id).join(", ");
    const ask = (step, label) => {
      const v = prompt(TR("Модель для шага «") + label + TR("» (пусто — по умолчанию сервера): ") + list, cur[step] || "");
      return v === null ? null : v.trim();
    };
    const steps = [["translate", TR("перевод")], ["review", TR("ревизия")], ["backcheck", TR("back-check")],
                   ["termcheck", TR("термины")], ["termaudit", TR("сверка терминов")], ["repair", TR("ремонт")]];
    const models = {};
    for (const [k, label] of steps) {
      const v = ask(k, label);
      if (v === null) return;
      if (v) models[k] = v;
    }
    try { await window.API.tenantUpdate(t.id, { simple: true, models }); toast.success(TR("Упрощённый режим включён"), t.name); onChange(); }
    catch (e) { toast.error(TR("Не удалось"), e.message || String(e)); }
  };
  const del = async (t) => {
    if (!confirm(TR("Удалить организацию «") + t.name + TR("» вместе с её пользователями?\nПроекты должны быть удалены заранее."))) return;
    try { const r = await window.API.tenantDelete(t.id); toast.success(TR("Организация удалена"), TR("пользователей: ") + r.usersRemoved); onChange(); }
    catch (e) { toast.error(TR("Не удалена"), e.message || String(e)); }
  };
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } }, TR("Организации · ") + ov.tenants.length),
    ov.capDefaults && React.createElement("p", { className: "dim", style: { margin: "0 0 8px", fontSize: 13 } },
      TR("Потолки импорта по умолчанию (из окружения, 0 — без потолка): файл ≤ ") + fmtCap(ov.capDefaults.filePages)
      + TR(" стр. · организация ≤ ") + fmtCap(ov.capDefaults.maxPages) + TR(" стр., ≤ ") + fmtCap(ov.capDefaults.maxProjects)
      + TR(" проектов. Своё — кнопки «Пополнить» (страницы, с журналом) и «Потолки» (проекты); помечено ★.")),
    React.createElement("div", { style: { overflowX: "auto" } }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Организация"), TR("Люди"), TR("Проекты"), TR("Страницы"), TR("Сегменты"), TR("Глоссарий"), TR("Расход за ") + ov.month, TR("Лимит"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, ov.tenants.map(t => [React.createElement("tr", { key: t.id, style: t.active === false ? { opacity: .55 } : null },
        React.createElement("td", null, React.createElement("b", null, t.name), " ", React.createElement("span", { className: "dim" }, t.id + (t.active === false ? TR(" · отключена") : ""))),
        React.createElement("td", null, t.activeUsers + (t.users !== t.activeUsers ? " / " + t.users : "")),
        React.createElement("td", { title: capTitle(t, "maxProjects") }, t.projects + capSuffix(t, "maxProjects")),
        React.createElement("td", { title: pagesTitle(t) }, (t.usage ? t.usage.pages : "—") + capSuffix(t, "maxPages")),
        React.createElement("td", null, t.segments),
        React.createElement("td", null, t.glossary + (t.domains ? TR(" · обл. ") + t.domains : "")),
        React.createElement("td", { style: { color: t.spend.over ? "var(--c-danger)" : undefined } },
          "$" + Number(t.spend.spentUsd).toFixed(2) + " · " + t.spend.calls + TR(" выз.") + (t.spend.unpriced ? TR(" · без цены ") + t.spend.unpriced : "")),
        React.createElement("td", null, t.limitUsd != null ? "$" + Number(t.limitUsd).toFixed(2) : "—"),
        React.createElement("td", { style: { whiteSpace: "nowrap", textAlign: "right" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setLimit(t) }, TR("Лимит")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => topUp(t) }, TR("Пополнить")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setCaps(t) }, TR("Потолки")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setLogFor(logFor === t.id ? null : t.id) }, TR("Журнал")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => simpleMode(t),
            title: t.simple ? TR("сейчас: без сумм и моделей на экране") : TR("сейчас: обычный режим") },
            t.simple ? TR("Режим ★") : TR("Режим")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => toggle(t) }, t.active === false ? TR("Включить") : TR("Отключить")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => del(t) }, TR("Удалить")))),
        logFor === t.id && React.createElement("tr", { key: t.id + ":log" },
          React.createElement("td", { colSpan: 9 }, React.createElement(AdminPagesLog, { log: t.pagesLog })))])))));
}

/* Журнал страниц организации: пополнения и списания, хвост с сервера.
   Вид записи и служебные пометки — КОДЫ, подпись даёт браузер (закон CLEAN_*). */
function pagesKindLabel(k) {
  return k === "credit" ? TR("пополнение") : k === "repeat" ? TR("повтор файла, без списания")
    : k === "init" ? TR("стартовый объём по проектам")
    : k === "reimport" ? TR("новая версия файла, за добавленные строки") : TR("списание");
}
function pagesNoteLabel(n) { return n === "env" ? TR("стартовый лимит из окружения") : (n || ""); }
function AdminPagesLog({ log }) {
  if (!log || !log.length) return React.createElement("div", { className: "dim" }, TR("Журнал страниц пуст"));
  return React.createElement("table", { className: "tbl", style: { fontSize: 12 } },
    React.createElement("tbody", null, log.slice().reverse().map((e, i) => React.createElement("tr", { key: i },
      React.createElement("td", null, e.at),
      React.createElement("td", null, pagesKindLabel(e.kind)),
      React.createElement("td", { style: { textAlign: "right" } }, (e.pages > 0 && e.kind === "credit" ? "+" : "") + e.pages),
      React.createElement("td", { className: "dim" }, [e.title, pagesNoteLabel(e.note), e.name].filter(Boolean).join(" · "))))));
}

function AdminUsers({ toast, tenants }) {
  const [users, setUsers] = useState([]);
  const [q, setQ] = useState("");
  const reload = () => window.API.safeCall(() => window.API.usersAll()).then(r => setUsers((r && r.users) || []));
  useEffect(() => { reload(); }, []);
  const patch = async (u, body, msg) => {
    try { await window.API.userUpdate(u.id, body); toast.success(msg, u.login); reload(); }
    catch (e) { toast.error(TR("Не удалось"), e.message || String(e)); }
  };
  const remove = async (u) => {
    if (!confirm(TR("Удалить учётную запись «") + u.login + "»?")) return;
    try { await window.API.userDelete(u.id); toast.success(TR("Удалён"), u.login); reload(); }
    catch (e) { toast.error(TR("Не удалён"), e.message || String(e)); }
  };
  const shown = users.filter(u => !q || (u.login + " " + (u.email || "") + " " + u.name + " " + u.tenant).toLowerCase().includes(q.toLowerCase()));
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "row between", style: { marginBottom: 8 } },
      React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Аккаунты · ") + users.length),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Input, { value: q, placeholder: TR("поиск: логин, имя, организация"), style: { maxWidth: 280 }, onChange: (e) => setQ(e.target.value) }),
        React.createElement(AdminUserAdd, { tenants, toast, onDone: reload }))),
    React.createElement("div", { style: { overflowX: "auto", maxHeight: 360, overflowY: "auto" } }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Логин"), TR("Почта"), TR("Имя"), TR("Организация"), TR("Роль"), TR("Создан"), TR("Состояние"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, shown.map(u => React.createElement("tr", { key: u.id },
        React.createElement("td", null, u.login, u.super ? React.createElement("span", { className: "dim" }, " · super") : null),
        React.createElement("td", { className: "dim" }, (u.email || "—") + (u.email && !u.emailVerified ? TR(" · не подтверждена") : "")),
        React.createElement("td", null, u.name),
        React.createElement("td", null, u.tenant),
        React.createElement("td", null, roleLabel(u.role)),
        React.createElement("td", { className: "dim" }, u.created || ""),
        React.createElement("td", null, u.active ? TR("активен") : TR("отключён")),
        React.createElement("td", { style: { whiteSpace: "nowrap", textAlign: "right" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => { const pw = prompt(TR("Новый пароль для ") + u.login + ":"); if (pw) patch(u, { password: pw }, TR("Пароль сменён")); } }, TR("Пароль")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => patch(u, { active: !u.active }, u.active ? TR("Отключён") : TR("Включён")) }, u.active ? TR("Отключить") : TR("Включить")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => remove(u) }, TR("Удалить")))))))));
}

/* Заведение учётной записи. Эндпоинт был с самого начала, кнопки не было —
   и завести человека можно было только запросом руками. Пароль предлагается
   сразу и читаемый: пустое поле «пароль» в форме для администратора кончается
   паролем «12345678». */
function randomPass() {
  const A = "abcdefghijkmnpqrstuvwxyz23456789";   // без похожих 0/O, 1/l
  let out = [];
  for (let g = 0; g < 3; g++) {
    let s = "";
    for (let i = 0; i < 4; i++) s += A[Math.floor(Math.random() * A.length)];
    out.push(s);
  }
  return out.join("-");
}

function AdminUserAdd({ tenants, onDone, toast }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ login: "", name: "", email: "", role: "translator", tenant: "", password: randomPass() });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  if (!open)
    return React.createElement(Btn, { size: "sm", onClick: () => { setF({ ...f, password: randomPass() }); setOpen(true); } },
      TR("Добавить пользователя"));
  const save = async () => {
    try {
      const r = await window.API.userCreate({
        login: f.login.trim(), name: f.name.trim(), email: f.email.trim(),
        role: f.role, tenant: f.tenant || undefined, password: f.password
      });
      // Пароль показываем ОДИН раз и целиком: на сервере лежит только его
      // хеш, и если администратор его сейчас не запишет — восстановить
      // будет нечего, останется только сменить.
      toast.success(TR("Заведён: ") + r.user.login, TR("пароль: ") + f.password);
      setOpen(false);
      setF({ login: "", name: "", email: "", role: "translator", tenant: "", password: randomPass() });
      onDone();
    } catch (e) { toast.error(TR("Не заведён"), e.message || String(e)); }
  };
  return React.createElement("div", { className: "col", style: { gap: 8, padding: "10px 0" } },
    React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
      React.createElement(Input, { value: f.login, placeholder: TR("логин"), style: { maxWidth: 150 }, onChange: set("login") }),
      React.createElement(Input, { value: f.name, placeholder: TR("имя"), style: { maxWidth: 150 }, onChange: set("name") }),
      React.createElement(Input, { value: f.email, placeholder: TR("почта (необязательно)"), style: { maxWidth: 190 }, onChange: set("email") }),
      React.createElement("select", { className: "input", value: f.role, style: { maxWidth: 140 }, onChange: set("role") },
        ["owner", "editor", "translator"].map(r => React.createElement("option", { key: r, value: r }, roleLabel(r)))),
      React.createElement("select", { className: "input", value: f.tenant, style: { maxWidth: 170 }, onChange: set("tenant") },
        React.createElement("option", { value: "" }, TR("своя организация")),
        (tenants || []).map(t => React.createElement("option", { key: t.id, value: t.id }, t.name || t.id))),
      React.createElement(Input, { value: f.password, style: { maxWidth: 160 }, onChange: set("password") }),
      React.createElement(Btn, { size: "sm", variant: "ghost", onClick: () => setF({ ...f, password: randomPass() }) }, TR("Другой пароль")),
      React.createElement(Btn, { size: "sm", onClick: save, disabled: !f.login.trim() || f.password.length < 8 }, TR("Завести")),
      React.createElement(Btn, { size: "sm", variant: "ghost", onClick: () => setOpen(false) }, TR("Отмена"))),
    React.createElement("p", { className: "dim", style: { fontSize: 12, margin: 0 } },
      TR("Пароль показывается один раз — на сервере хранится только его отпечаток. Новому человеку нужен лимит расхода и выданные страницы: их выдаёт карточка организации выше.")));
}

/* Тест-группа: наборы с числом мест, заведённые ботом тестировщики, анкеты.
   Лимит мест правится ЗДЕСЬ, потому что темп теста — решение владельца:
   пятерых за раз разобрать можно, пятьдесят нет. */
function AdminTesting({ toast }) {
  const [d, setD] = useState(null);
  const reload = () => window.API.safeCall(() => window.API.testing()).then(r => setD(r && r.ok ? r : null));
  useEffect(() => { reload(); }, []);
  if (!d) return null;
  const add = async () => {
    const id = prompt(TR("Идентификатор набора (латиница, цифры, дефис):"), "test-1");
    if (!id) return;
    const lim = prompt(TR("Сколько мест в наборе?"), "5");
    if (lim === null) return;
    const pages = prompt(TR("Сколько страниц выдать каждому?"), "30");
    if (pages === null) return;
    try {
      await window.API.batchCreate({ id: id.trim(), name: id.trim(), limit: Number(lim), pages: Number(pages) });
      toast.success(TR("Набор заведён"), id); reload();
    } catch (e) { toast.error(TR("Не заведён"), e.message || String(e)); }
  };
  const patch = async (b, body, msg) => {
    try { await window.API.batchUpdate(b.id, body); toast.success(msg, b.name || b.id); reload(); }
    catch (e) { toast.error(TR("Не изменено"), e.message || String(e)); }
  };
  const setLimit = (b) => {
    const v = prompt(TR("Сколько мест в наборе «") + (b.name || b.id) + TR("»? Выдано уже ") + (b.issued || 0) + ":", String(b.limit || 0));
    if (v === null || v.trim() === "") return;
    patch(b, { limit: Number(v) }, TR("Мест изменено"));
  };
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "row between", style: { marginBottom: 8 } },
      React.createElement("div", { className: "eyebrow", style: { margin: 0 } },
        TR("Тест-группа · наборов ") + d.batches.length + TR(" · тестировщиков ") + d.testers.length
        + TR(" · анкет ") + d.surveys.length),
      React.createElement(Btn, { size: "sm", onClick: add }, TR("Новый набор"))),
    // Бот без токена молчит, и молчание неотличимо от «никто не пишет».
    (!d.botReady || !d.serviceToken) && React.createElement("p", { className: "dim", style: { fontSize: 13, marginTop: 0 } },
      !d.botReady ? TR("Бот не настроен: нет TELEGRAM_BOT_TOKEN в окружении — доступ выдавать некому.")
        : TR("Нет TG_SERVICE_TOKEN: служебная дверь закрыта, бот не сможет завести тестировщика.")),
    React.createElement("div", { style: { overflowX: "auto" } }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Набор"), TR("Места"), TR("Страниц"), TR("Лимит $"), TR("Состояние"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, d.batches.map(b => React.createElement("tr", { key: b.id },
        React.createElement("td", null, b.name || b.id, React.createElement("span", { className: "dim" }, " · " + b.id)),
        React.createElement("td", null, (b.issued || 0) + " / " + (b.limit || 0),
          React.createElement("span", { className: "dim" }, TR(" · свободно ") + Math.max(0, (b.limit || 0) - (b.issued || 0)))),
        React.createElement("td", null, b.pages),
        React.createElement("td", null, b.limitUsd),
        React.createElement("td", null, b.active ? TR("идёт набор") : TR("закрыт")),
        React.createElement("td", { style: { textAlign: "right", whiteSpace: "nowrap" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setLimit(b) }, TR("Мест")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => patch(b, { active: !b.active }, b.active ? TR("Набор закрыт") : TR("Набор открыт")) },
            b.active ? TR("Закрыть") : TR("Открыть")))))))),
    d.testers.length > 0 && React.createElement("div", { style: { overflowX: "auto", marginTop: 12 } },
      React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("Тестировщики")),
      React.createElement("table", { className: "tbl" },
        React.createElement("thead", null, React.createElement("tr", null,
          [TR("Логин"), TR("Имя"), TR("Telegram"), TR("Набор"), TR("Язык"), TR("Страниц"), TR("Заведён")].map((h, i) => React.createElement("th", { key: i }, h)))),
        React.createElement("tbody", null, d.testers.map(u => React.createElement("tr", { key: u.login },
          React.createElement("td", null, u.login),
          React.createElement("td", null, u.name || "—"),
          React.createElement("td", { className: "dim" }, u.tgUser ? "@" + u.tgUser : "—"),
          React.createElement("td", null, u.batch || "—"),
          React.createElement("td", null, (u.uiLang || "").toUpperCase()),
          React.createElement("td", null, (u.usage && u.usage.used != null ? u.usage.used : "—") + " / "
            + (u.usage && u.usage.credit != null ? u.usage.credit : "∞")),
          React.createElement("td", { className: "dim" }, u.created || "")))))),
    d.surveys.length > 0 && React.createElement("div", { style: { marginTop: 12 } },
      React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("Анкеты")),
      React.createElement("div", { style: { maxHeight: 240, overflow: "auto" } },
        React.createElement("table", { className: "tbl" },
          React.createElement("tbody", null, d.surveys.map(s => React.createElement("tr", { key: s.id },
            React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap", fontSize: 12 } }, s.at),
            React.createElement("td", null, s.form === "apply" ? TR("заявка") : TR("разбор")),
            React.createElement("td", null, s.who || s.ref || "—"),
            React.createElement("td", null, (s.lang || "").toUpperCase()),
            React.createElement("td", { style: { textAlign: "right" } },
              React.createElement("a", { className: "link", href: "/t/a/" + s.token, target: "_blank", rel: "noopener" }, TR("Открыть лист"))))))))));
}

function AdminJobs({ ov, toast, onChange }) {
  const stop = async (j) => {
    try { await window.API.stopJob(j.id); toast.success(TR("Остановка запрошена"), TR("прогон №") + j.id); onChange(); }
    catch (e) { toast.error(TR("Не остановлен"), e.message || String(e)); }
  };
  const row = (j, active) => React.createElement("tr", { key: j.id },
    React.createElement("td", null, "№" + j.id + " · " + j.kind),
    React.createElement("td", null, j.tenant + TR(" · проект ") + j.project),
    React.createElement("td", null, j.status + (j.total ? " · " + j.done + "/" + j.total : "")),
    React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap" } }, j.started || j.created || ""),
    React.createElement("td", { className: "dim" }, j.usage && j.usage.cost != null ? "$" + Number(j.usage.cost).toFixed(3) : "", j.error ? " · " + j.error : ""),
    React.createElement("td", { style: { textAlign: "right" } }, active && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => stop(j) }, TR("Остановить"))));
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Прогоны · идёт ") + ov.jobs.active.length + TR(" · в очереди ") + ov.jobs.queued + (ov.jobs.workerAlive ? "" : TR(" · РАБОЧИЙ ПОТОК НЕ ЖИВ"))),
    React.createElement("div", { style: { overflowX: "auto" } }, React.createElement("table", { className: "tbl" },
      React.createElement("tbody", null,
        ov.jobs.active.map(j => row(j, true)),
        ov.jobs.recent.filter(j => !ov.jobs.active.some(a => a.id === j.id)).map(j => row(j, false))))),
    ov.jobs.recent.length === 0 && React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } }, TR("С момента старта сервиса прогонов не было (они живут в памяти процесса).")));
}

/* История входов. Два списка, потому что вопросы разные: события отвечают
   «что происходило» (включая неудачные попытки) и вытесняются кольцом,
   а срез по людям отвечает «кто когда заходил» и лежит НА ЗАПИСИ — по нему
   виден тот, кто не заходил ни разу, а такого в событиях нет по построению. */
function AdminLogins() {
  const [d, setD] = useState(null);
  useEffect(() => { window.API.safeCall(() => window.API.logins(200)).then(r => setD(r && r.ok ? r : null)); }, []);
  if (!d) return null;
  const never = d.users.filter(u => !u.lastLogin).length;
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Входы · событий ") + d.events.length + (never ? TR(" · ни разу не заходили: ") + never : "")),
    React.createElement("div", { className: "row row-wrap", style: { gap: 16, alignItems: "flex-start" } },
      React.createElement("div", { style: { flex: "1 1 320px", minWidth: 0 } },
        React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("Кто когда заходил")),
        React.createElement("div", { style: { maxHeight: 300, overflow: "auto" } },
          React.createElement("table", { className: "tbl" },
            React.createElement("tbody", null, d.users.map(u => React.createElement("tr", { key: u.id },
              React.createElement("td", null, u.login, u.tester ? React.createElement("span", { className: "dim" }, TR(" · тестировщик")) : null),
              React.createElement("td", { className: "dim" }, u.tenant),
              React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap" } },
                u.lastLogin || TR("ни разу")),
              React.createElement("td", { className: "dim" }, u.loginCount ? u.loginCount + TR(" вх.") : ""))))))),
      React.createElement("div", { style: { flex: "1 1 320px", minWidth: 0 } },
        React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("События")),
        React.createElement("div", { style: { maxHeight: 300, overflow: "auto" } },
          React.createElement("table", { className: "tbl" },
            React.createElement("tbody", null, d.events.map((r, i) => React.createElement("tr", { key: i },
              React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap", fontSize: 12 } }, r.at),
              React.createElement("td", { style: { color: r.action === "login.fail" ? "var(--c-danger)" : undefined } },
                r.action === "login.fail" ? TR("отказ") : TR("вход")),
              React.createElement("td", null, r.login || r.triedLogin || "—"),
              React.createElement("td", { className: "dim" }, r.tenant),
              React.createElement("td", { className: "dim", style: { fontSize: 12 } }, r.ip || "")))))))));
}

/* История прогонов с ФАКТИЧЕСКОЙ суммой. Берётся из runCosts, а не из
   списка задач: задачи живут в памяти процесса и теряются при рестарте,
   а расход терять нельзя — по нему калибруется смета. */
function AdminRuns() {
  const [d, setD] = useState(null);
  useEffect(() => { window.API.safeCall(() => window.API.runsHistory(100)).then(r => setD(r && r.ok ? r : null)); }, []);
  if (!d) return null;
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Прогоны с расходом · ") + d.runs.length + TR(" · всего $") + Number(d.totalUsd || 0).toFixed(2)
      + (d.estRatio ? TR(" · смета в среднем в ") + d.estRatio + TR(" раза от факта (по ") + d.estRuns + TR(" прогонам)") : "")),
    d.runs.length === 0 && React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } },
      TR("Прогонов с расходом ещё не было.")),
    React.createElement("div", { style: { maxHeight: 340, overflow: "auto" } },
      React.createElement("table", { className: "tbl" },
        React.createElement("thead", null, React.createElement("tr", null,
          [TR("Когда"), TR("Организация"), TR("Прогон"), TR("Сегментов"), TR("Смета"), TR("Факт"), TR("Вызовов")].map((h, i) => React.createElement("th", { key: i }, h)))),
        React.createElement("tbody", null, d.runs.map((r, i) => React.createElement("tr", { key: i },
          React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap", fontSize: 12 } }, r.finished || ""),
          React.createElement("td", null, r.tenant),
          React.createElement("td", null, "№" + r.job + " · " + r.kind
            + (r.status && r.status !== "done" ? " · " + r.status : "")),
          React.createElement("td", null, r.segments != null ? r.segments : "—"),
          React.createElement("td", { className: "dim" }, r.est != null ? "$" + Number(r.est).toFixed(3) : "—"),
          React.createElement("td", null, r.cost != null ? "$" + Number(r.cost).toFixed(3) : "—",
            r.unpriced ? React.createElement("span", { className: "dim", title: TR("вызовы, цена которых неизвестна") }, TR(" · без цены ") + r.unpriced) : null),
          React.createElement("td", { className: "dim" }, r.calls)))))));
}

function AdminAudit() {
  const [items, setItems] = useState([]);
  useEffect(() => { window.API.safeCall(() => window.API.auditAll(300)).then(r => setItems((r && r.items) || [])); }, []);
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } }, TR("Журнал всех организаций · ") + items.length),
    React.createElement("div", { style: { maxHeight: 320, overflow: "auto" } }, React.createElement("table", { className: "tbl" },
      React.createElement("tbody", null, items.map((r, i) => React.createElement("tr", { key: i },
        React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap", fontSize: 12 } }, r.at),
        React.createElement("td", null, r.tenant),
        React.createElement("td", null, r.login || "—"),
        React.createElement("td", null, (typeof AUDIT_LABELS !== "undefined" && AUDIT_LABELS[r.action]) || r.action),
        React.createElement("td", { className: "dim", style: { fontSize: 12 } },
          Object.keys(r).filter(k => !["at", "tenant", "user", "login", "action"].includes(k)).map(k => k + "=" + r[k]).join(" · "))))))));
}

function TabAdmin({ store, toast }) {
  const [ov, setOv] = useState(null);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!(store.can && store.can.super)) return;
    let dead = false;
    const tick = () => window.API.safeCall(() => window.API.adminOverview()).then(r => { if (!dead && r && r.ok) setOv(r); });
    tick();
    const h = setInterval(tick, 10000);
    return () => { dead = true; clearInterval(h); };
  }, [nonce, store.can && store.can.super]);
  if (!(store.can && store.can.super) || !window.ADMIN_ENTRY)
    return React.createElement("div", { className: "page" }, React.createElement("p", { className: "dim" }, TR("Этот экран доступен администратору сервиса по служебному адресу.")));
  const reload = () => setNonce(n => n + 1);
  const pr = ov && ov.process;
  return React.createElement("div", { className: "page page-wide" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, TR("Администрирование")),
      React.createElement("p", { className: "lead" }, TR("Все организации, аккаунты, прогоны и расход. Обновляется каждые 10 секунд."))),
    !ov && React.createElement("div", { className: "dim" }, TR("Загружаем сводку…")),
    ov && React.createElement("div", { className: "col", style: { gap: 16 } },
      React.createElement("div", { className: "row row-wrap", style: { gap: 10 } },
        React.createElement(AdminStat, { label: TR("Организаций"), value: ov.tenants.length }),
        React.createElement(AdminStat, { label: TR("Аккаунтов"), value: ov.tenants.reduce((a, t) => a + t.users, 0) }),
        React.createElement(AdminStat, { label: TR("Проектов / сегментов"), value: ov.tenants.reduce((a, t) => a + t.projects, 0) + " / " + ov.tenants.reduce((a, t) => a + t.segments, 0) }),
        React.createElement(AdminStat, { label: TR("Расход процесса с запуска"), value: "$" + Number(pr.usage.cost || 0).toFixed(2) + " · " + pr.usage.calls + TR(" выз."), warn: pr.usage.unpriced > 0 }),
        React.createElement(AdminStat, { label: TR("Аптайм"), value: fmtDur(pr.uptimeSec) }),
        React.createElement(AdminStat, { label: "state.json", value: fmtBytes(pr.stateBytes) }),
        React.createElement(AdminStat, { label: TR("Сессий"), value: pr.sessions }),
        React.createElement(AdminStat, { label: TR("Ключ OpenAI"), value: pr.openaiKey ? TR("есть") : TR("НЕТ"), warn: !pr.openaiKey }),
        React.createElement(AdminStat, { label: TR("Очередь терминов"), value: pr.termQueue })),
      React.createElement(AdminJobs, { ov, toast, onChange: reload }),
      React.createElement(AdminTenants, { ov, toast, onChange: reload }),
      React.createElement(AdminUsers, { toast, tenants: ov.tenants }),
      React.createElement(AdminTesting, { toast }),
      React.createElement(AdminRuns, null),
      React.createElement(AdminLogins, null),
      React.createElement(AdminAudit, null)));
}
