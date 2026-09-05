/* ============================================================
   API client — talks to FastAPI backend at /api/*
   ============================================================ */
(function () {
  const BASE = (window.API_BASE || "") + "/api";
  const TOKEN_KEY = "mct-token";

  /* sessionStorage, а не localStorage: закрыл вкладку — токен пропал.
     Медицинские документы не должны оставаться доступными на общем компьютере. */
  function getToken() {
    try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
  }
  function setToken(t) {
    try {
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch (e) {}
  }
  function authHeaders(h) {
    const t = getToken();
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }
  /* Токен истёк или процесс перезапущен → выкидываем на экран входа. */
  function onUnauthorized() {
    setToken("");
    window.dispatchEvent(new Event("mct-auth-expired"));
  }

  /* Правки ОДНОГО сегмента, ушедшие на сервер: сколько начато и сколько
     закончено. Считает один потребитель — сверка статусов в редакторе.

     Правка применяется в браузере сразу, а на сервер уходит отдельным
     запросом. Разбор состава, посланный МЕЖДУ этими двумя событиями, вернёт
     статусы ДО правки — и сверка приняла бы свежую вкладку за устаревшую
     и потянула бы весь проект заново: на 2711 сегментах это пять мегабайт
     на каждое нажатие «Подтвердить».

     Отпечаток строкой, а не флагом «занято»: правка, успевшая и начаться,
     и закончиться за время разбора, флагом не ловится, а отпечатком —
     ловится. Считаем по префиксу пути, а не по списку методов: под
     /segments/ лежат ВСЕ команды, меняющие один сегмент (перевод,
     подтверждение, откат, правка, ремонт, рассылка повторов), и перечислять
     их поимённо значит однажды забыть новую. Пакетные /projects/... сюда
     не попадают намеренно: они идут задачами, а на время задачи разбор
     состава и так не считается. */
  let segStarted = 0, segDone = 0, segFailed = 0;

  async function call(method, path, body) {
    const seg = path.lastIndexOf("/segments/", 0) === 0;
    if (seg) segStarted++;
    try {
      const init = { method, headers: authHeaders({}) };
      if (body !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
      }
      const r = await fetch(BASE + path, init);
      if (r.status === 401 && path !== "/auth/login") onUnauthorized();
      if (!r.ok) {
        const text = await r.text().catch(() => "");
        /* Граница показа ответа сервера — единственное место, где работает
           фразовая подстановка TRS(). Сервер отвечает по-русски намеренно
           (его строки лежат в боевых данных и разбираются подстрокой), а
           человеку показывать «API POST /… failed: 402 {"error":…}» нельзя:
           это не сообщение, а свалка. Достаём причину и переводим ЕЁ. */
        let detail = "";
        try { const j = JSON.parse(text); detail = j.detail || j.error || ""; }
        catch (e) { detail = ""; }
        if (typeof detail !== "string") detail = "";
        const err = new Error(detail ? TRS(detail)
                                     : `API ${method} ${path} failed: ${r.status} ${text}`);
        err.status = r.status;
        err.detail = detail;
        throw err;
      }
      return await r.json();
    } catch (e) {
      /* Правка НЕ доехала. Считаем такие отдельно и навсегда: локальный патч
         применён (store.updateSegment оптимистичен), а на сервере его нет —
         значит в браузере лежит текст, которого сервер не знает. Подстановка
         проекта целиком выбросила бы его молча, вместе с набранным человеком
         переводом. Пока такая правка есть, сверка статусов не работает:
         несохранённая работа человека дороже автоматической синхронизации. */
      if (seg) segFailed++;
      throw e;
    } finally {
      // finally, а не после return: упавший запрос обязан снять отметку «в пути»
      // тоже, иначе одна моргнувшая сеть вешает счётчик навсегда.
      if (seg) segDone++;
    }
  }

  window.API = {
    /* busy — правка сегмента ещё в пути, failed — хоть одна не доехала,
       ticket — отпечаток «начато:закончено». См. комментарий у счётчиков выше. */
    segEdits:      ()                       => ({ busy: segStarted !== segDone,
                                                  failed: segFailed > 0,
                                                  ticket: segStarted + ":" + segDone }),
    health:        ()                       => call("GET",    "/health"),
    seed:          ()                       => call("GET",    "/seed"),
    signupInfo:    ()                       => call("GET",    "/auth/signup-info"),
    register:      (body)                   => call("POST",   "/auth/register", body),
    resendCode:    (email)                  => call("POST",   "/auth/resend", { email }),
    forgotPassword:(email)                  => call("POST",   "/auth/forgot", { email }),
    verifyEmail: async (email, code) => {
      const r = await call("POST", "/auth/verify", { email, code });
      if (r && r.token) setToken(r.token);
      return r;
    },
    resetPassword: async (email, code, password) => {
      const r = await call("POST", "/auth/reset", { email, code, password });
      if (r && r.token) setToken(r.token);
      return r;
    },
    login: async (login, password) => {
      const r = await call("POST", "/auth/login", { login: login || "", password });
      if (!r || !r.token) throw new Error(TR("Сервер не выдал токен сессии"));
      setToken(r.token);
      return r;
    },
    logout: async () => {
      try { await call("POST", "/auth/logout"); } catch (e) { /* токен всё равно стираем */ }
      setToken("");
    },
    hasToken: () => !!getToken(),
    me:            ()                       => call("GET",    "/auth/me"),
    /* ── Профиль и команды ──────────────────────────────────────────
       Профиль доступен КАЖДОМУ вошедшему, в отличие от /admin/users:
       переводчику туда хода нет, а язык интерфейса и пароль менять надо.
       Команда — это рабочее пространство (арендатор), поэтому её
       переключение меняет ВСЁ, что видно на экране, и делается отдельным
       запросом, а не флажком в браузере. */
    profile:       ()                       => call("GET",    "/profile"),
    profileSave:   (body)                   => call("POST",   "/profile", body),
    teamSwitch:    (tenant)                 => call("POST",   "/profile/team", { tenant }),
    inviteDecide:  (iid, action)            => call("POST",   `/profile/invites/${iid}`, { action }),
    teams:         ()                       => call("GET",    "/teams"),
    teamCreate:    (name)                   => call("POST",   "/teams", { name }),
    teamDetail:    (tid)                    => call("GET",    `/teams/${encodeURIComponent(tid)}`),
    teamInvite:    (tid, email, role)       => call("POST",   `/teams/${encodeURIComponent(tid)}/invite`, { email, role: role || "translator" }),
    teamInviteRevoke: (tid, iid)            => call("POST",   `/teams/${encodeURIComponent(tid)}/invites/${iid}/revoke`),
    teamMember:    (tid, uid, body)         => call("POST",   `/teams/${encodeURIComponent(tid)}/members/${uid}`, body),
    teamLeave:     (tid)                    => call("POST",   `/teams/${encodeURIComponent(tid)}/leave`),
    users:         ()                       => call("GET",    "/admin/users"),
    userCreate:    (body)                   => call("POST",   "/admin/users", body),
    userUpdate:    (uid, body)              => call("POST",   `/admin/users/${uid}`, body),
    tenantCreate:  (body)                   => call("POST",   "/admin/tenants", body),
    tenants:       ()                       => call("GET",    "/admin/tenants"),
    adminOverview: ()                       => call("GET",    "/admin/overview"),
    usersAll:      ()                       => call("GET",    "/admin/users?all=1"),
    auditAll:      (limit)                  => call("GET",    "/admin/audit?all=1&limit=" + (limit || 300)),
    tenantUpdate:  (tid, body)              => call("POST",   `/admin/tenants/${tid}`, body),
    userDelete:    (uid)                    => call("DELETE", `/admin/users/${uid}`),
    tenantDelete:  (tid)                    => call("DELETE", `/admin/tenants/${tid}`),
    audit:         (limit)                  => call("GET",    "/admin/audit?limit=" + (limit || 200)),
    domains:       ()                       => call("GET",    "/admin/domains"),
    domainCreate:  (body)                   => call("POST",   "/admin/domains", body),
    domainUpdate:  (did, body)              => call("POST",   `/admin/domains/${did}`, body),
    domainDelete:  (did)                    => call("DELETE", `/admin/domains/${did}`),
    setProjectDomain: (pid, domain)         => call("POST",   `/projects/${pid}/domain`, { domain }),
    /* Для <a href> скачивания: заголовок в ссылку не подставить, токен идёт в query. */
    downloadUrl: (url) => url + (url.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(getToken()),

    /* lang/domain сужают выдачу до области проекта — той, что уходит в промпт. */
    listGlossary:  (q, cat, limit, offset, lang, domain) => call("GET", `/glossary?q=${encodeURIComponent(q||"")}&cat=${encodeURIComponent(cat||"")}&limit=${limit||200}&offset=${offset||0}&lang=${encodeURIComponent(lang||"")}&domain=${encodeURIComponent(domain||"")}`),
    listProjects:  ()                       => call("GET",    "/projects"),
    getProject:    (pid)                    => call("GET",    `/projects/${pid}`),
    createProject: (info)                   => call("POST",   "/projects",                          info),
    deleteProject: (pid)                    => call("DELETE", `/projects/${pid}`),
    uploadProject: async (file, title, src, tgt, domain) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", title || "");
      fd.append("src",   src  || "RU");
      fd.append("tgt",   tgt  || "EN");
      fd.append("domain", domain || "medical");
      const r = await fetch((window.API_BASE || "") + "/api/projects/upload",
                            { method: "POST", body: fd, headers: authHeaders({}) });
      if (r.status === 401) onUnauthorized();
      if (!r.ok) {
        // Отказ импорта (потолки страниц/проектов, размер файла) — текст
        // сервера, и переводится он там же, где все detail: через TRS().
        const t = await r.text().catch(() => "");
        let d = ""; try { d = JSON.parse(t).detail || ""; } catch (e) { d = ""; }
        const err = new Error(typeof d === "string" && d ? TRS(d) : "Upload failed: " + r.status + " " + t);
        err.status = r.status; throw err;
      }
      return r.json();
    },

    models:        ()                       => call("GET",    "/models"),

    /* ── Страницы и стоимость ──────────────────────────────────────
       Норму страницы и прайс отдаёт СЕРВЕР: второй прайс-лист в .jsx —
       ровно та беда, ради которой модели и их цены живут в OPENAI_MODELS.
       Считать смету вправе любой, править прайс — только владелец (403). */
    pricing:       ()                       => call("GET",    "/pricing"),
    /* История смет: числа заморожены на момент расчёта, здесь их не
       пересчитывают. Судьбу сметы (выставлена/оплачена) правит владелец. */
    quotes:        (limit)                  => call("GET",    `/quotes?limit=${limit || 200}`),
    quoteMark:     (qid, body)              => call("POST",   `/quotes/${qid}`, body),
    quoteDelete:   (qid)                    => call("DELETE", `/quotes/${qid}`),
    pricingSave:   (body)                   => call("POST",   "/pricing", body),
    quoteProject:  (pid, withFile)          => call("GET",    `/projects/${pid}/quote?withFile=${withFile ? "true" : "false"}`),
    /* Файл никуда не сохраняется — ни на диск, ни в состояние: это только
       расчёт. Ошибки разные и разбираются по коду: 413 — файл велик,
       415 — формат не разбираем, 503 — нечем прочитать. */
    quoteFile: async (file, src, tgt) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("src", src || "RU");
      fd.append("tgt", tgt || "EN");
      const r = await fetch(BASE + "/quote", { method: "POST", body: fd, headers: authHeaders({}) });
      if (r.status === 401) onUnauthorized();
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { const e = new Error(data.detail || data.error || (TR("Не посчитано: ") + r.status)); e.status = r.status; throw e; }
      return data;
    },
    importGlossary: async (file, lang, domain, tier, dryRun) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("lang", lang || "");
      fd.append("domain", domain || "");
      fd.append("tier", tier || "auto");
      fd.append("dry_run", dryRun ? "true" : "false");
      const r = await fetch(BASE + "/glossary/import", { method: "POST", body: fd, headers: authHeaders({}) });
      if (r.status === 401) onUnauthorized();
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { const e = new Error(data.detail || data.error || ("Import failed: " + r.status)); e.status = r.status; throw e; }
      return data;
    },
    /* Движок один — выбранная модель. Параметра engine больше нет. */
    translate:     (pid, sid, force, model) => call("POST", `/segments/${pid}/${sid}/translate`, { force: !!force, model: model || null }),
    backcheck:     (pid, sid, model, judge, judgeModel) => call("POST", `/segments/${pid}/${sid}/backcheck`, { model: model || null, use_judge: !!judge, judge_model: judgeModel || null }),
    backcheckBatch:(pid, segIds, limit, model, judge, judgeModel, skipCached) => call("POST", `/projects/${pid}/backcheck/batch`, { segment_ids: segIds || null, limit: limit || 10, model: model || null, use_judge: !!judge, judge_model: judgeModel || null, skip_cached: skipCached !== false }),
    /* Пересчёт сохранённых оценок back-check по нынешним правилам. Бесплатный:
       обратный перевод берётся из самой записи, ни одного вызова модели. */
    rescoreBackchecks: (pid, dryRun, force) => call("POST", `/projects/${pid}/backcheck/rescore`, { dry_run: dryRun !== false, force: !!force }),
    runChecks:     (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/checks`,  { run_backcheck: true }),
    qa:            (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/qa`),
    confirm:       (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/confirm`),
    revert:        (pid, sid)               => call("POST",   `/segments/${pid}/${sid}/revert`),
    update:        (pid, sid, patch)        => call("POST",   `/segments/${pid}/${sid}/update`,     patch),

    batch:         (pid, segIds, force, limit, model) => call("POST", `/projects/${pid}/batch`, { segment_ids: segIds || null, force: !!force, limit: limit || 50, model: model || null }),
    checksBatch:(pid, segIds, bcModel)    => call("POST",   `/projects/${pid}/checks/batch`,   { segment_ids: segIds || null, run_backcheck: true, bc_model: bcModel || null }),
    preflight:     (pid)                    => call("POST",   `/projects/${pid}/preflight`),
    exportProject: (pid, format, source)    => call("POST",   `/projects/${pid}/export`,            { format, source: source !== false }),
    /* Исходный .docx для экспорта 1в1. Переводы и проверки не трогает: пишется
       только файл и карта абзацев рядом с ним. force — согласие человека
       положить файл, совпавший меньше чем наполовину. */
    attachSource: async (pid, file, force) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("force", force ? "true" : "false");
      const r = await fetch((window.API_BASE || "") + "/api/projects/" + pid + "/source",
                            { method: "POST", body: fd, headers: authHeaders({}) });
      if (r.status === 401) onUnauthorized();
      if (!r.ok) { const t = await r.text().catch(() => ""); throw new Error("Attach failed: " + r.status + " " + t); }
      return r.json();
    },

    /* Текст, впечатанный в картинки. Разбор идёт задачей (createJob "images"):
       158 картинок учебника — это минуты только на поиск строк, и запросом
       такое делать нельзя. dry_run=true ищет строки и ничего не платит. */
    imagesReport:  (pid)                    => call("GET",    `/projects/${pid}/images`),
    /* wipe — забыть и ПРОЧИТАННЫЙ текст. По умолчанию он остаётся: геометрия
       стоила минут работы детектора, текст ещё и оплачен, а повторный заход
       заведёт сегменты заново бесплатно. */
    imagesForget:  (pid, force, wipe)       => call("POST",   `/projects/${pid}/images/forget`, { force: !!force, wipe: !!wipe }),
    /* Найденные надписи списком: что отсеяно и почему. Без этого «Отсеяно:
       230» — число, которое человеку нечем проверить. */
    imagesBlocks:  (pid, skip, limit)       => call("GET",    `/projects/${pid}/images/blocks?skip=${encodeURIComponent(skip || "")}&limit=${limit || 2000}`),
    /* Обратное решение: «это текст документа, а не надпись аппарата». */
    imageRestore:  (pid, part, block)       => call("POST",   `/projects/${pid}/images/restore`, { part, block }),
    /* «Это надпись аппарата»: убрать сегмент и запомнить метку на блоке,
       чтобы следующий разбор не завёл его заново. */
    imageMarkOverlay: (pid, sid)            => call("POST",   `/projects/${pid}/images/${sid}/overlay`),
    /* Кроп отдаётся картинкой и требует токен, поэтому <img src="..."> тут
       не годится: заголовок в src не положишь, а пускать эндпоинт без токена
       значит открыть куски документов всему интернету. Тянем сами и отдаём
       blob-ссылку. */
    /* Кусок картинки можно спросить и по сегменту, и по паре «часть + блок»:
       второе нужно списку отсеянного — там сегмента ещё нет, а решать
       по голой строке текста человек не должен. */
    imageCropUrl: async (pid, ref) => {
      const q = (ref && typeof ref === "object")
        ? `part=${encodeURIComponent(ref.part)}&block=${ref.block}`
        : `seg=${ref}`;
      const r = await fetch(`${BASE}/projects/${pid}/images/crop?${q}`, { headers: authHeaders({}) });
      if (r.status === 401) onUnauthorized();
      if (!r.ok) return null;
      return URL.createObjectURL(await r.blob());
    },

    termcheck:     (pid, sid, model)        => call("POST", `/segments/${pid}/${sid}/termcheck`, { model: model || null }),
    repair:        (pid, sid, opts)         => call("POST", `/segments/${pid}/${sid}/repair`, opts || {}),
    // Принять текст, который ремонт написал и отменил падением балла.
    // Вызова модели нет: подставляется уже написанный repair.candidate.
    acceptRepair:  (pid, sid)               => call("POST", `/segments/${pid}/${sid}/repair/accept`, {}),
    // Пачкой. dry_run=true — только посчитать; откат по stamp.
    acceptRepairBatch: (pid, opts)          => call("POST", `/projects/${pid}/repair/accept-batch`, opts || {}),
    undoAcceptRepair:  (pid, stamp)         => call("POST", `/projects/${pid}/repair/accept/${stamp}/undo`, {}),

    /* Фоновые прогоны: клиент только ставит задачу и смотрит прогресс */
    // Разбор прогона до запуска. Состав считает сервер тем же кодом, который
    // потом и работает: у браузера были свои предикаты, у сервера свои, и
    // расходились они не в пользу человека — смета показывала одно, а списывалось
    // другое. Ответ содержит и причины, по которым сегменты пропущены.
    runPlan:       (pid, body)              => call("POST", `/projects/${pid}/run-plan`, body || {}),
    createJob:     (pid, kind, segIds, params) => call("POST", `/projects/${pid}/jobs`, { kind, segment_ids: segIds, params: params || {} }),
    listJobs:      (pid)                    => call("GET",    `/jobs?project=${pid}`),
    fetchSegments: (pid, ids)               => call("POST",   `/projects/${pid}/segments/fetch`, { ids }),
    stopJob:       (jid)                    => call("POST",   `/jobs/${jid}/stop`),
    repairBatch:   (pid, segIds, limit, opts) => call("POST", `/projects/${pid}/repair/batch`, { segment_ids: segIds || null, limit: limit || 5, ...(opts || {}) }),
    termcheckBatch:(pid, segIds, limit, model, skipCached) => call("POST", `/projects/${pid}/termcheck/batch`, { segment_ids: segIds || null, limit: limit || 10, model: model || null, skip_cached: skipCached !== false }),

    /* Подтверждение теперь возвращает {tm, propagate, termCandidates} — см. confirm_segment */
    propagate:     (pid, sid, ids, includeConfirmed) => call("POST", `/segments/${pid}/${sid}/propagate`, { ids: ids || null, include_confirmed: !!includeConfirmed }),
    /* project — чтобы разбор «почему ждёт» считался в области проекта. */
    termQueue:     (status, limit, pid)     => call("GET",    `/term-queue?status=${encodeURIComponent(status || "pending")}&limit=${limit || 200}${pid ? "&project=" + pid : ""}`),
    /* Массовым может быть только отклонение: одобрение пачкой — auto-approve. */
    bulkReject:    (ids)                    => call("POST",   "/term-queue/bulk", { ids, action: "reject" }),
    glossaryUsage: (src, limit, lang, domain) => call("GET",  `/glossary/usage?src=${encodeURIComponent(src)}&limit=${limit || 6}&lang=${encodeURIComponent(lang||"")}&domain=${encodeURIComponent(domain||"")}`),
    /* refresh — «Пересчитать» руками: отчёт кэширован по отпечатку проекта,
       и без этого нажатие возвращало бы посчитанное раньше, ничего не сделав. */
    glossaryImpact:(pid, refresh)           => call("GET",    `/projects/${pid}/glossary-impact` + (refresh ? "?refresh=true" : "")),
    /* Начертание приказных терминов — под оригинал, 1в1. Вызовов модели НЕТ:
       меняются только заглавные и строчные, слова и порядок те же. dryRun
       по умолчанию: сначала показываем, что изменится, потом делаем. */
    /* segmentIds — не украшение: без него сервер правит ВЕСЬ проект, а кнопка
       рядом обещает конкретное число. Расходятся они там, где часть сегментов
       с расхождением начертания ушла человеку (заверенные, споры), — тогда
       правится больше, чем сказано. */
    termCase:      (pid, opts)              => call("POST",   `/projects/${pid}/term-case`, {
                                                 dry_run: !(opts && opts.apply),
                                                 segment_ids: (opts && opts.segmentIds) || null,
                                                 include_confirmed: !!(opts && opts.includeConfirmed) }),
    /* Итог по проекту одним экраном: чисто / исправлено машиной / нужен человек.
       Вызовов модели внутри нет, дёргать можно свободно. */
    analysis:      (pid)                    => call("GET",    `/projects/${pid}/analysis`),
    coverage:      (pid)                    => call("GET",    `/projects/${pid}/coverage`),
    style:         (pid)                    => call("GET",    `/projects/${pid}/style`),
    termlist:      (pid)                    => call("GET",    `/projects/${pid}/termlist`),
    setTermlist:   (pid, body)              => call("POST",   `/projects/${pid}/termlist`, body || {}),
    setStyle:      (pid, body)              => call("POST",   `/projects/${pid}/style`, body || {}),
    styleCheck:    (pid, body)              => call("POST",   `/projects/${pid}/style-check`, body || {}),
    styleUndo:     (pid, stamp)             => call("POST",   `/projects/${pid}/style-check/${stamp}/undo`, {}),
    orgStyle:      ()                       => call("GET",    `/style`),
    setOrgStyle:   (fields)                 => call("POST",   `/style`, { fields }),
    /* Контекстный арбитр спорного термина: смотрит сегмент ДО, этот и ПОСЛЕ.
       Единственный вызов в системе, которому дают соседей, — потому что
       вопрос «правильно ли передан термин ЗДЕСЬ» без ряда не решается.
       Платный, поэтому с потолком; вердикт кэшируется на сегменте. */
    termContext:   (pid, body)               => call("POST",   `/projects/${pid}/term-context`, body || {}),
    termContextApply: (pid, body)            => call("POST",   `/projects/${pid}/term-context/apply`, body || {}),
    termContextUndo:  (pid, stamp)           => call("POST",   `/projects/${pid}/term-context/apply/${stamp}/undo`, {}),
    /* Разбор вариантов НА ЯЗЫКЕ ОРИГИНАЛА: обратный перевод, значение и область
       употребления по каждому. Для тех, кто целевого языка не знает: сравнивать
       нужно смысл, написанный понятным языком, а не строки. Вызов платный. */
    explainTerm:   (cid, include)            => call("POST",   `/term-queue/${cid}/explain`, { include: include || null }),
    /* patch.confirm — «знаю о замечании, всё равно одобряю». Без него сервер
       возвращает warning и НЕ пишет: предупредить после записи бессмысленно. */
    approveTerm:   (cid, patch)             => call("POST",   `/term-queue/${cid}/approve`,          patch || {}),
    rejectTerm:    (cid)                    => call("POST",   `/term-queue/${cid}/reject`),
    extractTerms:  (pid, segIds, limit, model) => call("POST", `/projects/${pid}/extract-terms`,     { segment_ids: segIds || null, limit: limit || 30, model: model || null }),
    /* Автоодобрение: dry_run по умолчанию — сервер только считает вердикты. */
    autoApprove:   (opts)                   => call("POST",   "/term-queue/auto-approve",           opts || {}),
    undoAutoApprove:(batch)                 => call("POST",   `/term-queue/auto-approve/${batch}/undo`),
    autoBatches:   ()                       => call("GET",    "/term-queue/auto-batches"),
    /* Смысловая сверка записей, УЖЕ стоящих приказом. dry_run по умолчанию. */
    auditGlossary: (opts)                   => call("POST",   "/glossary/audit",                    opts || {}),
    /* force — переспросить и то, что уже сверялось: вердикт лежит на записи. */
    /* Массовый вынос автоимпорта. dry_run по умолчанию — сервер только считает. */
    purgeGlossary:(opts)                    => call("POST",   "/glossary/purge",                    opts || {}),
    purgeList:     ()                       => call("GET",    "/glossary/purge/list"),
    undoPurge:     (stamp)                  => call("POST",   `/glossary/purge/${stamp}/undo`),

    saveTerm:      (term, isNew)            => call("POST",   "/glossary",                          { ...term, isNew }),
    /* Область обязательна: без неё удаление уносит однофамильца из другой пары языков. */
    deleteTerm:    (src, lang, domain)      => call("DELETE", `/glossary?src=${encodeURIComponent(src)}&lang=${encodeURIComponent(lang||"")}&domain=${encodeURIComponent(domain||"")}`),
    /* Понижение приказа до подсказки: намерение, обратное правке (там «правка
       руками = приказ»), поэтому отдельной дверью. */
    demoteTerm:    (src, lang, domain)      => call("POST",   "/glossary/demote", { src, lang: lang || "", domain: domain || "" }),
    /* Откат правок, сделанных по этой записи. Текст меняется БЕЗ вызова модели:
       подставляется repair.from — то, что стояло до правки. */
    revertRepairs: (src, lang, domain)      => call("POST",   "/glossary/revert-repairs", { src, lang: lang || "", domain: domain || "" }),
    deleteTM:      (src, lang)              => call("DELETE", `/tm?src=${encodeURIComponent(src)}&lang=${encodeURIComponent(lang||"")}`),
  };

  // Best-effort: fail silently in dev if backend down (UI keeps working on mock data).
  window.API.safeCall = async function (fn) {
    try { return await fn(); }
    catch (e) { console.warn("[API] call failed, using local state:", e.message); return null; }
  };
})();
