/* ============================================================
   Вкладка «Профиль» — своя, а не владельческая.

   Заведена потому, что у переводчика до сих пор не было НИ ОДНОГО экрана
   про себя: язык интерфейса, имя и пароль правились только через
   `/api/admin/users`, куда ему хода нет (403). То есть человек не мог
   поменять даже язык, на котором с ним разговаривают.

   Здесь же живут КОМАНДЫ. Команда — это рабочее пространство (арендатор):
   свои проекты, свой глоссарий, своя память переводов, свой расход. Поэтому
   переключение команды — запрос к серверу (`/api/profile/team`), а не
   флажок в браузере: меняется ВСЁ, что человек видит, и решает это сервер.

   И приглашения. Решение принимает САМ приглашённый — здесь, а не по ссылке
   из письма: ссылка была бы вторым входом мимо пароля. Письмо только
   говорит, что приглашение пришло.
   ============================================================ */

/* Имя с префиксом экрана: сборки нет, .jsx живут в ОДНОЙ глобальной области,
   и функция верхнего уровня из позднего файла молча затирает одноимённую
   из раннего (так «SegRow» редактора уже был затёрт). */
function ProfileCard({ title, icon, children, right, bare }) {
  /* bare — раздел ВНУТРИ другой карточки (блок команды): рамка в рамке —
     лишний слой, который глаз должен разобрать. */
  if (bare) return React.createElement("div", { className: "pf-sub" },
    React.createElement("div", { className: "row between", style: { alignItems: "center", gap: 8 } },
      React.createElement("h3", { className: "pf-sub-title" }, title), right || null),
    children);
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 14 } },
    React.createElement("div", { className: "row between", style: { alignItems: "center" } },
      React.createElement("div", { className: "eyebrow", style: { margin: 0, display: "flex", alignItems: "center", gap: 8 } },
        icon && React.createElement(Icon, { name: icon, size: 16 }), title),
      right || null),
    children);
}

/* ---------- Кто я, язык, тема ---------- */
function ProfileIdentity({ data, onSaved, toast, theme, onToggleTheme }) {
  const me = data.me || {};
  const [name, setName] = useState(me.name || "");
  const [busy, setBusy] = useState(false);
  const langs = (window.I18N && window.I18N.langs) || [];

  const saveName = async () => {
    setBusy(true);
    try {
      const r = await window.API.profileSave({ name });
      onSaved(r && r.me);
      toast.success(TR("Сохранено"), TR("Имя обновлено."));
    } catch (e) { toast.error(TR("Не сохранено"), e.message || String(e)); }
    setBusy(false);
  };

  /* Язык пишется НА СЕРВЕР и в localStorage, и оба нужны: сервер — источник
     правды (язык переезжает на другой компьютер), localStorage — кэш, без
     которого экран ВХОДА мигал бы чужим языком (до входа спросить некого).
     Дальше страница перезагружается: часть надписей — константы верхнего
     уровня, они вычисляются один раз при загрузке файла. */
  const setLang = async (code) => {
    if (code === (window.I18N && window.I18N.lang)) return;
    try { await window.API.profileSave({ uiLang: code }); }
    catch (e) { toast.error(TR("Язык не сохранён на сервере"), e.message || String(e)); }
    window.I18N.setLang(code);
  };

  return React.createElement(ProfileCard, { title: TR("Учётная запись"), icon: "user" },
    React.createElement("div", { className: "row", style: { gap: 14, alignItems: "center" } },
      React.createElement(Avatar, { person: me, size: 48 }),
      React.createElement("div", { style: { minWidth: 0 } },
        React.createElement("div", { style: { fontWeight: 600, fontSize: 17 } }, me.name || me.login),
        React.createElement("div", { className: "dim", style: { fontSize: 14 } },
          TR("Логин: ") + (me.login || "—") + " · " + (me.email || TR("почта не указана")),
          me.email && !me.emailVerified ? " · " + TR("не подтверждена") : ""))),
    React.createElement("div", { className: "pf-grid" },
      React.createElement("div", { className: "col", style: { gap: 8 } },
        React.createElement("div", { className: "pf-label" }, TR("Как вас называть")),
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement(Input, { value: name, onChange: (e) => setName(e.target.value), style: { flex: 1, minWidth: 0 } }),
          React.createElement(Btn, { variant: "secondary", disabled: busy || !name.trim() || name === me.name, onClick: saveName },
            TR("Сохранить")))),
      React.createElement("div", { className: "col", style: { gap: 8 } },
        React.createElement("div", { className: "pf-label" }, TR("Язык интерфейса")),
        /* Выбор языка — переключатель .seg: он говорит «на каком языке
           с вами сейчас разговаривают», а не «нажмите сюда». После смены
           страница перезагружается (часть надписей собирается один раз). */
        React.createElement("div", { className: "seg" },
          langs.map(l => React.createElement("button", {
            key: l.code, "aria-pressed": (window.I18N && window.I18N.lang) === l.code,
            onClick: () => setLang(l.code),
          }, l.native))),
        React.createElement("div", { className: "row", style: { gap: 10, alignItems: "center", marginTop: 4 } },
          React.createElement(Switch, { on: theme === "dark", onClick: onToggleTheme, label: TR("Тёмная тема") }),
          React.createElement("span", { style: { fontSize: 14 } }, TR("Тёмная тема"))))));
}

/* ---------- Пароль ---------- */
function ProfilePassword({ toast }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const mismatch = next && again && next !== again;
  const save = async () => {
    setBusy(true);
    try {
      await window.API.profileSave({ password: next, currentPassword: cur });
      setCur(""); setNext(""); setAgain(""); setOpen(false);
      toast.success(TR("Пароль сменён"), TR("Остальные ваши сессии закрыты."));
    } catch (e) { toast.error(TR("Пароль не сменён"), e.message || String(e)); }
    setBusy(false);
  };
  /* Свёрнут за кнопкой: пароль меняют редко, а три пустых поля посреди
     профиля читаются как «заполните меня». Хук последним. */
  const [open, setOpen] = useState(false);
  if (!open) return React.createElement("div", { className: "card card-pad pf-row" },
    React.createElement(Icon, { name: "lock", size: 18, style: { color: "var(--text-3)" } }),
    React.createElement("div", { style: { flex: 1, fontWeight: 600 } }, TR("Пароль")),
    React.createElement(Btn, { variant: "secondary", onClick: () => setOpen(true) }, TR("Сменить пароль")));
  return React.createElement(ProfileCard, { title: TR("Пароль"), icon: "lock",
      right: React.createElement(Btn, { variant: "ghost", size: "sm", onClick: () => setOpen(false) }, TR("Отмена")) },
    React.createElement("div", { className: "grid grid-3", style: { gap: 10 } },
      React.createElement(Field, { label: TR("Нынешний пароль") },
        React.createElement(Input, { type: "password", value: cur, onChange: (e) => setCur(e.target.value) })),
      React.createElement(Field, { label: TR("Новый пароль (от 8 символов)") },
        React.createElement(Input, { type: "password", value: next, onChange: (e) => setNext(e.target.value) })),
      React.createElement(Field, { label: TR("Ещё раз"), hint: mismatch ? TR("Не совпадает") : "" },
        React.createElement(Input, { type: "password", value: again, onChange: (e) => setAgain(e.target.value) }))),
    React.createElement("div", null,
      React.createElement(Btn, { variant: "primary", icon: "lock",
        disabled: busy || !cur || next.length < 8 || mismatch, onClick: save }, TR("Сменить пароль"))),
    React.createElement("p", { className: "dim", style: { fontSize: 12, margin: 0 } },
      TR("Нынешний пароль спрашивается не для порядка: без него украденный токен означал бы украденную учётную запись навсегда.")));
}

/* ---------- Приглашения ---------- */
function ProfileInvites({ data, onChange, toast }) {
  const invites = data.invites || [];
  const [busy, setBusy] = useState("");
  if (!invites.length) return null;
  const decide = async (inv, action) => {
    setBusy(inv.id);
    try {
      await window.API.inviteDecide(inv.id, action);
      toast.success(action === "accept" ? TR("Приглашение принято") : TR("Приглашение отклонено"), inv.teamName);
      await onChange();
    } catch (e) { toast.error(TR("Не удалось"), e.message || String(e)); }
    setBusy("");
  };
  return React.createElement(ProfileCard, { title: TR("Приглашения в команды"), icon: "message" },
    invites.map(inv => React.createElement("div", { key: inv.id, className: "card", style: { padding: "12px 14px" } },
      React.createElement("div", { style: { fontWeight: 600 } }, inv.teamName),
      React.createElement("div", { className: "dim", style: { fontSize: 13, marginTop: 2 } },
        (inv.by ? TR("Пригласил: ") + inv.by + " · " : "")
        + TR("роль: ") + roleLabel(inv.role)
        + (inv.at ? " · " + inv.at : "")),
      React.createElement("div", { className: "row", style: { gap: 8, marginTop: 10 } },
        React.createElement(Btn, { variant: "primary", size: "sm", icon: "check",
          disabled: busy === inv.id, onClick: () => decide(inv, "accept") }, TR("Принять")),
        React.createElement(Btn, { variant: "ghost", size: "sm",
          disabled: busy === inv.id, onClick: () => decide(inv, "decline") }, TR("Отклонить"))))),
    React.createElement("p", { className: "dim", style: { fontSize: 12, margin: 0 } },
      TR("Пока приглашение не принято, доступа к проектам команды у вас нет.")));
}

/* ---------- Мои команды ---------- */
function ProfileTeams({ data, onChange, toast, bare }) {
  const teams = data.teams || [];
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const active = data.activeTeam;

  const switchTo = async (t) => {
    if (t.id === active) return;
    setBusy(true);
    try {
      await window.API.teamSwitch(t.id);
      /* Перезагрузка, а не перерисовка: сменилось рабочее пространство —
         проекты, глоссарий, память переводов и расход другие. Оставить
         на экране прежние данные значило бы показать чужую команду
         под именем новой. */
      window.location.reload();
    } catch (e) { toast.error(TR("Не удалось переключиться"), e.message || String(e)); setBusy(false); }
  };
  const create = async () => {
    setBusy(true);
    try {
      await window.API.teamCreate(name.trim());
      toast.success(TR("Команда создана"), name.trim());
      setName("");
      await onChange();
    } catch (e) { toast.error(TR("Команда не создана"), e.message || String(e)); }
    setBusy(false);
  };
  const leave = async (t) => {
    if (!window.confirm(TR("Выйти из команды «") + t.name + TR("»? Её проекты станут недоступны."))) return;
    setBusy(true);
    try {
      await window.API.teamLeave(t.id);
      toast.success(TR("Вы вышли из команды"), t.name);
      await onChange();
    } catch (e) { toast.error(TR("Не удалось выйти"), e.message || String(e)); }
    setBusy(false);
  };

  return React.createElement(ProfileCard, { title: TR("Мои команды"), icon: "folder", bare },
    React.createElement("div", { className: "tbl-fit" }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Команда"), TR("Моя роль"), TR("Участников"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, teams.map(t => React.createElement("tr", { key: t.id },
        React.createElement("td", null,
          React.createElement("span", { style: { fontWeight: t.id === active ? 600 : 400 } }, t.name),
          t.id === active && React.createElement("span", { className: "dim", style: { marginLeft: 8, fontSize: 12 } }, TR("· сейчас здесь")),
          t.home && React.createElement("span", { className: "dim", style: { marginLeft: 8, fontSize: 12 } }, TR("· домашняя"))),
        React.createElement("td", null, roleLabel(t.role)),
        React.createElement("td", null, t.members),
        React.createElement("td", { style: { whiteSpace: "nowrap" } },
          t.id !== active && React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy, onClick: () => switchTo(t) }, TR("Перейти")),
          !t.home && React.createElement(Btn, { variant: "ghost", size: "sm", disabled: busy, onClick: () => leave(t) }, TR("Выйти")))))))),

    React.createElement("div", { className: "eyebrow", style: { margin: "6px 0 0" } }, TR("Новая команда")),
    data.canCreateTeam
      ? React.createElement("div", { className: "row", style: { gap: 10, alignItems: "flex-end" } },
          React.createElement(Field, { label: TR("Название") },
            React.createElement(Input, { value: name, onChange: (e) => setName(e.target.value), placeholder: TR("например, «Клиника Шифо»") })),
          React.createElement(Btn, { variant: "primary", size: "sm", icon: "plus",
            disabled: busy || name.trim().length < 2, onClick: create }, TR("Создать")))
      : React.createElement("p", { className: "dim", style: { fontSize: 13, margin: 0 } },
          TR("Достигнут потолок команд на одного человека: ") + (data.teamLimit || "")),
    React.createElement("p", { className: "dim", style: { fontSize: 12, margin: 0 } },
      TR("У новой команды свой глоссарий, своя память переводов и свой лимит расхода — по умолчанию нулевой: платные прогоны включает администратор сервиса.")));
}

/* ---------- Состав активной команды (владельцу) ---------- */
function ProfileMembers({ data, toast, bare, hideHome }) {
  const tid = data.activeTeam;
  const [det, setDet] = useState(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("translator");
  const [busy, setBusy] = useState(false);
  const reload = () => window.API.safeCall(() => window.API.teamDetail(tid)).then(r => setDet(r || null));
  useEffect(() => { if (tid) reload(); }, [tid]);
  if (!det) return null;
  const owner = det.myRole === "owner";

  const invite = async () => {
    setBusy(true);
    try {
      const r = await window.API.teamInvite(tid, email.trim(), role);
      toast.success(TR("Приглашение отправлено"),
        r && r.mailSent ? TR("Письмо ушло; решение человек принимает в своём профиле.")
                        : TR("Письмо не ушло (почта на сервере не настроена) — приглашение всё равно ждёт в профиле человека."));
      setEmail("");
      reload();
    } catch (e) { toast.error(TR("Не приглашён"), e.message || String(e)); }
    setBusy(false);
  };
  const member = async (u, body, okMsg) => {
    try { await window.API.teamMember(tid, u.id, body); toast.success(okMsg, u.name || u.login); reload(); }
    catch (e) { toast.error(TR("Не удалось"), e.message || String(e)); }
  };

  /* hideHome: в ДОМАШНЕЙ команде людей с домашней записью показывает
     таблица входов (OrgUsers) — с паролем и отключением; здесь остаются
     приглашённые из других организаций. */
  const rows = hideHome ? det.members.filter(u => !u.home) : det.members;
  return React.createElement(ProfileCard, { title: hideHome ? TR("Пригласить по почте") : TR("Участники команды") + " · " + (det.team ? det.team.name : ""), icon: "user", bare },
    rows.length > 0 && React.createElement("div", { className: "tbl-fit" }, React.createElement("table", { className: "tbl" },
      React.createElement("thead", null, React.createElement("tr", null,
        [TR("Имя"), TR("Почта"), TR("Роль"), ""].map((h, i) => React.createElement("th", { key: i }, h)))),
      React.createElement("tbody", null, rows.map(u => React.createElement("tr", { key: u.id },
        React.createElement("td", null,
          React.createElement("span", { className: "row", style: { gap: 8, alignItems: "center" } },
            React.createElement(Avatar, { person: u, size: 24 }), u.name || u.login)),
        React.createElement("td", null, u.email || "—"),
        React.createElement("td", null, roleLabel(u.role)),
        React.createElement("td", { style: { whiteSpace: "nowrap" } },
          /* Домашнюю запись человека отсюда не правят: там своя дверь на
             экране «Организация», и правило одно — человек не должен
             остаться без рабочего пространства. */
          owner && !u.home && React.createElement(RoleSelect, { value: u.role,
            style: { width: 130, display: "inline-block", marginRight: 6 },
            onChange: (r) => r !== u.role && member(u, { role: r }, TR("Роль изменена")) }),
          owner && !u.home && React.createElement(Btn, { variant: "ghost", size: "sm",
            onClick: () => member(u, { remove: true }, TR("Исключён")) }, TR("Исключить")),
          u.home && React.createElement("span", { className: "dim", style: { fontSize: 12 } }, TR("домашняя запись")))))))),

    owner && !hideHome && React.createElement("div", { className: "eyebrow", style: { margin: "6px 0 0" } }, TR("Пригласить по почте")),
    owner && React.createElement("div", { className: "row", style: { gap: 10, alignItems: "flex-end", flexWrap: "wrap" } },
      React.createElement(Field, { label: TR("Почта участника") },
        React.createElement(Input, { value: email, onChange: (e) => setEmail(e.target.value), placeholder: "user@example.com" })),
      React.createElement(Field, { label: TR("Роль") },
        React.createElement(RoleSelect, { value: role, onChange: setRole })),
      React.createElement(Btn, { variant: "primary", size: "sm", icon: "send",
        disabled: busy || !email.trim(), onClick: invite }, TR("Пригласить"))),
    owner && React.createElement("p", { className: "dim", style: { fontSize: 12, margin: 0 } },
      TR("Приглашается уже зарегистрированный человек: учётную запись за него завести нельзя — пароль знает только он.")),

    owner && (det.invites || []).filter(i => i.status === "pending").length > 0 && React.createElement("div", null,
      React.createElement("div", { className: "eyebrow", style: { margin: "6px 0 6px" } }, TR("Ждут решения")),
      (det.invites || []).filter(i => i.status === "pending").map(i => React.createElement("div", { key: i.id,
        className: "row between", style: { fontSize: 13, padding: "4px 0" } },
        React.createElement("span", null, i.email + " · " + roleLabel(i.role)),
        React.createElement(Btn, { variant: "ghost", size: "sm",
          onClick: () => window.API.safeCall(() => window.API.teamInviteRevoke(tid, i.id)).then(reload) }, TR("Отозвать"))))));
}

/* ---------- Команда: одним блоком ----------
   Прежде люди жили в ДВУХ местах: «Пользователи» на экране организации
   (вход по логину и паролю) и «Участники команды» здесь (приглашение
   по почте) — один вопрос «кто со мной работает», заданный дважды.
   Теперь блок один: кто в команде, как позвать нового, другие команды. */
function ProfileTeamBlock({ data, onChange, toast, store }) {
  const active = (data.teams || []).find(t => t.id === data.activeTeam) || {};
  const homeOwner = !!(active.home && active.role === "owner" && store && store.can && store.can.owner);
  return React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 18 } },
    React.createElement("div", null,
      React.createElement("h2", { className: "section-title", style: { margin: 0, display: "flex", alignItems: "center", gap: 8 } },
        React.createElement(Icon, { name: "user", size: 18 }), TR("Создайте свою команду")),
      React.createElement("p", { className: "dim", style: { margin: "6px 0 0", fontSize: 14 } },
        TR("Позовите коллег работать над переводами вместе. У команды общие проекты и словари."))),
    homeOwner && React.createElement(ProfileCard, { title: TR("Люди в вашей команде"), bare: true },
      typeof OrgUsers === "function" ? React.createElement(OrgUsers, { toast }) : null),
    React.createElement(ProfileMembers, { data, toast, bare: true, hideHome: homeOwner }),
    React.createElement(ProfileTeams, { data, onChange, toast, bare: true }));
}

/* ---------- Экран ----------
   Одна колонка — одинаково на мониторе и на телефоне: сверху то, что ждёт
   ответа (приглашения), потом про себя (кто я, язык, пароль), потом команда,
   а в самом низу — приглашения коллег за страницы. */
function TabProfile({ store, toast, theme, onToggleTheme }) {
  const [data, setData] = useState(null);
  const load = () => window.API.safeCall(() => window.API.profile()).then(r => { if (r) setData(r); return r; });
  useEffect(() => { load(); }, []);
  if (!data) return React.createElement("div", { className: "page" },
    React.createElement("p", { className: "dim" }, TR("Загружаем профиль…")));

  const onSaved = (me) => { if (me) setData(d => ({ ...d, me })); };
  return React.createElement("div", { className: "page page-narrow" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, TR("Профиль")),
      React.createElement("p", { className: "lead" }, TR("Ваши данные, язык, пароль и команда."))),
    React.createElement("div", { className: "col profile-one", style: { gap: 16 } },
      React.createElement(ProfileInvites, { data, onChange: load, toast }),
      React.createElement(ProfileIdentity, { data, onSaved, toast, theme, onToggleTheme }),
      React.createElement(ProfilePassword, { toast }),
      React.createElement(ProfileTeamBlock, { data, onChange: load, toast, store }),
      store && store.can && store.can.owner && typeof OrgReferral === "function"
        ? React.createElement(OrgReferral, { toast }) : null));
}

window.TabProfile = TabProfile;
