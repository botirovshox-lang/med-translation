import re
from datetime import datetime


SEVERITY_SCORE = {
    "critical": 50,
    "major": 30,
    "medium": 15,
    "minor": 5,
}

UI_SEVERITY = {
    "critical": "critical",
    "major": "high",
    "medium": "medium",
    "minor": "medium",
}

STYLE_RULES = [
    {
        "bad": "outer circuit",
        "preferred": "outer contour",
        "source_phrase": "контур",
        "issue_type": "terminology",
        "severity": "major",
        "explanation_ru": "В медицинском и рентгенологическом английском 'контур' обычно передается как 'contour', а не 'circuit'.",
    },
    {
        "bad": "bay-like",
        "preferred": "scalloped",
        "source_phrase": "бухтообразный",
        "issue_type": "literal_calque",
        "severity": "major",
        "explanation_ru": "'Bay-like' звучит как буквальная калька; в радиологическом стиле лучше 'scalloped' или 'irregular with recesses'.",
    },
    {
        "bad": "lung root",
        "preferred": "hilar region",
        "source_phrase": "корень легкого",
        "issue_type": "terminology",
        "severity": "major",
        "explanation_ru": "В медицинском английском обычно используют 'hilum' или 'hilar region', а не буквальное 'lung root'.",
    },
    {
        "bad": "enlightenment",
        "preferred": "radiolucency",
        "source_phrase": "просветление",
        "issue_type": "terminology",
        "severity": "major",
        "explanation_ru": "Для рентгенологического 'просветление' обычно подходят 'radiolucency' или 'lucency'.",
    },
    {
        "bad": "decay",
        "preferred": "cavitation",
        "source_phrase": "распад",
        "issue_type": "terminology",
        "severity": "major",
        "explanation_ru": "В медицинском контексте 'распад' часто требует 'cavitation', 'breakdown' или 'destruction', а не буквальное 'decay'.",
    },
    {
        "bad": "hearth",
        "preferred": "focus",
        "source_phrase": "очаг",
        "issue_type": "terminology",
        "severity": "major",
        "explanation_ru": "'Очаг' в медицинском английском обычно 'focus', 'lesion' или 'opacity', не 'hearth'.",
    },
]

PAIR_RULES = [
    {
        "name": "laterality_left",
        "source_terms": ["левый", "левая", "левое", "левой", "слева"],
        "target_terms": ["left"],
        "opposite_terms": ["right"],
        "issue_type": "laterality_shift",
        "label": "left/right",
    },
    {
        "name": "laterality_right",
        "source_terms": ["правый", "правая", "правое", "правой", "справа"],
        "target_terms": ["right"],
        "opposite_terms": ["left"],
        "issue_type": "laterality_shift",
        "label": "left/right",
    },
    {
        "name": "inner",
        "source_terms": ["внутренний", "внутренняя", "внутреннее", "внутренней"],
        "target_terms": ["inner", "internal"],
        "opposite_terms": ["outer", "external"],
        "issue_type": "inner_outer_shift",
        "label": "inner/outer",
    },
    {
        "name": "outer",
        "source_terms": ["наружный", "наружная", "наружное", "наружной", "внешний"],
        "target_terms": ["outer", "external"],
        "opposite_terms": ["inner", "internal"],
        "issue_type": "inner_outer_shift",
        "label": "inner/outer",
    },
    {
        "name": "upper",
        "source_terms": ["верхний", "верхняя", "верхнее", "верхней"],
        "target_terms": ["upper"],
        "opposite_terms": ["lower"],
        "issue_type": "upper_lower_shift",
        "label": "upper/lower",
    },
    {
        "name": "lower",
        "source_terms": ["нижний", "нижняя", "нижнее", "нижней"],
        "target_terms": ["lower"],
        "opposite_terms": ["upper"],
        "issue_type": "upper_lower_shift",
        "label": "upper/lower",
    },
]

NEGATION_RU = ["не", "нет", "без", "отрицает", "исключено", "не выявлено"]
NEGATION_EN = ["no", "not", "without", "denies", "denied", "negative for", "not detected", "not identified"]

GLOSSARY_QA_SKIP_SRC = {"сахар", "нос", "отношение", "первичный"}
GLOSSARY_QA_SKIP_TARGET = {"sugar", "nose", "attitude", "white"}


def enabled_from_env(value):
    return str(value or "1").strip().lower() not in {"0", "false", "no", "off"}


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _term_boundary_pattern(term):
    parts = [re.escape(p) for p in re.split(r"\s+", _norm(term)) if p]
    if not parts:
        return None
    word = r"0-9A-Za-z\u0400-\u04FF"
    return r"(?<![" + word + r"])" + r"\s+".join(parts) + r"(?![" + word + r"])"


def _has_exact_term(text, term):
    pattern = _term_boundary_pattern(term)
    return bool(pattern and re.search(pattern, _norm(text), flags=re.IGNORECASE))


def _target_variants(term):
    return [p.strip() for p in re.split(r"\s*(?:;|/|,|\bor\b)\s*", term or "", flags=re.IGNORECASE) if p.strip()]


def _has_target_variant(text, term):
    return any(_has_exact_term(text, v) for v in _target_variants(term))


def _should_validate_glossary_term(src, tgt):
    src_l = _norm(src)
    variants = [_norm(v) for v in _target_variants(tgt)]
    if src_l in GLOSSARY_QA_SKIP_SRC:
        return False
    if any(v in GLOSSARY_QA_SKIP_TARGET for v in variants):
        return False
    return True


def _contains_any(text, terms):
    return any(_has_exact_term(text, term) for term in terms)


def _extract_numbers(text):
    return re.findall(r"\d+(?:[.,]\d+)?", text or "")


def _extract_units(text):
    # Unit checks are meaningful only when the unit is attached to a number.
    # This avoids false positives from abbreviations like "д.м.н.".
    text_l = (text or "").lower()
    num = r"\d+(?:[.,]\d+)?"
    en_pat = re.compile(num + r"\s*(mg|mcg|kg|ml|mm\s*hg|mmhg|mm|cm|bpm|iu|u/l|mmol/l|%)\b")
    ru_pat = re.compile(num + r"\s*(мг|мкг|кг|мл|мм\s*рт\.?\s*ст\.?|мм|см|%)\b", re.IGNORECASE)
    units = [re.sub(r"\s+", " ", m.group(1)) for m in en_pat.finditer(text_l)]
    units += [re.sub(r"\s+", " ", m.group(1)) for m in ru_pat.finditer(text_l)]
    return sorted(units)


def _make_issue(issue_type, severity, explanation_ru, source_fragment="", target_fragment="", bad_fragment="", suggested_fragment="", detected_by="deterministic_validator"):
    return {
        "type": issue_type,
        "severity": severity,
        "source_fragment": source_fragment,
        "target_fragment": target_fragment,
        "bad_fragment": bad_fragment,
        "suggested_fragment": suggested_fragment,
        "explanation_ru": explanation_ru,
        "detected_by": detected_by,
        "engine": "deterministic",
        "status": "open",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


def build_context_package(source_ru, prev_ru="", next_ru="", glossary_matches=None, tm_match=None, domain="medical", text_type="clinical_segment"):
    glossary_matches = glossary_matches or []
    return {
        "source_ru": source_ru or "",
        "context_before": prev_ru or "",
        "context_after": next_ru or "",
        "domain": domain,
        "text_type": text_type,
        "approved_terms": [
            {
                "source": g.get("src") or g.get("source") or "",
                "target": g.get("tgt") or g.get("target") or "",
                "category": g.get("cat") or g.get("category") or "",
                "matched_form": g.get("_form") or g.get("src") or "",
            }
            for g in glossary_matches[:20]
        ],
        "tm_examples": [tm_match] if tm_match else [],
        "forbidden_terms": [{"bad": r["bad"], "preferred": r["preferred"]} for r in STYLE_RULES],
        "style_rules": [
            "Back-check checks semantic preservation only.",
            "Medical Style QA must catch literal calques and weak medical collocations.",
            "Use contour, not circuit, for radiology contour descriptions.",
            "Use scalloped or irregular with recesses, not bay-like, for cavity-wall contour.",
        ],
        "known_risks": ["numbers", "units", "negation", "left/right", "upper/lower", "inner/outer", "literal_calques"],
    }


def deterministic_issues(source_ru, translated_en, glossary_matches=None):
    issues = []
    source = source_ru or ""
    target = translated_en or ""
    target_l = _norm(target)

    src_nums = sorted(_extract_numbers(source))
    tgt_nums = sorted(_extract_numbers(target))
    if src_nums and src_nums != tgt_nums:
        issues.append(_make_issue(
            "number_unit_dosage_mismatch",
            "critical",
            f"Числа в источнике и переводе не совпадают: source={src_nums}, target={tgt_nums}.",
            source_fragment=", ".join(src_nums),
            target_fragment=", ".join(tgt_nums),
        ))

    src_units = _extract_units(source)
    tgt_units = _extract_units(target)
    if src_units and not tgt_units:
        issues.append(_make_issue(
            "unit_mismatch",
            "major",
            "В источнике есть единицы измерения, но в переводе они не обнаружены.",
            source_fragment=", ".join(src_units),
        ))

    src_has_neg = _contains_any(source, NEGATION_RU)
    tgt_has_neg = _contains_any(target, NEGATION_EN)
    if src_has_neg != tgt_has_neg:
        issues.append(_make_issue(
            "negation_shift",
            "critical",
            "Отрицание изменилось или потерялось между источником и переводом.",
        ))

    for rule in PAIR_RULES:
        if not _contains_any(source, rule["source_terms"]):
            continue
        has_expected = _contains_any(target, rule["target_terms"])
        has_opposite = _contains_any(target, rule["opposite_terms"])
        if not has_expected:
            issues.append(_make_issue(
                rule["issue_type"],
                "critical" if has_opposite else "major",
                f"Проверьте {rule['label']}: в источнике есть '{rule['name']}', но перевод не сохраняет это явно.",
                source_fragment=", ".join(rule["source_terms"][:2]),
                target_fragment=", ".join(rule["target_terms"]),
            ))

    for style_rule in STYLE_RULES:
        bad = style_rule["bad"]
        if bad in target_l:
            issues.append(_make_issue(
                style_rule["issue_type"],
                style_rule["severity"],
                style_rule["explanation_ru"],
                source_fragment=style_rule["source_phrase"],
                target_fragment=bad,
                bad_fragment=bad,
                suggested_fragment=style_rule["preferred"],
                detected_by="medical_style_qa",
            ))

    for g in glossary_matches or []:
        src = (g.get("src") or g.get("source") or "").strip()
        tgt = (g.get("tgt") or g.get("target") or "").strip()
        if not src or not tgt:
            continue
        if not _should_validate_glossary_term(src, tgt):
            continue
        if _has_exact_term(source, src) and not _has_target_variant(target, tgt):
            issues.append(_make_issue(
                "glossary_violation",
                "medium",
                f"В источнике найден термин '{src}', но утвержденный вариант '{tgt}' не найден в переводе.",
                source_fragment=src,
                suggested_fragment=tgt,
                detected_by="glossary_validator",
            ))

    return issues


def _corrected_translation(translated_en, issues):
    corrected = translated_en or ""
    for issue in issues:
        bad = issue.get("bad_fragment") or ""
        good = issue.get("suggested_fragment") or ""
        if bad and good:
            corrected = re.sub(re.escape(bad), good, corrected, flags=re.IGNORECASE)
    if "outer contour of the cavity wall" in corrected.lower() and "scalloped" in corrected.lower():
        corrected = re.sub(
            r"the inner is uneven,\s*scalloped",
            "while the inner contour is irregular and scalloped",
            corrected,
            flags=re.IGNORECASE,
        )
    return corrected


def _risk_from_issues(issues, semantic_equivalence=True):
    score = 0
    forced_red_types = {
        "number_unit_dosage_mismatch",
        "unit_mismatch",
        "negation_shift",
        "laterality_shift",
        "upper_lower_shift",
        "inner_outer_shift",
        "anatomy_shift",
        "diagnosis_symptom_finding_changed",
        "uncertainty_changed",
    }
    forced_red = False
    for issue in issues:
        severity = issue.get("severity", "minor")
        score += SEVERITY_SCORE.get(severity, 5)
        if issue.get("type") in forced_red_types or severity == "critical":
            forced_red = True

    if not semantic_equivalence:
        score += 30

    style_only_types = {"literal_calque", "terminology", "forbidden_term", "weak_collocation", "glossary_violation"}
    style_only = bool(issues) and all(i.get("type") in style_only_types for i in issues)
    if forced_red or score >= 50:
        color = "yellow" if style_only and not forced_red else "red"
    elif score >= 20:
        color = "yellow"
    else:
        color = "green"

    return {
        "risk_score": min(score, 100),
        "risk_color": color,
        "human_review_required": color == "red",
        "auto_revision_allowed": color == "yellow",
    }


def _to_ui_issue(issue):
    fragment = issue.get("bad_fragment") or issue.get("target_fragment") or issue.get("source_fragment") or ""
    suggestion = issue.get("suggested_fragment") or ""
    msg = issue.get("explanation_ru") or "Обнаружена QA-проблема."
    if fragment:
        msg += f" Фрагмент: {fragment}."
    if suggestion:
        msg += f" Рекомендация: {suggestion}."
    return {
        "sev": UI_SEVERITY.get(issue.get("severity", "medium"), "medium"),
        "type": issue.get("type", "medical_qa"),
        "msg": msg,
    }


def _term_candidates(issues, source_ru):
    candidates = []
    eligible = {"literal_calque", "terminology", "forbidden_term", "weak_collocation", "glossary_violation"}
    for issue in issues:
        if issue.get("type") not in eligible:
            continue
        bad = issue.get("bad_fragment") or issue.get("target_fragment") or ""
        preferred = issue.get("suggested_fragment") or ""
        if not bad and not preferred:
            continue
        candidates.append({
            "source_pattern": issue.get("source_fragment") or "",
            "source_phrase": issue.get("source_fragment") or "",
            "bad_en": bad,
            "preferred_en": preferred,
            "allowed_en": [preferred] if preferred else [],
            "forbidden_en": [bad] if bad else [],
            "domain": "medical",
            "trigger_words": [],
            "confidence": 0.4,
            "occurrences": 1,
            "source_excerpt": source_ru or "",
            "source_issue_type": issue.get("type"),
            "status": "pending",
            "created_at": datetime.utcnow().isoformat() + "Z",
        })
    return candidates


def run_medical_qa(source_ru, translated_en, backtranslated_ru="", glossary_matches=None, tm_match=None, engine_qa="deterministic+mvp"):
    context_package = build_context_package(
        source_ru,
        glossary_matches=glossary_matches or [],
        tm_match=tm_match,
    )
    issues = deterministic_issues(source_ru, translated_en, glossary_matches=glossary_matches)
    semantic_equivalence = not any(i.get("type") in {
        "number_unit_dosage_mismatch",
        "negation_shift",
        "laterality_shift",
        "upper_lower_shift",
        "inner_outer_shift",
    } for i in issues)
    risk = _risk_from_issues(issues, semantic_equivalence=semantic_equivalence)
    corrected = _corrected_translation(translated_en, issues)
    style_issues = [i for i in issues if i.get("detected_by") == "medical_style_qa" or i.get("type") in {"glossary_violation"}]
    validator_issues = [i for i in issues if i not in style_issues]

    result = {
        "context_package": context_package,
        "translator": {
            "translated_text": translated_en or "",
            "used_glossary_terms": [],
            "uncertainty_flags": [],
            "translator_notes": [],
        },
        "literal_backcheck": {
            "backtranslated_ru": backtranslated_ru or "",
            "engine": "openai/google" if backtranslated_ru else "not_run",
        },
        "backcheck_comparator": {
            "semantic_equivalence": semantic_equivalence,
            "risk_score_addition": 0 if semantic_equivalence else 30,
            "issues": [i for i in issues if i.get("type") in {
                "number_unit_dosage_mismatch",
                "negation_shift",
                "laterality_shift",
                "upper_lower_shift",
                "inner_outer_shift",
            }],
        },
        "medical_style_qa": {
            "medical_style_ok": len(style_issues) == 0,
            "risk_score_addition": sum(SEVERITY_SCORE.get(i.get("severity", "minor"), 5) for i in style_issues),
            "issues": style_issues,
            "corrected_translation": corrected if corrected != translated_en else "",
        },
        "deterministic_validators": {
            "passed": len(validator_issues) == 0,
            "issues": validator_issues,
        },
        "issues": issues,
        "qa_issues": issues,
        "ui_issues": [_to_ui_issue(i) for i in issues],
        "term_candidates": _term_candidates(issues, source_ru),
        "risk_score": risk["risk_score"],
        "risk_color": risk["risk_color"],
        "routing": {
            **risk,
            "max_revision_attempts": 2,
            "route": "human_review" if risk["risk_color"] == "red" else "auto_revise" if risk["risk_color"] == "yellow" else "accept_or_random_audit",
        },
        "engine_qa": engine_qa,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    return result


# ─────────────────────────────────────────────────────────────────────
# Back-check: сравнение оригинала с обратным переводом
#
# Принципиальное отличие от deterministic_issues: там сравниваются РАЗНЫЕ языки
# (RU против EN), здесь — ОДИН И ТОТ ЖЕ язык (оригинал RU против обратного
# перевода RU). Внутри одного языка проверки на порядок надёжнее: числа обязаны
# совпадать буквально, отрицания сравнимы напрямую, термины — по основе слова.
#
# Строковую похожесть как главную метрику брать нельзя: «лимфаденит» и
# «аденолимфит» отличаются на любой edit-distance процентов на двадцать, то есть
# именно тот случай, ради которого всё затевалось, она бы уверенно пропустила.
# Поэтому непрерывная база (сколько содержательных слов пережило круг) отвечает
# только за оттенки, а подмены смысла ловятся жёсткими штрафами.
# ─────────────────────────────────────────────────────────────────────

from collections import Counter as _Counter

BACKCHECK_BANDS = [
    {"key": "eq100", "min": 100, "max": 100, "label": "100%",   "note": "Дословное совпадение",       "color": "green"},
    {"key": "b98",   "min": 98,  "max": 99,  "label": "98-99%", "note": "Почти дословно",             "color": "green"},
    {"key": "b95",   "min": 95,  "max": 97,  "label": "95-97%", "note": "Незначительные расхождения", "color": "green"},
    {"key": "b90",   "min": 90,  "max": 94,  "label": "90-94%", "note": "Мелкие расхождения",         "color": "yellow"},
    {"key": "b85",   "min": 85,  "max": 89,  "label": "85-89%", "note": "Заметные расхождения",       "color": "yellow"},
    {"key": "b80",   "min": 80,  "max": 84,  "label": "80-84%", "note": "Требует просмотра",          "color": "orange"},
    {"key": "b71",   "min": 71,  "max": 79,  "label": "71-79%", "note": "Смысл поплыл",               "color": "orange"},
    {"key": "b61",   "min": 61,  "max": 70,  "label": "61-70%", "note": "Существенные расхождения",   "color": "red"},
    {"key": "b50",   "min": 50,  "max": 60,  "label": "50-60%", "note": "Смысл разошёлся",            "color": "red"},
    {"key": "low",   "min": 0,   "max": 49,  "label": "< 50%",  "note": "Совпадения почти нет",       "color": "red"},
]

# Штрафы вынесены константами: после первого прохода по проекту их и границы
# полос имеет смысл откалибровать на реальном распределении.
BACKCHECK_PENALTY = {
    "number_mismatch": 40,
    "unit_mismatch": 20,
    "negation_shift": 40,
    "pair_shift": 30,
    "term_lost": 25,
    "term_lost_cap": 50,
}

# Кривая калибровки базы. Чистая доля совпавших основ занижает оценку: живой
# обратный перевод почти всегда перефразирует, и «пациенту назначили» против
# «больному назначен» давало бы 75% при полностью целом смысле. Корень поднимает
# такие случаи в район 85-90, оставляя низ шкалы жёстким. Значение подлежит
# калибровке на реальном распределении после первого полного прохода.
BACKCHECK_RECALL_CURVE = 0.5

# Роль эмбеддингов ограничена намеренно. Замер на реальных парах (text-embedding-3-small):
#   синоним  «Больному назначен» / «Пациенту назначили»   cos 0.677
#   подмена  «лимфаденит» / «аденолимфит»                 cos 0.842
#   подмена  «левое лёгкое» / «правое лёгкое»             cos 0.809
#   чужое    «микроскопия мокроты» / «погода хорошая»     cos 0.145
# То есть опасная подмена термина получает косинус ВЫШЕ, чем безобидная
# перефразировка: как метрика смысловой близости в средней зоне эмбеддинги здесь
# бесполезны и даже вредны — они бы подняли балл именно тому случаю, ради которого
# всё делалось. Поэтому используем их только по краям, где они надёжны:
#   очень высокий косинус при отсутствии жёстких находок — тексты почти идентичны;
#   очень низкий — обратный перевод просто про другое.
# Среднюю зону разбирает LLM-судья, а не эмбеддинги.
BACKCHECK_SEM_HIGH = 0.95
BACKCHECK_SEM_ALIEN = 0.50
BACKCHECK_SEM_HIGH_FLOOR = 0.95   # доля от 100 баллов
BACKCHECK_SEM_ALIEN_CAP = 0.40

# Потолки и полы, которые ставит вердикт судьи.
JUDGE_CAP = {"critical": 45, "major": 70, "minor": None, "none": None}
JUDGE_FLOOR_NONE = 95

RU_STOPWORDS = {
    "и", "или", "но", "а", "же", "ли", "не", "нет", "да", "в", "во", "на", "с", "со", "к", "ко",
    "по", "за", "из", "от", "до", "для", "при", "об", "о", "у", "то", "это", "этот", "эта", "эти",
    "тот", "та", "те", "как", "что", "чем", "чтобы", "если", "так", "также", "тоже", "уже", "ещё",
    "еще", "был", "была", "было", "были", "быть", "есть", "их", "его", "её", "ее", "они", "она",
    "он", "оно", "мы", "вы", "я", "все", "всех", "всего", "может", "можно", "более", "менее",
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "is", "are", "was", "were",
}

_PAIR_OPPOSITE = {
    "laterality_left": "laterality_right", "laterality_right": "laterality_left",
    "inner": "outer", "outer": "inner",
    "upper": "lower", "lower": "upper",
}
_PAIR_BY_NAME = {r["name"]: r for r in PAIR_RULES}


def band_of(score):
    if score is None:
        return None
    for b in BACKCHECK_BANDS:
        if b["min"] <= score <= b["max"]:
            return b["key"]
    return "low"


def _stems(text):
    """Грубая нормализация под русскую морфологию: обрезаем слово до основы.
    Полноценный морфоанализатор здесь не нужен — для сравнения двух русских
    текстов между собой достаточно совпадения основ."""
    words = re.findall(r"[а-яёa-z0-9]+", _norm(text))
    out = []
    for w in words:
        if len(w) < 3 or w in RU_STOPWORDS:
            continue
        out.append(w[:6] if len(w) > 6 else w)
    return out


def _content_recall(source_ru, back_ru):
    """Доля содержательных слов оригинала, переживших круг.
    Именно recall, а не F1: лишние слова в обратном переводе — не ошибка,
    ошибка — когда из оригинала что-то пропало."""
    src = _Counter(_stems(source_ru))
    if not src:
        return 1.0
    bak = _Counter(_stems(back_ru))
    covered = sum(min(cnt, bak.get(w, 0)) for w, cnt in src.items())
    return covered / sum(src.values())


def _term_survived(term, back_stems):
    ts = _stems(term)
    return bool(ts) and all(t in back_stems for t in ts)


def backcheck_issues(source_ru, back_ru, glossary_matches=None):
    """Расхождения между оригиналом и обратным переводом."""
    issues = []
    source = source_ru or ""
    back = back_ru or ""

    src_nums = sorted(_extract_numbers(source))
    back_nums = sorted(_extract_numbers(back))
    if src_nums != back_nums:
        issues.append(_make_issue(
            "backcheck_number_mismatch", "critical",
            "Числа не пережили обратный перевод: в оригинале {0}, в обратном переводе {1}.".format(
                src_nums or "—", back_nums or "—"),
            source_fragment=", ".join(src_nums), target_fragment=", ".join(back_nums),
            detected_by="backcheck_comparator"))

    src_units = _extract_units(source)
    back_units = _extract_units(back)
    if src_units != back_units:
        issues.append(_make_issue(
            "backcheck_unit_mismatch", "major",
            "Единицы измерения разошлись: в оригинале {0}, в обратном переводе {1}.".format(
                src_units or "—", back_units or "—"),
            source_fragment=", ".join(src_units), target_fragment=", ".join(back_units),
            detected_by="backcheck_comparator"))

    if _contains_any(source, NEGATION_RU) != _contains_any(back, NEGATION_RU):
        issues.append(_make_issue(
            "backcheck_negation_shift", "critical",
            "Отрицание изменилось при обратном переводе — утверждение и отрицание "
            "не должны меняться местами.",
            detected_by="backcheck_comparator"))

    for rule in PAIR_RULES:
        if not _contains_any(source, rule["source_terms"]):
            continue
        opposite = _PAIR_BY_NAME.get(_PAIR_OPPOSITE.get(rule["name"], ""))
        if not opposite:
            continue
        # Ошибка — не отсутствие слова (это может быть перефразировка),
        # а именно подмена на противоположное.
        if _contains_any(back, opposite["source_terms"]) and not _contains_any(back, rule["source_terms"]):
            issues.append(_make_issue(
                "backcheck_pair_shift", "critical",
                "Подмена на противоположное ({0}) при обратном переводе.".format(rule["label"]),
                source_fragment=rule["label"], detected_by="backcheck_comparator"))

    back_stems = set(_stems(back))
    lost = []
    for hit in (glossary_matches or []):
        term = hit.get("_form") or hit.get("src") or ""
        if not term or not _has_exact_term(source, term):
            continue
        if not _term_survived(term, back_stems):
            lost.append(term)
    for term in lost:
        issues.append(_make_issue(
            "backcheck_term_lost", "major",
            "Термин «{0}» не пережил обратный перевод — в обратном тексте его нет. "
            "Возможна подмена понятия.".format(term),
            source_fragment=term, detected_by="backcheck_comparator"))

    return issues, lost


def _hard_issue(issues):
    hard = {"backcheck_number_mismatch", "backcheck_unit_mismatch",
            "backcheck_negation_shift", "backcheck_pair_shift", "backcheck_term_lost"}
    return any(i.get("type") in hard for i in (issues or []))


def apply_judge_verdict(result, verdict):
    """Вердикт судьи корректирует балл: подмена понятия роняет его вниз,
    подтверждённая эквивалентность — поднимает. Судья не отменяет
    детерминированные находки, он только двигает итог в их рамках."""
    if not result or not verdict or result.get("score") is None:
        return result
    sev = (verdict.get("severity") or "").lower()
    if not verdict.get("same_meaning", True) and sev not in ("critical", "major"):
        sev = "major"
    cap = JUDGE_CAP.get(sev)
    score = result["score"]
    if cap is not None and score > cap:
        score = cap
        result["reasons"] = list(result.get("reasons", [])) + [
            "судья: " + (verdict.get("comment") or "смысл расходится")]
    elif sev == "none" and score < JUDGE_FLOOR_NONE and not result.get("terms_lost"):
        # Поднимаем только когда жёстких находок нет: иначе судья затрёт
        # расхождение чисел или отрицания, которое видно объективно.
        hard = {"backcheck_number_mismatch", "backcheck_unit_mismatch",
                "backcheck_negation_shift", "backcheck_pair_shift"}
        if not any(i.get("type") in hard for i in result.get("issues", [])):
            score = JUDGE_FLOOR_NONE
            result["reasons"] = ["судья: смысл эквивалентен, отличается формулировка"]
    result["score"] = int(score)
    result["band"] = band_of(result["score"])
    result["judge"] = {
        "same_meaning": verdict.get("same_meaning"),
        "severity": sev,
        "divergences": verdict.get("divergences", []),
        "comment": verdict.get("comment", ""),
        "model": verdict.get("model", ""),
    }
    return result


def run_backcheck(source_ru, back_ru, glossary_matches=None, semantic=None, semantic_fn=None):
    """Оценка соответствия обратного перевода оригиналу: 0-100 и причины.

    semantic    — косинус эмбеддингов оригинала и обратного перевода, если посчитан.
    semantic_fn — ленивый вариант: функция без аргументов, которую зовут ТОЛЬКО
                  если косинус реально повлияет на результат. При жёсткой находке
                  (числа, единицы, отрицание, подмена) он игнорируется — значит и
                  платить за эмбеддинги незачем.
    Работает только по краям шкалы (см. комментарий к BACKCHECK_SEM_*): в средней
    зоне косинус не отличает синонимию от подмены понятия, там решает судья."""
    if not (back_ru or "").strip():
        return {"score": None, "band": None, "hard": False, "recall": None, "issues": [],
                "terms_lost": [], "reasons": ["Обратный перевод не выполнен"]}

    issues, lost = backcheck_issues(source_ru, back_ru, glossary_matches)
    hard = _hard_issue(issues)
    recall = _content_recall(source_ru, back_ru)
    base = recall ** BACKCHECK_RECALL_CURVE
    sem_note = None
    if semantic is None and semantic_fn is not None and not hard:
        semantic = semantic_fn()
    if semantic is not None and not hard:
        # Тексты почти идентичны по смыслу и жёстких находок нет — поднимаем базу
        if semantic >= BACKCHECK_SEM_HIGH:
            base = max(base, BACKCHECK_SEM_HIGH_FLOOR)
        # Обратный перевод просто про другое — этого не спасёт никакая лексика
        elif semantic < BACKCHECK_SEM_ALIEN:
            base = min(base, BACKCHECK_SEM_ALIEN_CAP)
            sem_note = "обратный перевод про другое"
    score = 100.0 * base

    penalty = 0
    term_penalty = 0
    reasons = []
    for i in issues:
        t = i.get("type")
        if t == "backcheck_number_mismatch":
            penalty += BACKCHECK_PENALTY["number_mismatch"]
            reasons.append("расхождение чисел")
        elif t == "backcheck_unit_mismatch":
            penalty += BACKCHECK_PENALTY["unit_mismatch"]
            reasons.append("расхождение единиц")
        elif t == "backcheck_negation_shift":
            penalty += BACKCHECK_PENALTY["negation_shift"]
            reasons.append("инверсия отрицания")
        elif t == "backcheck_pair_shift":
            penalty += BACKCHECK_PENALTY["pair_shift"]
            reasons.append("подмена на противоположное")
        elif t == "backcheck_term_lost":
            term_penalty += BACKCHECK_PENALTY["term_lost"]
    if term_penalty:
        term_penalty = min(term_penalty, BACKCHECK_PENALTY["term_lost_cap"])
        penalty += term_penalty
        reasons.append("потерян термин: " + ", ".join(lost[:3]) + ("…" if len(lost) > 3 else ""))

    if sem_note:
        reasons.append(sem_note)
    score = int(round(max(0.0, min(100.0, score - penalty))))
    if not reasons and score < 100:
        reasons.append("часть текста не совпала дословно")

    return {
        "score": score,
        "band": band_of(score),
        "hard": hard,
        "recall": round(recall, 3),
        "semantic": round(semantic, 3) if semantic is not None else None,
        "issues": issues,
        "terms_lost": lost,
        "reasons": reasons,
    }
