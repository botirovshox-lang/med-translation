/* ============================================================
   Tab: Import DOCX — create projects from Word documents
   ============================================================ */
function TabImport({ store, toast }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);      // { name, size, raw: File }
  const [title, setTitle] = useState("");
  const [src, setSrc] = useState("RU");
  const [tgt, setTgt] = useState("EN");
  const [creating, setCreating] = useState(false);
  const [progress, setProgress] = useState("");
  const fileRef = useRef(null);

  const pickFile = (f) => {
    if (!f) return;
    setFile({ name: f.name, size: (f.size / 1024).toFixed(0) + " КБ", raw: f });
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  };
  const onDrop = (e) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) pickFile(f);
  };
  const create = async () => {
    if (!file || !file.raw) { toast.error("Файл не выбран", "Выберите .docx файл"); return; }
    setCreating(true);
    setProgress("Загружаем файл…");
    try {
      const project = await window.API.uploadProject(file.raw, title || file.name.replace(/\.[^.]+$/, ""), src, tgt);
      setProgress("");
      setCreating(false);
      store.addProject(project);
      toast.success("Проект создан", project.segments.length + " сегментов готовы к переводу.");
      store.openProject(project.id);
    } catch (e) {
      setProgress("");
      setCreating(false);
      toast.error("Ошибка импорта", e.message || "Не удалось разобрать файл");
    }
  };

  const langOpts = [["RU", "Русский"], ["EN", "Английский"], ["DE", "Немецкий"], ["FR", "Французский"], ["ES", "Испанский"]];

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "page-head" },
      React.createElement("h1", null, "Импорт документа"),
      React.createElement("p", { className: "lead" }, "Загрузите файл Word, чтобы создать новый проект перевода. Документ автоматически разбивается на сегменты с сохранением форматирования.")
    ),

    // Section 1: upload
    React.createElement("div", { className: "section" },
      React.createElement("div", { className: "grid", style: { gridTemplateColumns: "1.3fr 1fr", gap: 24, alignItems: "start" } },
        React.createElement("div", null,
          React.createElement("div", { className: "eyebrow" }, "Шаг 1 — Файл"),
          React.createElement("div", {
            className: "dropzone" + (dragging ? " drag" : ""),
            onDragOver: (e) => { e.preventDefault(); setDragging(true); },
            onDragLeave: () => setDragging(false),
            onDrop,
            onClick: () => fileRef.current && fileRef.current.click(),
            role: "button", tabIndex: 0,
            onKeyDown: (e) => { if (e.key === "Enter") fileRef.current.click(); },
          },
            React.createElement("input", { ref: fileRef, type: "file", accept: ".docx", hidden: true,
              onChange: (e) => pickFile(e.target.files[0]) }),
            file
              ? React.createElement("div", null,
                  React.createElement(Icon, { name: "file", size: 36, className: "dz-ic", style: { color: "var(--c-success)" } }),
                  React.createElement("div", { style: { fontWeight: 650, fontSize: 16 } }, file.name),
                  React.createElement("div", { className: "dim", style: { marginTop: 4 } }, file.size + " · нажмите, чтобы заменить"))
              : React.createElement("div", null,
                  React.createElement(Icon, { name: "upload", size: 36, className: "dz-ic" }),
                  React.createElement("div", { style: { fontWeight: 650, fontSize: 16 } }, "Перетащите DOCX сюда"),
                  React.createElement("div", { className: "dim", style: { marginTop: 4 } }, "или нажмите для выбора файла"))
          )
        ),
        React.createElement("div", { className: "card card-pad", style: { display: "flex", flexDirection: "column", gap: 18 } },
          React.createElement("div", { className: "eyebrow", style: { margin: 0 } }, "Шаг 2 — Параметры"),
          React.createElement(Field, { label: "Название проекта" },
            React.createElement(Input, { value: title, placeholder: "напр. Эпикриз 2026", onChange: (e) => setTitle(e.target.value) })),
          React.createElement("div", { className: "grid grid-2" },
            React.createElement(Field, { label: "Язык оригинала" },
              React.createElement(Select, { value: src, onChange: (e) => setSrc(e.target.value) },
                langOpts.map(([v, l]) => React.createElement("option", { key: v, value: v }, l)))),
            React.createElement(Field, { label: "Язык перевода" },
              React.createElement(Select, { value: tgt, onChange: (e) => setTgt(e.target.value) },
                langOpts.map(([v, l]) => React.createElement("option", { key: v, value: v }, l))))
          ),
          React.createElement(Btn, { variant: "primary", icon: creating ? null : "arrowR", disabled: !file || !file.raw || creating, onClick: create },
            creating ? React.createElement(React.Fragment, null, React.createElement(Spinner, null), progress || "Загрузка…") : "Создать проект")
        )
      )
    ),

    // Section 2: existing projects
    React.createElement("div", { className: "section" },
      React.createElement("div", { className: "row between", style: { marginBottom: 16 } },
        React.createElement("h2", { className: "section-title", style: { margin: 0 } }, "Ваши проекты"),
        React.createElement("span", { className: "dim" }, store.projects.length + " всего")
      ),
      React.createElement("div", { className: "grid grid-3" },
        store.projects.map(p => React.createElement(ProjectCard, { key: p.id, project: p, store, toast }))
      )
    )
  );
}

function ProjectCard({ project, store, toast }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const counts = store.statusCounts(project);
  const total = project.segments.length;
  const done = counts.confirmed;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const statusMap = { in_progress: ["badge-review", "В работе"], review: ["badge-qa", "На проверке"], done: ["badge-confirmed", "Завершён"] };
  const [bcls, blab] = statusMap[project.status] || statusMap.in_progress;

  const handleDelete = () => {
    store.deleteProject(project.id);
    toast.warning("Проект удалён", project.title);
  };

  return React.createElement(React.Fragment, null,
    React.createElement("div", { className: "card card-pad card-hover", style: { display: "flex", flexDirection: "column", gap: 14 } },
      React.createElement("div", { className: "row between", style: { alignItems: "flex-start" } },
        React.createElement("div", { style: { minWidth: 0 } },
          React.createElement("div", { style: { fontWeight: 700, fontSize: 16, letterSpacing: "-.2px" } }, project.title),
          React.createElement("div", { className: "dim", style: { fontSize: 13, marginTop: 2 } }, project.titleEn)),
        React.createElement("span", { className: "badge " + bcls }, blab)
      ),
      React.createElement("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
        React.createElement(Badge, { icon: "list" }, total + " сегментов"),
        React.createElement(LangPair, { src: project.src, tgt: project.tgt })
      ),
      React.createElement("div", null,
        React.createElement("div", { className: "row between", style: { fontSize: 12, marginBottom: 6 } },
          React.createElement("span", { className: "muted" }, "Подтверждено"),
          React.createElement("span", { style: { fontWeight: 700 } }, pct + "%")),
        React.createElement(ProgressBar, { value: pct })
      ),
      React.createElement("div", { className: "row between", style: { marginTop: 2 } },
        React.createElement("div", { className: "row", style: { gap: 8 } },
          React.createElement(Btn, { variant: "secondary", size: "sm", icon: "edit", onClick: () => store.openProject(project.id) }, "Открыть"),
          React.createElement(Btn, { variant: "ghost", size: "sm", icon: "download", onClick: () => { store.openProject(project.id); store.go("export"); } }, "Экспорт")
        ),
        React.createElement(IconBtn, { icon: "trash", label: "Удалить проект", sm: true, onClick: (e) => { e.stopPropagation(); setConfirmDelete(true); } })
      )
    ),
    confirmDelete && React.createElement(Modal, {
      title: "Удалить проект?", icon: "trash", onClose: () => setConfirmDelete(false),
      footer: React.createElement(React.Fragment, null,
        React.createElement(Btn, { variant: "ghost", onClick: () => setConfirmDelete(false) }, "Отмена"),
        React.createElement(Btn, { variant: "danger", icon: "trash", onClick: handleDelete }, "Удалить"))
    },
      React.createElement("p", { style: { margin: 0 } },
        "Проект «", React.createElement("strong", null, project.title), "» будет удалён безвозвратно. ",
        React.createElement("br", null),
        React.createElement("span", { className: "dim" }, total + " сегментов · " + done + " подтверждено"))
    )
  );
}
window.TabImport = TabImport;
