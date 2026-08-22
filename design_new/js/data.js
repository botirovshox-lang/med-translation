/* ============================================================
   Sample data — Medical CAT Translator v5.5
   Realistic RU -> EN clinical content. Exposed as window.SEED.
   ============================================================ */
(function () {
  // status: new | translated | qa | confirmed | failed | review
  // route:  EXACT_TM | DUPLICATE | GOOGLE_SAFE | GPT_REQUIRED | HUMAN_REVIEW
  // risk:   low | medium | high | critical

  const seg = (id, source, target, status, route, risk, extra) =>
    Object.assign({ id, source, target, status, route, risk, comments: [], qa: [], tm: null }, extra || {});

  const project7 = {
    id: 7,
    title: "Эпикриз — кардиология 2026",
    titleEn: "Discharge Summary — Cardiology 2026",
    src: "RU", tgt: "EN",
    status: "in_progress",
    created: "2026-05-28",
    deadline: "2026-06-13",
    segments: [
      seg(1, "Выписной эпикриз пациента, находившегося на стационарном лечении в кардиологическом отделении.",
        "Discharge summary of a patient who received inpatient treatment in the cardiology department.",
        "confirmed", "EXACT_TM", "low",
        { tm: { score: 100, source: "Выписной эпикриз пациента, находившегося на стационарном лечении в кардиологическом отделении.", target: "Discharge summary of a patient who received inpatient treatment in the cardiology department." } }),
      seg(2, "Жалобы при поступлении: давящие боли за грудиной, одышка при умеренной физической нагрузке, перебои в работе сердца.",
        "Complaints on admission: pressing retrosternal pain, dyspnea on moderate exertion, and palpitations.",
        "confirmed", "GPT_REQUIRED", "medium"),
      seg(3, "Анамнез заболевания: считает себя больным в течение трёх лет, когда впервые появились ангинозные приступы.",
        "History of present illness: the patient has considered himself ill for three years, when anginal attacks first appeared.",
        "qa", "GPT_REQUIRED", "medium",
        { qa: [{ sev: "medium", type: "terminology", msg: "Термин «ангинозные» — проверьте соответствие глоссарию (anginal vs. angina-type)." }] }),
      seg(4, "Объективно: общее состояние удовлетворительное. Кожные покровы обычной окраски.",
        "Objectively: general condition is satisfactory. Skin is of normal colour.",
        "confirmed", "DUPLICATE", "low"),
      seg(5, "Тоны сердца приглушены, ритм правильный. ЧСС 78 ударов в минуту. АД 140/90 мм рт. ст.",
        "Heart sounds are muffled, rhythm is regular. Heart rate 78 bpm. Blood pressure 140/90 mmHg.",
        "translated", "GPT_REQUIRED", "high",
        { qa: [] }),
      seg(6, "На ЭКГ: синусовый ритм, признаки гипертрофии левого желудочка, депрессия сегмента ST в отведениях V4–V6.",
        "ECG: sinus rhythm, signs of left ventricular hypertrophy, ST-segment depression in leads V4–V6.",
        "translated", "GPT_REQUIRED", "high"),
      seg(7, "Эхокардиография выявила снижение фракции выброса левого желудочка до 48%.",
        "Echocardiography revealed a reduction of the left ventricular ejection fraction to 48%.",
        "qa", "GPT_REQUIRED", "high",
        { qa: [{ sev: "high", type: "numeric", msg: "Проверьте число: 48% присутствует и в источнике, и в переводе. ОК." }] }),
      seg(8, "Коронароангиография: стеноз передней межжелудочковой ветви левой коронарной артерии до 75%.",
        "Coronary angiography: stenosis of the anterior interventricular branch of the left coronary artery up to 75%.",
        "translated", "GPT_REQUIRED", "critical"),
      seg(9, "Клинический диагноз: ИБС. Стабильная стенокардия напряжения, функциональный класс III.",
        "Clinical diagnosis: coronary artery disease. Stable exertional angina, functional class III.",
        "review", "HUMAN_REVIEW", "critical",
        { qa: [{ sev: "high", type: "terminology", msg: "«ИБС» раскрыто как coronary artery disease — подтвердите предпочтительный вариант (CAD / IHD)." }] }),
      seg(10, "Сопутствующие заболевания: гипертоническая болезнь II стадии, сахарный диабет 2 типа, компенсированный.",
        "Comorbidities: stage II essential hypertension, compensated type 2 diabetes mellitus.",
        "translated", "GPT_REQUIRED", "medium"),
      seg(11, "Назначено лечение: бисопролол 5 мг утром, аторвастатин 20 мг вечером, ацетилсалициловая кислота 75 мг.",
        "Treatment prescribed: bisoprolol 5 mg in the morning, atorvastatin 20 mg in the evening, acetylsalicylic acid 75 mg.",
        "failed", "GPT_REQUIRED", "high",
        { qa: [{ sev: "critical", type: "numeric", msg: "Несоответствие дозировки: проверьте «75 мг» — в черновике перевода указано 750 mg." }] }),
      seg(12, "Рекомендовано: контроль артериального давления, соблюдение гиполипидемической диеты, дозированные физические нагрузки.",
        "",
        "new", "GOOGLE_SAFE", "low"),
      seg(13, "Повторная консультация кардиолога через один месяц с результатами липидограммы.",
        "",
        "new", "GOOGLE_SAFE", "low"),
      seg(14, "Прогноз для жизни благоприятный при условии соблюдения рекомендаций и регулярного приёма препаратов.",
        "",
        "new", "GPT_REQUIRED", "medium"),
      seg(15, "Листок нетрудоспособности выдан с 14.05.2026 по 28.05.2026.",
        "",
        "new", "GOOGLE_SAFE", "low"),
    ],
  };

  const project4 = {
    id: 4,
    title: "Инструкция по применению — Метформин",
    titleEn: "Patient Information Leaflet — Metformin",
    src: "RU", tgt: "EN",
    status: "review",
    created: "2026-05-12",
    deadline: "2026-06-09",
    segments: [
      seg(1, "Перед началом приёма препарата внимательно прочитайте инструкцию.",
        "Read this leaflet carefully before you start taking the medicine.",
        "confirmed", "EXACT_TM", "low"),
      seg(2, "Показания к применению: сахарный диабет 2 типа у взрослых и детей старше 10 лет.",
        "Indications: type 2 diabetes mellitus in adults and children over 10 years of age.",
        "confirmed", "GPT_REQUIRED", "medium"),
      seg(3, "Противопоказания: повышенная чувствительность к метформину, диабетический кетоацидоз.",
        "Contraindications: hypersensitivity to metformin, diabetic ketoacidosis.",
        "qa", "GPT_REQUIRED", "high"),
    ],
  };

  const project2 = {
    id: 2,
    title: "Протокол клинического исследования (фаза II)",
    titleEn: "Clinical Trial Protocol (Phase II)",
    src: "RU", tgt: "EN",
    status: "done",
    created: "2026-03-04",
    deadline: "2026-04-30",
    segments: [
      seg(1, "Первичная конечная точка исследования — изменение уровня гликированного гемоглобина.",
        "The primary endpoint of the study is the change in glycated haemoglobin level.",
        "confirmed", "GPT_REQUIRED", "high"),
      seg(2, "Все нежелательные явления регистрируются в индивидуальной регистрационной карте.",
        "All adverse events are recorded in the case report form.",
        "confirmed", "EXACT_TM", "low"),
    ],
  };

  const glossary = [
    { src: "ИБС", tgt: "coronary artery disease", cat: "Disease", freq: 142, conf: "high", note: "Ишемическая болезнь сердца. Предпочтительно CAD в US-английском." },
    { src: "фракция выброса", tgt: "ejection fraction", cat: "Cardiology", freq: 96, conf: "high", note: "" },
    { src: "стеноз", tgt: "stenosis", cat: "Anatomy", freq: 88, conf: "high", note: "" },
    { src: "одышка", tgt: "dyspnea", cat: "Symptom", freq: 75, conf: "high", note: "US: dyspnea / UK: dyspnoea" },
    { src: "АД", tgt: "blood pressure", cat: "Vitals", freq: 210, conf: "high", note: "Артериальное давление" },
    { src: "ЧСС", tgt: "heart rate", cat: "Vitals", freq: 198, conf: "high", note: "Частота сердечных сокращений" },
    { src: "стенокардия напряжения", tgt: "exertional angina", cat: "Disease", freq: 54, conf: "high", note: "" },
    { src: "гипертрофия левого желудочка", tgt: "left ventricular hypertrophy", cat: "Cardiology", freq: 41, conf: "medium", note: "Аббревиатура LVH допустима в таблицах." },
    { src: "ацетилсалициловая кислота", tgt: "acetylsalicylic acid", cat: "Dosage", freq: 67, conf: "high", note: "Не переводить как aspirin без согласования." },
    { src: "бисопролол", tgt: "bisoprolol", cat: "Dosage", freq: 38, conf: "high", note: "" },
    { src: "аторвастатин", tgt: "atorvastatin", cat: "Dosage", freq: 35, conf: "high", note: "" },
    { src: "кетоацидоз", tgt: "ketoacidosis", cat: "Disease", freq: 22, conf: "high", note: "" },
    { src: "нежелательное явление", tgt: "adverse event", cat: "Regulatory", freq: 130, conf: "high", note: "" },
    { src: "гликированный гемоглобин", tgt: "glycated haemoglobin", cat: "Lab", freq: 44, conf: "medium", note: "HbA1c в таблицах." },
    { src: "эпикриз", tgt: "discharge summary", cat: "Document", freq: 60, conf: "high", note: "" },
  ];

  const tm = [
    { src: "Выписной эпикриз пациента, находившегося на стационарном лечении в кардиологическом отделении.",
      tgt: "Discharge summary of a patient who received inpatient treatment in the cardiology department.",
      created: "2026-04-02", used: 12, quality: "verified" },
    { src: "Перед началом приёма препарата внимательно прочитайте инструкцию.",
      tgt: "Read this leaflet carefully before you start taking the medicine.",
      created: "2026-02-18", used: 34, quality: "verified" },
    { src: "Все нежелательные явления регистрируются в индивидуальной регистрационной карте.",
      tgt: "All adverse events are recorded in the case report form.",
      created: "2026-03-09", used: 8, quality: "verified" },
    { src: "Объективно: общее состояние удовлетворительное. Кожные покровы обычной окраски.",
      tgt: "Objectively: general condition is satisfactory. Skin is of normal colour.",
      created: "2026-05-01", used: 5, quality: "draft" },
    { src: "Тоны сердца ясные, ритм правильный.",
      tgt: "Heart sounds are clear, rhythm is regular.",
      created: "2026-01-22", used: 19, quality: "verified" },
  ];

  const exportHistory = [
    { file: "epikriz_cardiology_v3.docx", when: "2 часа назад", size: "248 КБ" },
    { file: "epikriz_cardiology_v2.docx", when: "вчера, 16:40", size: "244 КБ" },
    { file: "metformin_leaflet_final.pdf", when: "3 дня назад", size: "1.1 МБ" },
  ];

  window.SEED = {
    projects: [project7, project4, project2],
    glossary,
    tm,
    exportHistory,
    team: [
      { name: "А. Морозова", initials: "АМ", color: "#0066cc", edits: 67 },
      { name: "Dr. Smith", initials: "DS", color: "#7c3aed", edits: 41 },
      { name: "И. Петров", initials: "ИП", color: "#16a34a", edits: 28 },
      { name: "L. Chen", initials: "LC", color: "#d97706", edits: 19 },
      { name: "К. Волков", initials: "КВ", color: "#0891b2", edits: 11 },
    ],
  };

  // ---- TM match scores (MemSource-style) ----
  // 100 exact · 95-99 high fuzzy · 85-94 medium · <85 low · 101 = new/no-match · null = no TM
  const TM_OVERRIDE = {
    7: { 1: 100, 2: null, 3: 87, 4: 99, 5: 92, 6: null, 7: 100, 8: null, 9: 78, 10: null, 11: null, 12: 101, 13: 101, 14: 101, 15: 101 },
    4: { 1: 100, 2: null, 3: 96 },
    2: { 1: null, 2: 100 },
  };
  window.SEED.projects.forEach(p => p.segments.forEach(s => {
    const o = TM_OVERRIDE[p.id];
    s.tmScore = o && (s.id in o) ? o[s.id] : (s.tm ? (s.tm.score || 100) : (s.status === "new" ? 101 : null));
  }));
})();
