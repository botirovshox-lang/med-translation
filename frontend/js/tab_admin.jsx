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
    React.createElement("div", { style: { fontSize: 20, fontWeight: 600, color: warn ? "var(--c-danger)" : undefined } }, value));
}

function AdminTenants({ ov, toast, onChange }) {
  const setLimit = async (t) => {
    const v = prompt(TR("Месячный лимит для «") + t.name + TR("», $ (пусто — снять):"), t.limitUsd != null ? t.limitUsd : "");
    if (v === null) return;
    try { await window.API.tenantUpdate(t.id, v.trim() === "" ? { clearLimit: true } : { limitUsd: Number(v) }); toast.success(TR("Лимит обновлён"), t.name); onChange(); }
    catch (e) { toast.error(TR("Не обновлён"), e.message || String(e)); }
  };
  const toggle = async (t) => {
    try { await window.API.tenantUpdate(t.id, { active: !t.active }); toast.success(t.active ? TR("Отключена") : TR("Включена"), t.name); onChange(); }
    catch (e) { toast.error(TR("Не удалось"), e.message || String(e)); }
  };
  const del = async (t) => {
    if (!confirm(TR("Удалить организацию «") + t.name + TR("» вместе с её пользователями?\nПроекты должны быть удалены заранее."))) return;
    try { const r = await window.API.tenantDelete(t.id); toast.success(TR("Организация удалена"), TR("пользователей: ") + r.usersRemoved); onChange(); }
    catch (e) { toast.error(TR("Не удалена"), e.message || String(e)); }
  };
  return React.createElement("div", { className: "card card-pad" },
    React.createElement("div", { className: "eyebrow", style: { margin: "0 0 8px" } }, TR("Организации · ") + ov.tenants.length),
    React.createElement("div", { style: { overflowX: "auto" } }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Организация"), TR("Люди"), TR("Проекты"), TR("Сегменты"), TR("Глоссарий"), TR("Расход за ") + ov.month, TR("Лимит"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, ov.tenants.map(t => React.createElement("tr", { key: t.id, style: t.active === false ? { opacity: .55 } : null },
        React.createElement("td", null, React.createElement("b", null, t.name), " ", React.createElement("span", { className: "dim" }, t.id + (t.active === false ? TR(" · отключена") : ""))),
        React.createElement("td", null, t.activeUsers + (t.users !== t.activeUsers ? " / " + t.users : "")),
        React.createElement("td", null, t.projects),
        React.createElement("td", null, t.segments),
        React.createElement("td", null, t.glossary + (t.domains ? TR(" · обл. ") + t.domains : "")),
        React.createElement("td", { style: { color: t.spend.over ? "var(--c-danger)" : undefined } },
          "$" + Number(t.spend.spentUsd).toFixed(2) + " · " + t.spend.calls + TR(" выз.") + (t.spend.unpriced ? TR(" · без цены ") + t.spend.unpriced : "")),
        React.createElement("td", null, t.limitUsd != null ? "$" + Number(t.limitUsd).toFixed(2) : "—"),
        React.createElement("td", { style: { whiteSpace: "nowrap", textAlign: "right" } },
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setLimit(t) }, TR("Лимит")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => toggle(t) }, t.active === false ? TR("Включить") : TR("Отключить")),
          React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => del(t) }, TR("Удалить")))))))));
}

function AdminUsers({ toast }) {
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
      React.createElement(Input, { value: q, placeholder: TR("поиск: логин, имя, организация"), style: { maxWidth: 280 }, onChange: (e) => setQ(e.target.value) })),
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
      React.createElement(AdminUsers, { toast }),
      React.createElement(AdminAudit, null)));
}
