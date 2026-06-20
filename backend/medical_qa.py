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
