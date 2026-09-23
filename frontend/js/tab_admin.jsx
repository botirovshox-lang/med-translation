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
  /* Перевод ЗАНОВО поверх готового текста: предел на строку (0 — запрещено)
     и сколько раз можно перевести заново весь файл. Пусто — умолчание сервиса
     (ov.capDefaults). Суперпользователя предел не касается. */
  const setRetranslate = async (t) => {
    const d = ov.capDefaults || {};
    const a = prompt(TR("Сколько раз строку можно перевести заново для «") + t.name + TR("» (пусто — по умолчанию ")
      + (d.retranslateLimit != null ? d.retranslateLimit : "—") + TR(", 0 — запрещено):"),
      t.retranslateLimit != null ? t.retranslateLimit : "");
    if (a === null) return;
    const b = prompt(TR("Сколько раз можно перевести заново весь файл (пусто — по умолчанию ")
      + (d.retranslateBulk != null ? d.retranslateBulk : "—") + TR(", 0 — только администратор сервиса):"),
      t.retranslateBulk != null ? t.retranslateBulk : "");
    if (b === null) return;
    /* Целое ≥ 0 или пусто — проверка до отправки. Number("abc") — NaN, а NaN
       в JSON уезжает как null: опечатка превращалась в непонятный отказ
       сервера или в «не задано», вместо того чтобы быть названной здесь. */
    const bad = [a, b].some(v => v.trim() !== "" && !/^\d+$/.test(v.trim()));
    if (bad) { toast.error(TR("Не обновлён"), TR("Нужно целое число от 0 или пусто.")); return; }
    const body = (a.trim() === "" && b.trim() === "") ? { clearRetranslate: true } : {};
    if (a.trim() !== "") body.retranslateLimit = Number(a);
    if (b.trim() !== "") body.retranslateBulk = Number(b);
    try { await window.API.tenantUpdate(t.id, body); toast.success(TR("Предел перевода заново обновлён"), t.name); onChange(); }
    catch (e) { toast.error(TR("Не обновлён"), e.message || String(e)); }
  };
  /* Потолок НАШИХ затрат на страницу заказа (`budgetPerPage`). Настройка,
     которую нельзя выставить из интерфейса, выключена навсегда: колонка
     «$ на страницу» показывала бы числа, а поменять ставку было бы нечем.
     Пусто — умолчание сервиса, 0 — выключено. */
  const setBudget = async (t) => {
    const d = ov.capDefaults || {};
    const v = prompt(TR("Сколько мы готовы потратить на одну страницу заказа у «") + t.name
      + TR("», $ (пусто — по умолчанию ") + (d.budgetPerPage != null ? d.budgetPerPage : "—")
      + TR(", 0 — без потолка):"), t.budgetPerPage != null ? t.budgetPerPage : "");
    if (v === null) return;
    if (v.trim() !== "" && !/^\d+(\.\d+)?$/.test(v.trim())) {
      toast.error(TR("Не обновлён"), TR("Нужно число от 0 или пусто.")); return;
    }
    const body = v.trim() === "" ? { clearBudget: true } : { budgetPerPage: Number(v) };
    try { await window.API.tenantUpdate(t.id, body); toast.success(TR("Потолок на страницу обновлён"), t.name); onChange(); }
    catch (e) { toast.error(TR("Не обновлён"), e.message || String(e)); }
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
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setRetranslate(t),
            title: TR("перевод заново: строка ≤ ") + (t.retranslateLimit != null ? t.retranslateLimit : (ov.capDefaults || {}).retranslateLimit)
              + TR(", весь файл ≤ ") + (t.retranslateBulk != null ? t.retranslateBulk : (ov.capDefaults || {}).retranslateBulk) },
            (t.retranslateLimit != null || t.retranslateBulk != null) ? TR("Заново ★") : TR("Заново")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setBudget(t),
            title: TR("потолок наших затрат на страницу заказа, $: ")
              + (t.budgetPerPage != null ? t.budgetPerPage : ((ov.capDefaults || {}).budgetPerPage || 0)) },
            t.budgetPerPage != null ? TR("$/стр. ★") : TR("$/стр.")),
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
    : k === "reimport" ? TR("новая версия файла, за добавленные строки")
    : k === "edit" ? TR("дописано руками сверх файла") : TR("списание");
}
function pagesNoteLabel(n) { return n === "env" ? TR("стартовый лимит из окружения") : (n || ""); }
function AdminPagesLog({ log }) {
  if (!log || !log.length) return React.createElement("div", { className: "dim" }, TR("Журнал страниц пуст"));
  return React.createElement("div", { className: "tbl-fit" }, React.createElement("table", { className: "tbl", style: { fontSize: 12 } },
    React.createElement("tbody", null, log.slice().reverse().map((e, i) => React.createElement("tr", { key: i },
      React.createElement("td", null, e.at),
      React.createElement("td", null, pagesKindLabel(e.kind)),
      React.createElement("td", { style: { textAlign: "right" } }, (e.pages > 0 && e.kind === "credit" ? "+" : "") + e.pages),
      React.createElement("td", { className: "dim" }, [e.title, pagesNoteLabel(e.note), e.name].filter(Boolean).join(" · ")))))));
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
/* ---------- Программа приглашений: числа сервиса ----------
   Настройка, которую нельзя выставить из интерфейса, выключена навсегда
   (тот же довод, что у «$/стр.»), поэтому карточка есть всегда — даже
   когда программа выключена: включать её надо где-то.

   Числа отсюда и есть источник правды для начисления; в `tab_org.jsx`
   их только ПОКАЗЫВАЮТ, пришедшими с сервера. Вторая копия чисел в .jsx
   разошлась бы с той, по которой платят. */
function AdminReferral({ toast }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => window.API.safeCall(() => window.API.referralCfg())
    .then(r => r && setD(r.referral));
  useEffect(() => { load(); }, []);
  if (!d) return null;
  const save = async (body) => {
    setBusy(true);
    try { const r = await window.API.referralSave(body); setD(r.referral); toast.success(TR("Сохранено")); }
    catch (e) { toast.error(TR("Не сохранено"), e.message || String(e)); }
    setBusy(false);
  };
  const num = (key, label, hint) => React.createElement("label", {
    className: "col", style: { gap: 4, flex: "1 1 170px", minWidth: 0 } },
    React.createElement("span", { className: "dim", style: { fontSize: 12 } }, label),
    React.createElement("input", {
      type: "number", min: 0, step: "0.1", defaultValue: d[key],
      style: { fontSize: 16 },
      onBlur: e => { const v = Number(e.target.value); if (v !== d[key]) save({ [key]: v }); } }),
    hint ? React.createElement("span", { className: "dim", style: { fontSize: 11 } }, hint) : null);
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 10 } },
    React.createElement("div", { className: "row between", style: { alignItems: "center" } },
      React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Приглашения")),
      React.createElement("label", { className: "row", style: { gap: 6, fontSize: 13 } },
        React.createElement("input", { type: "checkbox", checked: !!d.enabled, disabled: busy,
          onChange: e => save({ enabled: e.target.checked }) }),
        TR("Программа включена"))),
    React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 12 } },
      TR("Страницы начисляются, когда приглашённый ПОДТВЕРДИТ почту, и процентом — когда вы пополните ему страницы. Все нули — программа не раздаёт ничего.")),
    React.createElement("div", { className: "row row-wrap", style: { gap: 10 } },
      num("signupPages", TR("Пригласившему за регистрацию, стр.")),
      num("welcomePages", TR("Приглашённому при входе, стр.")),
      num("percent", TR("% от выданных ему страниц")),
      num("maxPerInvitee", TR("Потолок с одного, стр."), TR("0 — без потолка")),
      num("maxTotal", TR("Потолок на организацию, стр."), TR("0 — без потолка"))),
    React.createElement("div", { className: "dim", style: { fontSize: 12 } },
      TR("Уже начислено страниц: ") + (d.awarded || 0) + TR(" · пришло по ссылкам: ") + (d.invited || 0)));
}

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
  // Возврат выданного места. Отдельно от «Мест» намеренно: лимит — сколько
  // людей мы зовём, «выдано» — сколько доступов ушло. Пробный доступ,
  // выданный владельцем себе, лечился бы поднятием лимита — то есть враньём
  // в числе, по которому бот решает, звать ли ещё людей.
  const setIssued = (b) => {
    const v = prompt(TR("Сколько мест уже выдано в наборе «") + (b.name || b.id) + TR("»? Доступы при этом не отзываются."), String(b.issued || 0));
    if (v === null || v.trim() === "") return;
    patch(b, { issued: Number(v) }, TR("Выдано изменено"));
  };
  const dropSurvey = async (s) => {
    if (!confirm(TR("Убрать анкету от ") + (s.who || s.ref || "—") + TR("? Отката нет."))) return;
    try { await window.API.surveyDelete(s.id); toast.success(TR("Анкета убрана"), s.who || s.ref || ("#" + s.id)); reload(); }
    catch (e) { toast.error(TR("Не убрана"), e.message || String(e)); }
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
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setIssued(b) }, TR("Выдано")),
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
            React.createElement("td", { style: { textAlign: "right", whiteSpace: "nowrap" } },
              React.createElement("a", { className: "link", href: "/t/a/" + s.token, target: "_blank", rel: "noopener" }, TR("Открыть лист")),
              React.createElement(Btn, { variant: "ghost", size: "sm", style: { marginLeft: 8 }, onClick: () => dropSurvey(s) }, TR("Убрать"))))))))));
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
/* Расход ПО ПРОЕКТУ — счётчиком сервера (`byProject`): в нём и одиночные
   кнопки, и прогоны старше кольца runCosts. Идущие прогоны — живым счётчиком
   задачи (`live`). Карточка обновляется сама раз в 10 с, пока вкладка
   на экране: смотреть, сколько уходит сейчас, надо сейчас. */
const RUNS_REFRESH_MS = 10000;
function adminProjectName(r) {
  if (r.project == null) return "—";
  return (r.projectName ? r.projectName + " · " : "") + "№" + r.project
    + (r.deleted ? TR(" · удалён") : "");
}
function AdminRuns() {
  const [d, setD] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => window.API.safeCall(() => window.API.runsHistory(100))
      .then(r => { if (alive && r && r.ok) setD(r); });
    load();
    const t = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      load();
    }, RUNS_REFRESH_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!d) return null;
  const byProject = d.byProject || [], live = d.live || [];
  const money = (v) => v != null ? "$" + Number(v).toFixed(3) : "—";
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Прогоны с расходом · ") + d.runs.length + TR(" · всего $") + Number(d.shownUsd || 0).toFixed(2)
      + (d.estRatio ? TR(" · смета в среднем в ") + d.estRatio + TR(" раза от факта (по ") + d.estRuns + TR(" прогонам)") : "")),
    live.length > 0 && React.createElement("div", { style: { margin: "0 0 12px", overflowX: "auto" } },
      React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("Идут сейчас")),
      React.createElement("table", { className: "tbl" },
        React.createElement("tbody", null, live.map(j => React.createElement("tr", { key: j.job },
          React.createElement("td", null, "№" + j.job + " · " + j.kind + " · " + j.status),
          React.createElement("td", null, j.tenant),
          React.createElement("td", null, adminProjectName(j)),
          React.createElement("td", null, (j.done || 0) + "/" + (j.total || 0)),
          React.createElement("td", { className: "dim" }, j.est != null ? money(j.est) : "—"),
          React.createElement("td", null, money(j.cost))))))),
    byProject.length > 0 && React.createElement("div", { style: { maxHeight: 300, overflow: "auto", margin: "0 0 12px" } },
      React.createElement("table", { className: "tbl" },
        React.createElement("thead", null, React.createElement("tr", null,
          [TR("Организация"), TR("Проект"), TR("Прогонов"), TR("Факт $ по проекту"), TR("$ на страницу"), TR("Вызовов"), TR("Смета / факт")].map((h, i) => React.createElement("th", { key: i }, h)))),
        React.createElement("tbody", null, byProject.map((r, i) => React.createElement("tr", { key: i },
          React.createElement("td", null, r.tenant),
          React.createElement("td", null, adminProjectName(r)),
          React.createElement("td", null, r.runs),
          React.createElement("td", null, money(r.usd),
            r.unpriced ? React.createElement("span", { className: "dim", title: TR("вызовы, цена которых неизвестна") }, TR(" · без цены ") + r.unpriced) : null),
          /* Расход на СТРАНИЦУ ЗАКАЗА: слева — сколько мы потратили,
             справа — за сколько продано. Порога тут нет и прогон он
             не останавливает: ставку выбирают по боевым числам. */
          /* Потолок на файл (если назначен) — тем же числом, каким прогон
             останавливается: второй расчёт в браузере разошёлся бы с рубежом. */
          React.createElement("td", { className: r.budget && r.budget.over ? "bad" : "dim",
                                      title: r.pages ? TR("страниц в проекте: ") + r.pages : "" },
            r.usdPerPage != null ? money(r.usdPerPage) : "—",
            r.budget ? React.createElement("span", { className: "dim" },
              TR(" из ") + money(r.budget.rate)) : null),
          React.createElement("td", { className: "dim" }, r.calls),
          React.createElement("td", { className: "dim" }, r.estActualUsd ? money(r.estUsd) + " / " + money(r.estActualUsd) : "—")))))),
    d.runs.length === 0 && React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } },
      TR("Прогонов с расходом ещё не было.")),
    React.createElement("div", { style: { maxHeight: 340, overflow: "auto" } },
      React.createElement("table", { className: "tbl" },
        React.createElement("thead", null, React.createElement("tr", null,
          [TR("Когда"), TR("Организация"), TR("Проект"), TR("Прогон"), TR("Сегментов"), TR("Смета"), TR("Факт"), TR("Вызовов")].map((h, i) => React.createElement("th", { key: i }, h)))),
        React.createElement("tbody", null, d.runs.map((r, i) => React.createElement("tr", { key: i },
          React.createElement("td", { className: "dim", style: { whiteSpace: "nowrap", fontSize: 12 } }, r.finished || ""),
          React.createElement("td", null, r.tenant),
          React.createElement("td", null, adminProjectName(r)),
          React.createElement("td", null, "№" + r.job + " · " + r.kind
            + (r.status && r.status !== "done" ? " · " + r.status : "")),
          React.createElement("td", null, r.segments != null ? r.segments : "—"),
          React.createElement("td", { className: "dim" }, money(r.est)),
          React.createElement("td", null, money(r.cost),
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

/* ── Модели шагов на всю систему ──────────────────────────────────────────
   Пустое — умолчание кода. Настройка подменяет УМОЛЧАНИЕ, поэтому сильнее её
   модель, назначенная организации в упрощённом режиме, и явный выбор в
   редакторе. Подписи шагов — здесь, сервер отдаёт только ключи. */
function adminStepLabel(k) {
  const L = { translate: TR("Перевод"), review: TR("Ревизия"), backcheck: "back-check",
    termcheck: TR("Проверка терминов"), termaudit: TR("Сверка терминов"), repair: TR("Ремонт"),
    judge: TR("Судья"), ocr: TR("Текст на картинках"), terms: TR("Извлечение терминов"),
    // Смета скана — те же деньги на ту же модель, но потраченные ДО заказа,
    // на файл, который могут и не принести. Своей строкой именно поэтому.
    scanquote: TR("Смета скана (до заказа)"),
    termcross: TR("Кросс-проверка терм-листа"), embed: TR("Эмбеддинги") };
  return L[k] || k;
}
function adminModelName(models, id) {
  const m = (models || []).find(x => x.id === id);
  return m ? m.label : (id || "—");
}
function adminPrice(models, id) {
  const m = (models || []).find(x => x.id === id);
  return m ? "$" + m.in + " / $" + m.out : "";
}
function adminUsd(v) { return v == null ? "—" : "$" + Number(v).toFixed(v !== 0 && Math.abs(v) < 1 ? 4 : 2); }

function AdminSystemModels({ toast, onSaved }) {
  const [d, setD] = useState(null);
  const [draft, setDraft] = useState({});
  const [busy, setBusy] = useState(false);
  /* Какое предупреждение сейчас в фокусе (наведение или клик): его пара
     строк выделяется сильнее остальных спорящих. Клик держит выделение,
     наведение — пока мышь на строке предупреждения. */
  const [hot, setHot] = useState(null);
  const [pinned, setPinned] = useState(null);
  const load = () => window.API.safeCall(() => window.API.systemModels()).then(r => {
    if (!r || !r.ok) return;
    setD(r);
    const o = {};
    r.steps.forEach(s => { o[s.key] = s.value || ""; });
    setDraft(o);
  });
  useEffect(() => { load(); }, []);
  if (!d) return React.createElement("div", { className: "card card-pad dim" }, TR("Загружаем модели…"));
  const dirty = d.steps.some(s => (s.value || "") !== (draft[s.key] || ""));
  /* Спор моделей по РОЛИ — тем же правилом, что в панели запуска
     (`modelRoleConflicts` в ui.jsx). Считается по ЧЕРНОВИКУ, а не по тому,
     что действует: человек решает прямо сейчас, и узнать о споре он должен
     до «Сохранить», а не после. Пустой выбор раскрыт в умолчание КОДА —
     иначе спор двух шагов, оба оставленных «по умолчанию», был бы не виден,
     хотя работать они будут одной моделью (в таблице это и стоит справа). */
  const eff = {};
  d.steps.forEach(s => { eff[s.key] = draft[s.key] || s.codeDefault || ""; });
  const conflicts = modelRoleConflicts(eff, (id) => adminModelName(d.models, id));
  /* Для каждой строки — С КЕМ она спорит: человеку нужно видеть не только
     «здесь что-то не так», но и какую строку менять. Подсвечиваются ровно
     спорящие строки, а у строки сказано, с каким шагом у неё одна модель. */
  const disputed = {};
  conflicts.forEach(c => c.steps.forEach(k => {
    const other = c.steps.filter(x => x !== k);
    disputed[k] = (disputed[k] || []).concat(other.filter(x => (disputed[k] || []).indexOf(x) < 0));
  }));
  const focus = pinned != null ? pinned : hot;
  const focusSteps = (focus != null && conflicts[focus]) ? conflicts[focus].steps : [];
  const save = async () => {
    setBusy(true);
    try {
      const r = await window.API.systemModelsSave(draft);
      setD(r);
      toast.success(TR("Модели сохранены"), TR("открытые вкладки увидят их после обновления страницы"));
      if (onSaved) onSaved(r);
    } catch (e) { toast.error(TR("Не сохранено"), e.message || String(e)); }
    finally { setBusy(false); }
  };
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "row between", style: { marginBottom: 8 } },
      React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, TR("Модели шагов на всю систему")),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        dirty && React.createElement(Btn, { variant: "ghost", size: "sm", onClick: load }, TR("Отменить")),
        React.createElement(Btn, { size: "sm", disabled: !dirty || busy, onClick: save }, busy ? TR("Сохраняем…") : TR("Сохранить")))),
    React.createElement("p", { className: "dim", style: { margin: "0 0 8px", fontSize: 13 } },
      TR("Модель, которой шаг идёт, когда её не выбрали явно. Пусто — умолчание кода. Сильнее системной только модель, назначенная организации в упрощённом режиме, и явный выбор в редакторе.")),
    /* Спор называется вслух и ДО сохранения: назначенные здесь модели уходят
       умолчанием всем организациям сразу, и цена ошибки выше, чем у выбора
       на один прогон. Сохранить это не мешает — бывает, что так и надо. */
    conflicts.length > 0 && React.createElement("div", { className: "col", style: { gap: 4, margin: "0 0 10px" } },
      React.createElement("div", { className: "dim", style: { fontSize: 12 } },
        TR("Спорящие строки подсвечены в таблице. Наведите на предупреждение или нажмите его — выделится ровно его пара строк.")),
      conflicts.map((c, i) => React.createElement("div", { key: "c" + i,
        className: "adm-conflict" + (focus === i ? " on" : ""),
        role: "button", tabIndex: 0,
        onMouseEnter: () => setHot(i), onMouseLeave: () => setHot(null),
        onFocus: () => setHot(i), onBlur: () => setHot(null),
        onClick: () => setPinned(pinned === i ? null : i),
        onKeyDown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPinned(pinned === i ? null : i); } },
        style: { fontSize: 12.5, color: "var(--c-warning)", lineHeight: 1.5 } },
        "⚠ " + c.text))),
    React.createElement("div", { style: { overflowX: "auto" } }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Шаг"), TR("Модель"), TR("Цена за 1M токенов, вход / выход"), TR("Действует сейчас")].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, d.steps.map(s => React.createElement("tr", { key: s.key,
          className: disputed[s.key] ? ("adm-dispute" + (focusSteps.indexOf(s.key) >= 0 ? " on" : "")) : undefined },
        React.createElement("td", null, adminStepLabel(s.key),
          disputed[s.key] && React.createElement("span", { style: { color: "var(--c-warning)" },
            title: TR("Эта модель спорит по роли с моделью другого шага — см. предупреждение над таблицей") }, " ⚠"),
          disputed[s.key] && React.createElement("div", { style: { fontSize: 11.5, color: "var(--c-warning)", marginTop: 2 } },
            TR("та же модель, что у: ") + disputed[s.key].map(adminStepLabel).join(", "))),
        React.createElement("td", null,
          React.createElement("select", { className: "input" + (disputed[s.key] ? " adm-dispute-input" : ""),
            value: draft[s.key] || "", style: { maxWidth: 260 },
            onChange: (e) => setDraft({ ...draft, [s.key]: e.target.value }) },
            React.createElement("option", { value: "" }, TR("по умолчанию: ") + adminModelName(d.models, s.codeDefault)),
            d.models.map(m => React.createElement("option", { key: m.id, value: m.id, disabled: m.ready === false }, m.label + (m.ready === false ? TR(" — нет ключа") : ""))))),
        React.createElement("td", { className: "dim" }, adminPrice(d.models, draft[s.key] || s.codeDefault)),
        React.createElement("td", { className: "dim" }, adminModelName(d.models, s.effective))))))));
}

/* ── Виртуальный пересчёт ──────────────────────────────────────────────────
   Те же токены журнала — по ценам выбранных моделей. Модели по умолчанию —
   нынешние системные: вопрос «во что обошёлся бы период при этих настройках».
   Считает сервер (ни одного вызова модели). */
function adminLocalDay(offset) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}
function adminSysPreset(sys) {
  const o = {};
  ((sys && sys.steps) || []).forEach(s => { o[s.key] = s.effective || ""; });
  return o;
}

function AdminUsageSim({ toast, tenants, sys }) {
  const [from, setFrom] = useState(adminLocalDay(-29));
  const [to, setTo] = useState(adminLocalDay(0));
  const [tenant, setTenant] = useState("");
  const [user, setUser] = useState("");
  const [models, setModels] = useState(null);
  const [users, setUsers] = useState([]);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { window.API.safeCall(() => window.API.usersAll()).then(r => setUsers((r && r.users) || [])); }, []);
  const catalog = (sys && sys.models) || [];
  const chosen = models || adminSysPreset(sys);
  const run = async (m) => {
    setBusy(true);
    try {
      const clean = {};
      Object.keys(m).forEach(k => { if (m[k]) clean[k] = m[k]; });
      setRes(await window.API.usageSimulate({ dateFrom: from, dateTo: to, tenant: tenant || null, user: user || null, models: clean }));
    } catch (e) { toast.error(TR("Не посчитано"), e.message || String(e)); }
    finally { setBusy(false); }
  };
  const pick = (grp, id) => { const next = { ...chosen, [grp]: id }; setModels(next); if (res) run(next); };
  const preset = (days) => { setFrom(adminLocalDay(-(days - 1))); setTo(adminLocalDay(0)); };
  const shownUsers = users.filter(u => !tenant || u.tenant === tenant);
  const t = res && res.total;
  const delta = t ? t.sim - t.actual : 0;
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } }, TR("Виртуальный пересчёт расхода")),
    React.createElement("p", { className: "dim", style: { margin: "0 0 10px", fontSize: 13 } },
      TR("Сколько стоил бы расход за период, если бы шаги шли выбранными моделями. Считаются те же токены по другим ценам: без скидки на кэш и с тем же числом токенов рассуждения — это оценка, а не прогноз.")),
    React.createElement("div", { className: "row row-wrap", style: { gap: 8, alignItems: "center" } },
      React.createElement("input", { type: "date", className: "input", value: from, style: { maxWidth: 160 }, onChange: (e) => setFrom(e.target.value) }),
      React.createElement("span", { className: "dim" }, "—"),
      React.createElement("input", { type: "date", className: "input", value: to, style: { maxWidth: 160 }, onChange: (e) => setTo(e.target.value) }),
      [[7, TR("7 дней")], [30, TR("30 дней")], [90, TR("90 дней")]].map(([n, label]) =>
        React.createElement(Btn, { key: n, variant: "ghost", size: "sm", onClick: () => preset(n) }, label)),
      React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => { setFrom(adminLocalDay(0).slice(0, 8) + "01"); setTo(adminLocalDay(0)); } }, TR("Этот месяц")),
      React.createElement("select", { className: "input", value: tenant, style: { maxWidth: 200 },
        onChange: (e) => { setTenant(e.target.value); setUser(""); } },
        React.createElement("option", { value: "" }, TR("вся система")),
        (tenants || []).map(x => React.createElement("option", { key: x.id, value: x.id }, x.name || x.id))),
      React.createElement("select", { className: "input", value: user, style: { maxWidth: 220 }, onChange: (e) => setUser(e.target.value) },
        React.createElement("option", { value: "" }, TR("все пользователи")),
        shownUsers.map(u => React.createElement("option", { key: u.id, value: u.id }, u.login + " · " + u.tenant))),
      React.createElement(Btn, { size: "sm", disabled: busy || !from || !to, onClick: () => run(chosen) }, busy ? TR("Считаем…") : TR("Посчитать"))),
    res && React.createElement("div", { className: "col", style: { gap: 12, marginTop: 12 } },
      React.createElement("div", { className: "row row-wrap", style: { gap: 10 } },
        React.createElement(AdminStat, { label: TR("Факт"), value: adminUsd(t.actual) }),
        React.createElement(AdminStat, { label: TR("По выбранным моделям"), value: adminUsd(t.sim) }),
        React.createElement(AdminStat, { label: TR("Разница"),
          value: (delta > 0 ? "+" : "") + adminUsd(delta) + (t.actual ? " · " + (delta > 0 ? "+" : "") + Math.round(delta / t.actual * 100) + "%" : ""),
          warn: delta > 0 }),
        React.createElement(AdminStat, { label: TR("Вызовов"), value: t.calls })),
      React.createElement("p", { className: "dim", style: { margin: 0, fontSize: 12 } },
        (res.ledgerSince ? TR("Журнал токенов ведётся с ") + res.ledgerSince + ". " : TR("Журнал токенов пока пуст. "))
        + (res.historyRows ? TR("Строк из истории прогонов в периоде: ") + res.historyRows + TR(" — у них нет автора, а одиночные вызовы туда не попадали. ") : "")
        + (t.unpriced ? TR("Вызовов без цены в факте: ") + t.unpriced + ". " : "")),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => { const m = adminSysPreset(sys); setModels(m); run(m); } }, TR("Модели как в настройках")),
        React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => { setModels({}); run({}); } }, TR("Без замены"))),
      React.createElement("div", { style: { overflowX: "auto" } }, React.createElement("table", { className: "tbl" },
        React.createElement("thead", null, React.createElement("tr", null,
          [TR("Шаг"), TR("Вызовов"), TR("Токены вход / выход"), TR("Факт"), TR("Модель пересчёта"), TR("Пересчёт")].map((h, i) => React.createElement("th", { key: i }, h)))),
        React.createElement("tbody", null, res.groups.map(g => React.createElement("tr", { key: g.group },
          React.createElement("td", null, adminStepLabel(g.group)),
          React.createElement("td", null, g.calls),
          React.createElement("td", { className: "dim" }, g.in.toLocaleString() + " / " + g.out.toLocaleString()),
          React.createElement("td", { title: Object.keys(g.actualModels || {}).map(id => adminModelName(catalog, id) + ": " + g.actualModels[id]).join(", ") },
            adminUsd(g.actual), g.unpriced ? React.createElement("span", { className: "dim" }, TR(" · без цены ") + g.unpriced) : null),
          React.createElement("td", null, g.simulable
            ? React.createElement("select", { className: "input", value: chosen[g.group] || "", style: { maxWidth: 220 },
                onChange: (e) => pick(g.group, e.target.value) },
                React.createElement("option", { value: "" }, TR("как было")),
                catalog.map(m => React.createElement("option", { key: m.id, value: m.id }, m.label + " · $" + m.in + " / $" + m.out)))
            : React.createElement("span", { className: "dim" }, TR("не пересчитывается"))),
          React.createElement("td", null, adminUsd(g.sim))))))),
      res.byUser.length > 0 && React.createElement("div", { style: { overflowX: "auto", maxHeight: 320, overflowY: "auto" } },
        React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("По людям")),
        React.createElement("table", { className: "tbl" },
          React.createElement("thead", null, React.createElement("tr", null,
            [TR("Человек"), TR("Организация"), TR("Вызовов"), TR("Факт"), TR("Пересчёт")].map((h, i) => React.createElement("th", { key: i }, h)))),
          React.createElement("tbody", null, res.byUser.map(u => React.createElement("tr", { key: u.user || "-" },
            React.createElement("td", null, u.user ? (u.login || u.user) + (u.name && u.name !== u.login ? " · " + u.name : "") : TR("без автора")),
            React.createElement("td", { className: "dim" }, u.home || "—"),
            React.createElement("td", null, u.calls),
            React.createElement("td", null, adminUsd(u.actual)),
            React.createElement("td", null, adminUsd(u.sim)))))))));
}

function AdminModelsView({ toast, tenants }) {
  const [sys, setSys] = useState(null);
  useEffect(() => { window.API.safeCall(() => window.API.systemModels()).then(r => { if (r && r.ok) setSys(r); }); }, []);
  return React.createElement("div", { className: "col", style: { gap: 16 } },
    React.createElement(AdminSystemModels, { toast, onSaved: setSys }),
    React.createElement(AdminUsageSim, { toast, tenants, sys }));
}

/* ─── Вкладка «Метрики»: где теряем, где заработать, что чинить ───────
 *
 * Экран отвечает на ВОПРОС, а не показывает счётчики. Порядок разделов —
 * по деньгам: подсказки (что делать сегодня), организации (кому продавать
 * и кто в убытке), расход по шагам, потолки; техническое — маршруты,
 * скорость, ошибки — убрано под «Подробности», потому что это работа
 * разработчика, а не владельца.
 *
 * Подсказки приходят с сервера КОДАМИ (`kind` + `code` + числа), а текст
 * собирается здесь: правило одно, а языков у интерфейса несколько
 * (инвариант 17). Число при этом стоит РЯДОМ с переведённой фразой,
 * а не внутри неё: строка с подстановкой требовала бы шаблона в каждом
 * словаре, а первый же забытый шаблон показал бы «{n}» живому человеку.
 *
 * Обновление — по нажатию, а не по таймеру: сводка обходит организации
 * и проекты, а воркер у сервиса ОДИН (инвариант 1) — десятисекундный
 * опрос этого экрана отнимал бы его у переводчиков.
 */
const MET_DAYS = [1, 7, 30, 90];

/* Вид подсказки решает ЦВЕТ и порядок. Виды три и они разные по смыслу:
   money — где взять деньги, loss — где они утекают, fix — где сломано. */
const MET_KIND = { money: "ok", loss: "warn", fix: "bad" };

/* Заголовок вида — ЛИТЕРАЛОМ внутри TR(), а не полем объекта: ключи словаря
   собираются из исходника разбором `TR("…")`, и строка, доехавшая до TR()
   переменной, не попала бы в словарь ВООБЩЕ — на узбекском экране она
   осталась бы русской, и ни один тест этого бы не заметил. */
function metKindTitle(kind) {
  if (kind === "money") return TR("Деньги на столе");
  if (kind === "loss") return TR("Теряем");
  return TR("Чинить");
}

/* Код подсказки → фраза. Ключ словаря — сама русская строка (инвариант 17),
   поэтому число в неё не входит: оно рисуется отдельным элементом. */
function metHintText(code) {
  switch (code) {
    case "bigFiles": return TR("раз файл не взяли — он толще потолка страниц. Это спрос на большие документы: потолок можно поднять платно");
    case "heavyFiles": return TR("раз файл не взяли — он тяжелее потолка в мегабайтах");
    case "pagesOut": return TR("отказов «кончились выданные страницы» — пора предлагать пакет");
    case "spendOut": return TR("отказов «исчерпан месячный лимит расхода»");
    case "formats": return TR("раз просили формат, которого у нас нет — это список, какой импорт писать следующим");
    case "duplicate": return TR("раз пытались загрузить тот же файл второй раз");
    case "invoicedUnpaid": return TR("смет выставлено и не оплачено");
    case "pagesLow": return TR("страниц осталось — предложите пополнение заранее");
    case "idle": return TR("дней без единого прогона при неизрасходованных страницах: это отток с предоплатой на счету");
    case "thinMargin": return TR("процентов цены страницы остаётся после себестоимости");
    case "estOff": return TR("во столько раз смета расходится с фактом");
    case "heavy": return TR("во столько раз больше медианы тратит эта организация — кандидат на отдельный тариф");
    case "uploadNoRun": return TR("файлов принесли и ни одного прогона не запустили: разбор каждого мы уже оплатили");
    // Оговорка про когорту — В САМОЙ ФРАЗЕ, а не в подсказке рядом:
    // считаются события периода, и удалить могли не то, что принесли.
    // Без неё строка звучит обвинением, которого мы доказать не можем.
    case "uploadChurn": return TR("принесённых файлов удалено за период (не обязательно те же самые): разбор мы оплатили, а заказом это не стало");
    case "http5xx": return TR("ошибок сервера: отказ в обслуживании");
    case "slowRoute": return TR("мс в среднем отвечает маршрут");
    case "waste:repairReverted": return TR("правок ремонта откатилось — за них заплачено");
    case "waste:reviewVeto": return TR("готовых правок ревизии не прошли сверку — за них заплачено");
    case "waste:refusal": return TR("отказов модели отвечать: токены выставлены в счёт");
    case "waste:jobStopped:limit": return TR("прогонов остановлено исчерпанным лимитом");
    case "waste:jobStopped:provider_quota": return TR("прогонов остановлено пустым счётом у поставщика");
    case "provider:quota": return TR("раз у поставщика моделей кончились деньги");
    case "provider:rate": return TR("раз поставщик ответил «слишком часто» (rate limit)");
    case "provider:timeout": return TR("раз поставщик не ответил: сеть или таймаут");
    case "provider:other": return TR("прочих ошибок поставщика моделей");
    default: return code;
  }
}

/* Число подсказки: у доли и отношения свой вид, иначе «0.42 раза»
   читается как ошибка, а не как отношение сметы к факту. */
function metHintNum(h) {
  if (h.code === "thinMargin") return Math.round(100 - (h.n || 0)) + "%";
  if (h.code === "estOff" || h.code === "heavy") return "×" + h.n;
  if (h.code === "pagesLow") return Number(h.n).toFixed(1);
  // У оттока знаменатель НЕСУЩИЙ: «4 удалено» без «из 4 принесённых» —
  // наблюдение, а не доля, и суточный текст на сервере говорит «из N»,
  // то есть экран и Telegram рассказывали бы про одно число разное.
  if (h.code === "uploadChurn" && h.of) return h.n + "/" + h.of;
  return String(h.n);
}

function MetHint({ h }) {
  const cls = MET_KIND[h.kind] || MET_KIND.fix;
  const who = (h.who || []).map(w => w.tenant + " (" + w.n + ")").join(", ");
  const items = (h.items || []).map(i => i.ext + "×" + i.n).join(", ");
  return React.createElement("li", { className: "met-hint" },
    React.createElement("b", { className: "met-num " + cls }, metHintNum(h)),
    React.createElement("span", null, " ", metHintText(h.code),
      h.name ? React.createElement("span", { className: "dim" }, " — " + h.name) : null,
      h.route ? React.createElement("span", { className: "dim" }, " — " + h.route) : null,
      items ? React.createElement("span", { className: "dim" }, " — " + items) : null,
      h.total != null ? React.createElement("span", { className: "dim" },
        " — " + h.total + " " + (h.currency || "")) : null,
      who ? React.createElement("span", { className: "dim" }, " · " + TR("кто: ") + who) : null));
}

function MetHints({ m }) {
  const hints = m.hints || [];
  if (!hints.length)
    return React.createElement("div", { className: "card card-pad" },
      React.createElement("p", { className: "dim", style: { margin: 0 } },
        TR("Ни одной находки за период: в потолки никто не упёрся, сметы сходятся, ошибок нет. Это ответ, а не пустой экран.")));
  return React.createElement("div", { className: "col", style: { gap: 12 } },
    Object.keys(MET_KIND).map(kind => {
      const mine = hints.filter(h => h.kind === kind);
      if (!mine.length) return null;
      return React.createElement("div", { key: kind, className: "card card-pad" },
        React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
          metKindTitle(kind)),
        React.createElement("ul", { className: "met-list" },
          mine.map((h, i) => React.createElement(MetHint, { key: i, h }))));
    }));
}

function metUsd(v) { return v == null ? "—" : "$" + Number(v).toFixed(Math.abs(v) < 1 && v !== 0 ? 4 : 2); }

function MetTenants({ m }) {
  const rows = m.tenants || [];
  if (!rows.length) return null;
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Организации: страницы, деньги, себестоимость")),
    React.createElement("p", { className: "dim", style: { fontSize: 12, margin: "0 0 8px" } },
      TR("Себестоимость страницы — расход на модели за всю жизнь файлов, делённый на списанные страницы. Это единственное число, по которому видно работу в убыток.")),
    React.createElement("div", { style: { overflowX: "auto" } },
      React.createElement("table", { className: "tbl" },
        React.createElement("thead", null, React.createElement("tr", null,
          [TR("Организация"), TR("Страниц"), TR("Остаток"), TR("Расход"), TR("Себест./стр."),
           TR("Цена/стр."), TR("Остаётся"), TR("Смета/факт"), TR("Простой")]
            .map((h, i) => React.createElement("th", { key: i }, h)))),
        React.createElement("tbody", null, rows.map(t => React.createElement("tr", { key: t.id },
          React.createElement("td", null, t.name,
            t.active === false ? React.createElement("span", { className: "dim" }, TR(" · отключена")) : null),
          React.createElement("td", null, t.pages),
          React.createElement("td", { className: t.pagesLeft != null && t.pagesLeft <= 0 ? "bad" : "" },
            t.pagesLeft == null ? "—" : t.pagesLeft),
          React.createElement("td", null, metUsd(t.spendUsd)),
          React.createElement("td", null, metUsd(t.costPerPage)),
          React.createElement("td", { className: "dim" },
            t.pricePerPage == null ? TR("не задана") : t.pricePerPage + " " + (t.currency || "")),
          React.createElement("td", { className: t.margin != null && t.margin < 0.5 ? "bad" : "" },
            t.margin == null ? "—" : Math.round(t.margin * 100) + "%"),
          React.createElement("td", { className: "dim" },
            t.estRatio == null ? "—" : "×" + t.estRatio),
          React.createElement("td", { className: "dim" },
            t.idleDays == null ? TR("не запускали") : t.idleDays + TR(" дн."))))))));
}

function MetSteps({ m }) {
  const rows = m.steps || [];
  if (!rows.length) return null;
  const top = rows[0].usd || 0;
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Расход по шагам за период · всего ") + metUsd(m.spendUsd)),
    React.createElement("div", { style: { overflowX: "auto" } },
      React.createElement("table", { className: "tbl" },
        React.createElement("tbody", null, rows.map(r => React.createElement("tr", { key: r.step },
          React.createElement("td", null, r.step),
          React.createElement("td", { style: { width: "45%" } },
            React.createElement("div", { className: "met-bar" },
              React.createElement("i", { style: { width: (top ? Math.round(r.usd / top * 100) : 0) + "%" } }))),
          React.createElement("td", null, metUsd(r.usd)),
          React.createElement("td", { className: "dim" }, r.calls + TR(" выз."))))))));
}

function MetCaps({ m }) {
  const rows = (m.capCodes || []).concat(m.waste || [], m.provider || []);
  if (!rows.length) return null;
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Во что упирались и что сгорело")),
    React.createElement("div", { style: { overflowX: "auto" } },
      React.createElement("table", { className: "tbl" },
        React.createElement("tbody", null, rows.map((r, i) => React.createElement("tr", { key: i },
          React.createElement("td", null, r.code),
          React.createElement("td", null, r.n)))))));
}

function MetTech({ m }) {
  return React.createElement("details", { className: "card card-pad" },
    React.createElement("summary", null, TR("Технические подробности: маршруты, скорость, ошибки")),
    React.createElement("div", { className: "col", style: { gap: 12, marginTop: 10 } },
      React.createElement("div", null,
        React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("Чаще всего зовут")),
        React.createElement("div", { style: { overflowX: "auto" } },
          React.createElement("table", { className: "tbl" },
            React.createElement("tbody", null, (m.routes || []).map((r, i) => React.createElement("tr", { key: i },
              React.createElement("td", null, r.route),
              React.createElement("td", null, r.n),
              React.createElement("td", { className: "dim" }, r.avgMs + TR(" мс в среднем")),
              React.createElement("td", { className: "dim" }, r.msMax + TR(" мс худший")))))))),
      React.createElement("div", null,
        React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("Самые медленные")),
        React.createElement("div", { style: { overflowX: "auto" } },
          React.createElement("table", { className: "tbl" },
            React.createElement("tbody", null, (m.slow || []).map((r, i) => React.createElement("tr", { key: i },
              React.createElement("td", null, r.route),
              React.createElement("td", null, r.avgMs + TR(" мс")),
              React.createElement("td", { className: "dim" }, r.slow + TR(" раз дольше секунды")))))))),
      React.createElement("div", null,
        React.createElement("div", { className: "eyebrow", style: { margin: "0 0 6px" } }, TR("Отказы")),
        (m.errors || []).length === 0
          ? React.createElement("p", { className: "dim", style: { margin: 0 } }, TR("Отказов не было."))
          : React.createElement("div", { style: { overflowX: "auto" } },
            React.createElement("table", { className: "tbl" },
              React.createElement("tbody", null, (m.errors || []).map((r, i) => React.createElement("tr", { key: i },
                React.createElement("td", null, r.code),
                React.createElement("td", null, r.n)))))))));
}

function MetDigest({ days, toast }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => window.API.safeCall(() => window.API.adminDigest(days))
    .then(r => { if (r && r.ok) setText(r.text); });
  const send = () => {
    setBusy(true);
    window.API.adminDigestSend(days)
      .then(() => toast(TR("Сводка отправлена в Telegram")))
      .catch(e => toast(e.message, "err"))
      .finally(() => setBusy(false));
  };
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Сводка словами — себе в Telegram или своему ИИ-агенту")),
    React.createElement("p", { className: "dim", style: { fontSize: 12, margin: "0 0 8px" } },
      TR("Тот же разбор, но текстом: его можно читать по утрам и скармливать агенту, который ищет в нём возможности.")),
    React.createElement("div", { className: "row", style: { gap: 8, marginBottom: 8 } },
      React.createElement("button", { className: "btn", onClick: load }, TR("Показать текстом")),
      React.createElement("button", { className: "btn", disabled: busy, onClick: send }, TR("Прислать в Telegram"))),
    text ? React.createElement("pre", { className: "met-pre" }, text) : null);
}

function TabMetrics({ toast }) {
  const [days, setDays] = useState(7);
  const [m, setM] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = (d) => {
    setBusy(true);
    window.API.safeCall(() => window.API.adminMetrics(d))
      .then(r => { if (r && r.ok) setM(r); })
      .finally(() => setBusy(false));
  };
  useEffect(() => { load(days); }, [days]);
  return React.createElement("div", { className: "col", style: { gap: 16 } },
    React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
      React.createElement("div", { className: "seg", role: "tablist" },
        MET_DAYS.map(d => React.createElement("button", {
          key: d, role: "tab", "aria-pressed": days === d, "aria-selected": days === d,
          onClick: () => setDays(d),
        }, d + TR(" дн.")))),
      React.createElement("button", { className: "btn", disabled: busy, onClick: () => load(days) },
        TR("Обновить")),
      m ? React.createElement("span", { className: "dim", style: { alignSelf: "center", fontSize: 12 } },
        m.from + " — " + m.to) : null),
    !m && React.createElement("div", { className: "dim" }, TR("Считаем…")),
    m && React.createElement(MetHints, { m }),
    m && React.createElement(MetTenants, { m }),
    m && React.createElement(MetSteps, { m }),
    m && React.createElement(MetCaps, { m }),
    m && React.createElement(MetDigest, { days, toast }),
    m && React.createElement(MetTech, { m }));
}

/* ---------- Вкладка «Возможности» ----------
   Отвечает на вопрос «где сервис упирается в себя»: во что упёрлись люди,
   чего у нас нет вовсе, докуда они доходят и какие отказы дают четыре пятых
   всех отказов. Отдельно от «Метрик» потому, что вопрос другой: там —
   «что происходит», здесь — «что построить и кому продать».

   Три решения, которые легко потерять молча:
   1) числа и КОДЫ считает сервер, фразу собирает браузер (инвариант 17).
      Забытая строка в `oppBlockText` выводит на экран сам код — сторожит
      tests/test_admin_render.js;
   2) живое обновление ходит в ЛЁГКУЮ дверь (`live=1`): тяжёлая обходит
      организации и проекты, а воркер у нас один — опрашивать её каждые
      15 секунд значило бы держать сервис ради экрана;
   3) денежные подсказки по организациям приходят только с полного ответа,
      и живое обновление их НЕ СТИРАЕТ: пропавшая с экрана строка
      неотличима от решённой задачи. */
const OPP_LIVE_MS = 15000;

/* Тупик словами. Ключ словаря — сама русская строка, поэтому число в неё
   не входит: оно рисуется отдельным элементом. */
function oppBlockText(code) {
  switch (code) {
    case "cap.filePages413": return TR("раз файл не взяли: он толще потолка страниц. Это спрос на большие документы — потолок поднимается платно");
    case "cap.bytes413": return TR("раз файл не взяли: он тяжелее потолка в мегабайтах");
    case "cap.pages402": return TR("раз кончились выданные страницы — пора предлагать пакет");
    case "cap.projects402": return TR("раз упёрлись в потолок числа проектов");
    case "cap.spend402": return TR("раз исчерпан месячный лимит расхода");
    case "cap.format415": return TR("раз принесли формат, которого мы не читаем — это список, какой импорт писать следующим");
    case "cap.noReader503": return TR("раз формат мы знаем, а библиотеки на сервере нет — чинится установкой");
    case "cap.duplicate409": return TR("раз несли тот же файл второй раз: человек не нашёл свой же готовый проект");
    case "dead.exportFormat": return TR("раз просили формат выгрузки, которого у нас нет");
    case "dead.writeback": return TR("раз просили «как в оригинале», а формат этого не умеет — отдали Word");
    case "dead.pdfLayout503": return TR("раз PDF «как в оригинале» не собрался: нет шрифта или библиотеки на сервере");
    case "dead.slotsDrift400": return TR("раз выгрузка 1в1 отказала: правила разбора файла изменились с момента загрузки");
    case "dead.images": return TR("раз чтение надписей с картинок не запустилось");
    case "dead.scan": return TR("раз принесли скан: объём мы считаем выборкой, а не целиком");
    case "dead.retranslateOne": return TR("строк не дали перевести заново: предел организации");
    case "dead.retranslateBulk": return TR("раз файл не дали перевести заново целиком: квота");
    case "dead.sourceGrow409": return TR("раз правка оригинала выросла больше потолка");
    case "dead.budget402": return TR("раз прогон не пустили: потолок расхода на страницу файла");
    default: return code;
  }
}

/* Что человек ДЕЛАЛ и ПОЧЕМУ не вышло — две закрытые таблицы, а не разбор
   маршрута в браузере: маршрут приходит с сервера строкой и переводу
   не подлежит, а «нёс файл» переводится и читается человеком. */
function oppActText(act) {
  switch (act) {
    case "upload": return TR("нёс файл");
    case "reimport": return TR("менял или пересобирал файл");
    case "export": return TR("забирал перевод");
    case "run": return TR("запускал прогон");
    case "quote": return TR("считал смету");
    case "glossary": return TR("правил словарь");
    case "terms": return TR("решал по терминам");
    case "tm": return TR("смотрел память переводов");
    case "images": return TR("читал надписи с картинок");
    case "segment": return TR("правил строку");
    case "project": return TR("открывал проект или папку");
    case "auth": return TR("входил");
    case "team": return TR("работал с командой");
    case "profile": return TR("менял свой профиль");
    case "admin": return TR("смотрел админку");
    default: return TR("прочее");
  }
}

function oppWhyText(status) {
  switch (status) {
    case 400: return TR("мы не поняли запрос");
    case 401: return TR("вход просрочен");
    case 402: return TR("кончились деньги или страницы");
    case 403: return TR("не хватило прав");
    case 404: return TR("не нашли — или это чужое");
    case 409: return TR("занято: такое уже есть либо идёт прогон");
    case 413: return TR("файл больше потолка");
    case 415: return TR("формат мы не читаем");
    case 422: return TR("запрос не сошёлся с формой — это наша ошибка");
    case 429: return TR("просили слишком часто");
    case 500: return TR("сломались мы");
    case 503: return TR("нечем сделать: нет библиотеки или ключа");
    default: return TR("отказ");
  }
}

function oppPct(v) { return Math.round((v || 0) * 100) + "%"; }

function OppBar({ share, vital }) {
  return React.createElement("div", { className: "met-bar" },
    React.createElement("i", {
      style: { width: Math.max(2, Math.round((share || 0) * 100)) + "%",
               opacity: vital ? 1 : 0.45 },
    }));
}

/* Список с Парето: число, полоса доли, фраза и накопленная доля. Строки
   ниже порога отделены чертой и приглушены — разница между «браться
   сейчас» и «браться последним» должна быть видна без чтения чисел. */
function OppRows({ rows, text, kind }) {
  let cut = false;
  return React.createElement("div", { className: "col", style: { gap: 8 } },
    rows.map((r, i) => {
      const tail = !r.vital;
      const first = tail && !cut;
      if (tail) cut = true;
      return React.createElement("div", { key: i, className: "col", style: { gap: 6 } },
        first ? React.createElement("div", { className: "opp-cut dim", style: { fontSize: 12 } },
          TR("Ниже — хвост: мелочи, за которые браться последними")) : null,
        React.createElement("div", { className: "opp-row" + (tail ? " tail" : "") },
          React.createElement("b", { className: "met-num " + (MET_KIND[kind(r)] || "bad") }, r.n),
          React.createElement(OppBar, { share: r.share, vital: r.vital }),
          React.createElement("span", null, text(r),
            React.createElement("span", { className: "dim" },
              " · " + oppPct(r.share) + TR(" от всех") + " · " + TR("накопл. ") + oppPct(r.cum)))));
    }));
}

function OppBlocked({ d }) {
  const rows = d.blocked || [];
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Тупики: во что упёрлись и чего у нас нет")),
    React.createElement("p", { className: "dim", style: { fontSize: 12, margin: "0 0 10px" } },
      TR("Верхние строки до 80% — та самая работа, которая закроет четыре пятых всех отказов. Зелёные можно продать, красные надо чинить.")),
    rows.length === 0
      ? React.createElement("p", { className: "dim", style: { margin: 0 } },
        TR("За период никто ни во что не упёрся. Это ответ, а не пустой экран."))
      : React.createElement(OppRows, {
        rows, kind: r => r.kind,
        text: r => React.createElement("span", null, oppBlockText(r.code),
          (r.items || []).length ? React.createElement("span", { className: "dim" },
            " — " + r.items.map(i => i.name + "×" + i.n).join(", ")) : null,
          (r.who || []).length ? React.createElement("span", { className: "dim" },
            " · " + TR("кто: ") + r.who.map(w => w.tenant + " (" + w.n + ")").join(", ")) : null),
      }));
}

function OppErrors({ d }) {
  const rows = d.errors || [];
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Отказы понятными словами")),
    rows.length === 0
      ? React.createElement("p", { className: "dim", style: { margin: 0 } },
        TR("Отказов за период не было."))
      : React.createElement(OppRows, {
        rows, kind: r => (r.status >= 500 ? "fix" : r.status === 402 || r.status === 413 ? "money" : "loss"),
        text: r => React.createElement("span", null,
          oppActText(r.act) + " — " + oppWhyText(r.status),
          React.createElement("span", { className: "dim" }, " · " + r.status + " " + r.route)),
      }));
}

function OppFunnel({ d }) {
  const f = d.funnel || {};
  const steps = f.steps || [];
  const label = { upload: TR("принесли файл"), run: TR("запустили прогон"),
                  export: TR("забрали перевод") };
  if (!steps.some(s => s.n)) return null;
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
      TR("Докуда доходят")),
    React.createElement("div", { className: "opp-steps" },
      steps.map((s, i) => React.createElement(React.Fragment, { key: s.code },
        i ? React.createElement("span", { className: "dim" }, "→") : null,
        React.createElement("div", { className: "opp-step" },
          React.createElement("b", null, s.n),
          React.createElement("span", { className: "dim" }, label[s.code] || s.code)))),
      f.conv != null ? React.createElement("span", { className: "dim", style: { marginLeft: 6 } },
        TR("доходит до выгрузки ") + oppPct(f.conv)) : null),
    React.createElement("p", { className: "dim", style: { fontSize: 12, margin: "10px 0 0" } },
      TR("Это не когорта: считаются события периода, а не путь одного человека — файл могли принести вчера, а выгрузить сегодня. Вопрос, на который она отвечает: сколько принесённых файлов так и не дошли до выгрузки.")),
    // Отток — отдельным числом, а не шагом воронки: «принесли 40, унесли 38»
    // это не два дошедших, а разбор сорока файлов, который мы оплатили
    // и выбросили. Внутри `steps` он испортил бы долю дошедших.
    f.deleted ? React.createElement("p", { style: { margin: "8px 0 0", fontSize: 13 } },
      TR("Принесли и удалили: ") + f.deleted +
      TR(" — разбор этих файлов мы уже оплатили")) : null,
    (f.byExt || []).length ? React.createElement("p", { style: { margin: "8px 0 0", fontSize: 13 } },
      TR("Что нам несут: ") + f.byExt.map(x => x.name + "×" + x.n).join(", ")) : null,
    (f.byKind || []).length ? React.createElement("p", { style: { margin: "4px 0 0", fontSize: 13 } },
      TR("За какой работой приходят: ") + f.byKind.map(x => x.name + "×" + x.n).join(", ")) : null);
}

/* Деньги по организациям и сожжённая работа рисуются той же карточкой
   подсказки, что и на «Метриках» (`MetHint`): два вида одной строки
   разошлись бы первой же правкой. */
function OppMoney({ d }) {
  const money = d.money || [];
  const burnt = (d.waste || []).map(w => ({ kind: "loss", code: "waste:" + w.code, n: w.n }))
    .concat((d.provider || []).map(p => ({ kind: "fix", code: "provider:" + p.code, n: p.n })));
  if (!money.length && !burnt.length) return null;
  return React.createElement("div", { className: "col", style: { gap: 12 } },
    money.length ? React.createElement("div", { className: "card card-pad" },
      React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
        TR("Деньги по организациям")),
      React.createElement("ul", { className: "met-list" },
        money.map((h, i) => React.createElement(MetHint, { key: i, h })))) : null,
    burnt.length ? React.createElement("div", { className: "card card-pad" },
      React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } },
        TR("Сожжено: за это заплачено, а работы нет")),
      React.createElement("ul", { className: "met-list" },
        burnt.map((h, i) => React.createElement(MetHint, { key: i, h })))) : null);
}

function TabChances({ toast }) {
  const [days, setDays] = useState(7);
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(true);
  const load = (dd, live) => {
    if (!live) setBusy(true);
    return window.API.safeCall(() => window.API.adminChances(dd, live))
      .then(r => {
        if (!r || !r.ok) return;
        // Лёгкий ответ денежных подсказок не несёт — оставляем прежние,
        // иначе живое обновление стирало бы их каждые 15 секунд.
        setD(prev => (r.money == null && prev && prev.money
          ? Object.assign({}, r, { money: prev.money }) : r));
      })
      .finally(() => { if (!live) setBusy(false); });
  };
  useEffect(() => { load(days, 0); }, [days]);
  useEffect(() => {
    if (!auto) return;
    let dead = false;
    const h = setInterval(() => {
      // Вкладка в фоне — не будим единственный воркер ради экрана,
      // которого никто не смотрит.
      if (!dead && !(window.document && window.document.hidden)) load(days, 1);
    }, OPP_LIVE_MS);
    return () => { dead = true; clearInterval(h); };
  }, [auto, days]);
  return React.createElement("div", { className: "col", style: { gap: 16 } },
    React.createElement("div", { className: "row row-wrap", style: { gap: 8 } },
      React.createElement("div", { className: "seg", role: "tablist" },
        MET_DAYS.map(x => React.createElement("button", {
          key: x, role: "tab", "aria-pressed": days === x, "aria-selected": days === x,
          onClick: () => setDays(x),
        }, x + TR(" дн.")))),
      React.createElement("button", { className: "btn", disabled: busy, onClick: () => load(days, 0) },
        TR("Обновить")),
      React.createElement("label", { className: "row", style: { gap: 6, alignSelf: "center", fontSize: 13 } },
        React.createElement("input", { type: "checkbox", checked: auto,
          onChange: e => setAuto(e.target.checked) }),
        TR("Живое обновление")),
      d ? React.createElement("span", { className: "dim", style: { alignSelf: "center", fontSize: 12 } },
        d.from + " — " + d.to + TR(" · обновлено ") + d.at) : null),
    !d && React.createElement("div", { className: "dim" }, TR("Считаем…")),
    d && React.createElement(OppFunnel, { d }),
    d && React.createElement(OppBlocked, { d }),
    d && React.createElement(OppMoney, { d }),
    d && React.createElement(OppErrors, { d }));
}

function TabAdmin({ store, toast }) {
  const [ov, setOv] = useState(null);
  const [nonce, setNonce] = useState(0);
  // Третьим хуком, после сводки: рендер-тест подкладывает сводку в hooks[0].
  const [view, setView] = useState("summary");
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
      React.createElement("p", { className: "lead" }, view === "models"
        ? TR("Модели шагов на всю систему и пересчёт расхода по журналу токенов.")
        : view === "chances"
          ? TR("Куда люди упираются, чего им не хватило и что из этого можно продать. Считается по журналу событий; вызовов модели нет.")
          : view === "metrics"
            ? TR("Где теряются деньги, где их можно заработать и что чинить. Считается по журналу событий, расходу и сметам; вызовов модели нет.")
          : TR("Все организации, аккаунты, прогоны и расход. Обновляется каждые 10 секунд."))),
    React.createElement("div", { className: "row", style: { gap: 8, marginBottom: 16 } },
      React.createElement("div", { className: "seg", role: "tablist" },
        [["summary", TR("Сводка")], ["chances", TR("Возможности")], ["metrics", TR("Метрики")],
         ["models", TR("Модели и расход")]].map(([key, label]) =>
          React.createElement("button", { key, role: "tab", "aria-pressed": view === key, "aria-selected": view === key,
            onClick: () => setView(key) }, label)))),
    view === "models" && React.createElement(AdminModelsView, { toast, tenants: ov ? ov.tenants : [] }),
    view === "chances" && React.createElement(TabChances, { toast }),
    view === "metrics" && React.createElement(TabMetrics, { toast }),
    view === "summary" && !ov && React.createElement("div", { className: "dim" }, TR("Загружаем сводку…")),
    view === "summary" && ov && React.createElement("div", { className: "col", style: { gap: 16 } },
      React.createElement("div", { className: "row row-wrap", style: { gap: 10 } },
        React.createElement(AdminStat, { label: TR("Организаций"), value: ov.tenants.length }),
        React.createElement(AdminStat, { label: TR("Аккаунтов"), value: ov.tenants.reduce((a, t) => a + t.users, 0) }),
        React.createElement(AdminStat, { label: TR("Проектов / сегментов"), value: ov.tenants.reduce((a, t) => a + t.projects, 0) + " / " + ov.tenants.reduce((a, t) => a + t.segments, 0) }),
        React.createElement(AdminStat, { label: TR("Расход процесса с запуска"), value: "$" + Number(pr.usage.cost || 0).toFixed(2) + " · " + pr.usage.calls + TR(" выз."), warn: pr.usage.unpriced > 0 }),
        React.createElement(AdminStat, { label: TR("Аптайм"), value: fmtDur(pr.uptimeSec) }),
        React.createElement(AdminStat, { label: "state.json", value: fmtBytes(pr.stateBytes) }),
        React.createElement(AdminStat, { label: TR("Сессий"), value: pr.sessions }),
        React.createElement(AdminStat, { label: TR("Ключ OpenAI"), value: pr.openaiKey ? TR("есть") : TR("НЕТ"), warn: !pr.openaiKey }),
        /* Второй поставщик необязателен: без ключа Anthropic просто недоступны
           модели Claude, поэтому «нет» здесь не тревога. */
        React.createElement(AdminStat, { label: TR("Ключ Anthropic"), value: pr.anthropicKey ? TR("есть") : TR("нет") }),
        React.createElement(AdminStat, { label: TR("Очередь терминов"), value: pr.termQueue })),
      React.createElement(AdminJobs, { ov, toast, onChange: reload }),
      React.createElement(AdminTenants, { ov, toast, onChange: reload }),
      React.createElement(AdminUsers, { toast, tenants: ov.tenants }),
      React.createElement(AdminReferral, { toast }),
      React.createElement(AdminTesting, { toast }),
      React.createElement(AdminRuns, null),
      React.createElement(AdminLogins, null),
      React.createElement(AdminAudit, null)));
}
