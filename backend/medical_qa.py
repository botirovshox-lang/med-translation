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

# ─── Реестр правил: предметная область × языковая пара ───────────────
# Раньше все правила лежали одним списком и молча предполагали медицину и
# пару RU→EN. В юридическом переводе на немецкий «bay-like → scalloped» —
# мусор, а «левый → left» просто не сработает: у правил русские ключи.
#
# Теперь набор собирается из двух слоёв:
#   * языконезависимое — числа, единицы, соответствие глоссарию: работает всегда;
#   * правила пары языков и области — подключаются, только если проект совпал
#     и по языкам, и по области. Не совпал — проверка молчит, а не врёт.
#
# Добавить область или пару языков = добавить запись здесь. Больше нигде.

PAIRS_ORIENTATION_RU_EN = [r for r in PAIR_RULES if r["issue_type"] == "laterality_shift"]
PAIRS_ANATOMY_RU_EN = [r for r in PAIR_RULES if r["issue_type"] != "laterality_shift"]

NEGATION_MARKERS = {
    "RU": ["не", "нет", "без", "отрицает", "исключено", "не выявлено"],
    "EN": ["no", "not", "without", "denies", "denied", "negative for",
           "not detected", "not identified"],
}

# Ключ — (область, язык оригинала, язык перевода)
DOMAIN_RULES = {
    ("medical", "RU", "EN"): {
        "pairs": PAIRS_ORIENTATION_RU_EN + PAIRS_ANATOMY_RU_EN,
        "style": STYLE_RULES,
        "skip_src": {"сахар", "нос", "отношение", "первичный"},
        "skip_tgt": {"sugar", "nose", "attitude", "white"},
    },
    ("pharma", "RU", "EN"): {
        "pairs": PAIRS_ORIENTATION_RU_EN,
        "style": [],
        "skip_src": {"сахар", "отношение"},
        "skip_tgt": {"sugar", "attitude"},
    },
    ("technical", "RU", "EN"): {
        # Лево/право и верх/низ важны в чертежах и инструкциях ровно так же
        "pairs": PAIRS_ORIENTATION_RU_EN + [r for r in PAIRS_ANATOMY_RU_EN
                                            if r["issue_type"] == "upper_lower_shift"],
        "style": [], "skip_src": set(), "skip_tgt": set(),
    },
}

# Область без своей записи получает только языконезависимые проверки:
# лучше молчать, чем выдумывать правила, которых для этой пары никто не писал.
EMPTY_RULES = {"pairs": [], "style": [], "skip_src": set(), "skip_tgt": set()}


def rules_for(domain=None, src_lang="RU", tgt_lang="EN"):
    key = ((domain or "medical").lower(), (src_lang or "").upper(), (tgt_lang or "").upper())
    return DOMAIN_RULES.get(key, EMPTY_RULES)


def negation_markers(lang):
    return NEGATION_MARKERS.get((lang or "").upper(), [])


NEGATION_RU = NEGATION_MARKERS["RU"]      # исторические имена: на них ссылается legacy-код
NEGATION_EN = NEGATION_MARKERS["EN"]

GLOSSARY_QA_SKIP_SRC = DOMAIN_RULES[("medical", "RU", "EN")]["skip_src"]
GLOSSARY_QA_SKIP_TARGET = DOMAIN_RULES[("medical", "RU", "EN")]["skip_tgt"]


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


def _should_validate_glossary_term(src, tgt, skip_src=None, skip_tgt=None):
    # Скип-списки приходят из DOMAIN_RULES области и пары языков проекта.
    # Раньше аргументы игнорировались, и юридический RU→DE проект молча
    # проверялся по медицинским RU→EN спискам. None — legacy-вызов без
    # области: для него прежнее поведение сохраняется.
    skip_src = GLOSSARY_QA_SKIP_SRC if skip_src is None else skip_src
    skip_tgt = GLOSSARY_QA_SKIP_TARGET if skip_tgt is None else skip_tgt
    src_l = _norm(src)
    variants = [_norm(v) for v in _target_variants(tgt)]
    if src_l in skip_src:
        return False
    if any(v in skip_tgt for v in variants):
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


def build_context_package(source_ru, prev_ru="", next_ru="", glossary_matches=None, tm_match=None, domain="medical", text_type="clinical_segment", src_lang="RU", tgt_lang="EN"):
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
        # Пара языков — проекта, а не зашитая RU→EN: правила стиля чужой пары
        # в списке запрещённых терминов были бы мусором.
        "forbidden_terms": [{"bad": r["bad"], "preferred": r["preferred"]}
                            for r in rules_for(domain, src_lang, tgt_lang)["style"]],
        "style_rules": [
            "Back-check checks semantic preservation only.",
            "Medical Style QA must catch literal calques and weak medical collocations.",
            "Use contour, not circuit, for radiology contour descriptions.",
            "Use scalloped or irregular with recesses, not bay-like, for cavity-wall contour.",
        ],
        "known_risks": ["numbers", "units", "negation", "left/right", "upper/lower", "inner/outer", "literal_calques"],
    }


def deterministic_issues(source_ru, translated_en, glossary_matches=None,
                        domain=None, src_lang="RU", tgt_lang="EN"):
    """Проверки правилами. Числа, единицы и соответствие глоссарию работают для
    любой пары языков; правила направлений и стиля — только там, где они описаны
    для этой области и этой пары (см. DOMAIN_RULES)."""
    rules = rules_for(domain, src_lang, tgt_lang)
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

    src_neg, tgt_neg = negation_markers(src_lang), negation_markers(tgt_lang)
    src_has_neg = _contains_any(source, src_neg) if src_neg else None
    tgt_has_neg = _contains_any(target, tgt_neg) if tgt_neg else None
    # Нет списка маркеров для языка — молчим: выдуманное «отрицание потерялось»
    # хуже отсутствующей проверки.
    if src_neg and tgt_neg and src_has_neg != tgt_has_neg:
        issues.append(_make_issue(
            "negation_shift",
            "critical",
            "Отрицание изменилось или потерялось между источником и переводом.",
        ))

    for rule in rules["pairs"]:
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

    for style_rule in rules["style"]:
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
        if not _should_validate_glossary_term(src, tgt, rules["skip_src"], rules["skip_tgt"]):
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


def _term_candidates(issues, source_ru, domain=None):
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
            # Область — из проекта: кандидат юридического проекта не должен
            # помечаться медициной только потому, что так начинался сервис.
            "domain": domain or "medical",
            "trigger_words": [],
            "confidence": 0.4,
            "occurrences": 1,
            "source_excerpt": source_ru or "",
            "source_issue_type": issue.get("type"),
            "status": "pending",
            "created_at": datetime.utcnow().isoformat() + "Z",
        })
    return candidates


def run_medical_qa(source_ru, translated_en, backtranslated_ru="", glossary_matches=None,
                   tm_match=None, engine_qa="deterministic+mvp", domain=None,
                   src_lang="RU", tgt_lang="EN"):
    context_package = build_context_package(
        source_ru,
        glossary_matches=glossary_matches or [],
        tm_match=tm_match,
        domain=domain or "medical",
        src_lang=src_lang,
        tgt_lang=tgt_lang,
    )
    issues = deterministic_issues(source_ru, translated_en, glossary_matches=glossary_matches,
                                  domain=domain, src_lang=src_lang, tgt_lang=tgt_lang)
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
        "term_candidates": _term_candidates(issues, source_ru, domain or "medical"),
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

# Границы откалиброваны на первом полном проходе боевого проекта (2711
# сегментов) — ровно так, как обещал прежний комментарий к BACKCHECK_PENALTY.
#
# Читать их надо через базу балла: score = 100 * recall^0.5, то есть 95 ⇔
# пережило 90% содержательных слов, 90 ⇔ 81%, 80 ⇔ 64%, 71 ⇔ 50%, 61 ⇔ 37%.
# Прежние границы называли «Смысл поплыл» уже 71-79, то есть половину уцелевших
# слов, — а живой обратный перевод ВСЕГДА перефразирует, и recall 0.6-0.8
# у ВЕРНОГО перевода это норма. Под тревожные подписи попадало 22% проекта,
# где разбираться не в чем; теперь туда попадает 9%.
#
# Границы посажены на решения, которые система принимает по этому же числу, —
# иначе полоса говорила бы одно, а порог делал другое:
#   100         дословно;
#   98-99       выше JUDGE_ZONE: спорить не о чем, судью не зовут;
#   95-97       низ = JUDGE_FLOOR_NONE, куда судья поднимает балл словами
#               «смысл эквивалентен», верх = JUDGE_ZONE;
#   90-94       низ = backcheck_min: ниже сегмент не годится в доноры
#               глоссария (AUTO_APPROVE_DEFAULT). Полоса и порог совпали
#               намеренно, но отвечают они на РАЗНЫЕ вопросы: полоса — «цел
#               ли смысл», порог — «можно ли этим учить глоссарий», и второй
#               строже первого по построению;
#   71-79       половина слов сменила форму — стоит взглянуть;
#   61-70       верх = JUDGE_CAP["major"]: сюда судья опускает балл, сказав
#               «смысл расходится». Такой вердикт обязан читаться красным;
#   50-60, 40-49  внутри — JUDGE_CAP["critical"] (45) и потолок «обратный
#               перевод про другое» (BACKCHECK_SEM_ALIEN_CAP, 40);
#   < 40        совпадения почти нет.
#
# Ключи переименованы под настоящие границы: прежние (b50 = 50-60, b85 = 85-89)
# после сдвига называли бы не свои числа, а следующий, кто напишет по ним
# фильтр, получил бы не то. Фронтенд читает min/max, ключ идёт React-ключом.
# ЕДИНСТВЕННАЯ копия этого списка на фронтенде — BC_BANDS_FALLBACK в ui.jsx,
# и она обязана совпадать: до прихода /api/models красят по ней.
# «orange» здесь не используется: bcBandColor красит его тем же цветом, что
# и «yellow», то есть полоса выглядела бы предупреждением, а не тревогой.
BACKCHECK_BANDS = [
    {"key": "b100", "min": 100, "max": 100, "label": "100%",   "note": "Дословное совпадение",       "color": "green"},
    {"key": "b98",  "min": 98,  "max": 99,  "label": "98-99%", "note": "Почти дословно",             "color": "green"},
    {"key": "b95",  "min": 95,  "max": 97,  "label": "95-97%", "note": "Незначительные расхождения", "color": "green"},
    {"key": "b90",  "min": 90,  "max": 94,  "label": "90-94%", "note": "Обычная перефразировка",     "color": "green"},
    {"key": "b80",  "min": 80,  "max": 89,  "label": "80-89%", "note": "Свободная перефразировка",   "color": "green"},
    {"key": "b71",  "min": 71,  "max": 79,  "label": "71-79%", "note": "Стоит взглянуть",            "color": "yellow"},
    {"key": "b61",  "min": 61,  "max": 70,  "label": "61-70%", "note": "Смысл расходится",           "color": "red"},
    {"key": "b50",  "min": 50,  "max": 60,  "label": "50-60%", "note": "Существенные расхождения",   "color": "red"},
    {"key": "b40",  "min": 40,  "max": 49,  "label": "40-49%", "note": "Смысл разошёлся",            "color": "red"},
    {"key": "low",  "min": 0,   "max": 39,  "label": "< 40%",  "note": "Совпадения почти нет",       "color": "red"},
]

# Штрафы вынесены константами: после первого прохода по проекту их и границы
# полос имеет смысл откалибровать на реальном распределении.
BACKCHECK_PENALTY = {
    "number_mismatch": 40,
    "unit_mismatch": 20,
    "negation_shift": 40,
    "pair_shift": 30,
    # Потерянный термин штрафуется ДОЛЕЙ сегмента, а не плоским числом.
    # Прежние −25 за термин (потолок −50) были вторым счётом за ту же потерю:
    # слова термина нет в обратном переводе, значит recall УЖЕ упал на него.
    # А сверху ложилась четверть шкалы, одинаковая и для одного слова
    # в сорокасловном абзаце, и для трёхсловной фразы в сегменте из восьми
    # слов. Здесь записан штраф за предельный случай — когда потерянные
    # термины и есть ВЕСЬ сегмент; в этом случае он равен прежнему потолку.
    "term_lost_full": 50,
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

# Ниже этого числа РАЗНЫХ содержательных основ доля выживших перестаёт быть
# мерой и становится монеткой: у сегмента из одного слова recall бывает только
# 1.0 или 0.0, промежуточных значений нет физически. Любой синоним в обратном
# переводе даёт ноль — «Фтизиатрия → Phthisiology → Фтизиология» и «плевры →
# pleura → плевра» получали 0% при совершенно верном переводе. Ноль здесь —
# не приговор переводу, а признание, что измерить нечем: решать должен судья,
# и зона его вызова для таких сегментов открывается до самого низа шкалы
# (см. _judge_zone в main.py).
BACKCHECK_MIN_STEMS = 3

# Версия ПРАВИЛ подсчёта балла. Едет в записи сегмента (`backcheck.v`) и служит
# ровно одному: отличить оценку, посчитанную нынешними правилами, от доставшейся
# от прежних. Хеш перевода этого не ловит — текст-то не менялся, менялись
# правила, — и запись со старым баллом считалась свежей навсегда. На боевом
# проекте так и вышло: правку 25.08 (потеря термина считается только по приказным
# записям, сравнение форм слова вместо обрезки основ) не увидели 798 сегментов,
# у 303 из них судья остался погашен как при жёсткой находке.
# Меняешь формулу, состав жёстких находок или полосы — поднимай версию: по ней
# идёт БЕСПЛАТНЫЙ пересчёт из сохранённого обратного перевода
# (`_rescore_backchecks` в main.py), а не платный перезапуск проверки.
BACKCHECK_VERSION = 2


def lexically_blind(source_ru):
    """Оригинал слишком короток, чтобы лексическая мера что-то значила."""
    return len(set(_stems(source_ru))) < BACKCHECK_MIN_STEMS


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


def _words_of(text):
    """Содержательные слова в нормальном виде — БЕЗ обрезки основы.
    Отбор тот же, что у _stems (короткие и служебные не в счёт), чтобы
    «пережил термин круг» и «доля выживших слов» считали по одним словам."""
    return [w for w in re.findall(r"[а-яёa-z0-9]+", _norm(text))
            if len(w) >= 3 and w not in RU_STOPWORDS]


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


# Сколько букв должно совпасть, чтобы считать два слова одной формой одного
# слова. Обрезка до BACKCHECK_STEM_LEN режет русское слово ровно по окончанию:
# «высокой» → «высоко», «высокую» → «высоку». Слово в обратном переводе есть,
# а проверка объявляет термин потерянным — и балл падает на ровном месте.
# Поэтому сравниваем не обрезки, а общий префикс: не короче четырёх букв
# И не меньше 60% короткого из двух слов. «противотуберкулёзный» против
# «туберкулёзный» так НЕ сходятся (общий префикс ноль) — отвалившаяся
# приставка остаётся настоящей потерей, ради которой проверка и заведена.
TERM_SAME_MIN_PREFIX = 4
TERM_SAME_MIN_SHARE = 0.6


def _common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _same_word_form(a, b):
    """Два слова — формы одного слова, а не разные слова."""
    if a == b:
        return True
    n = _common_prefix(a, b)
    return (n >= TERM_SAME_MIN_PREFIX
            and n >= TERM_SAME_MIN_SHARE * min(len(a), len(b)))


def _term_survived(term, back_stems, back_words=()):
    """Пережил ли термин обратный перевод.

    Сначала по основам (как раньше), потом по формам слова: обрезка основы
    слишком груба, чтобы на ней одной выносить приговор — см. _same_word_form.
    Второй проход только смягчает: то, что совпало по основам, совпадёт и так."""
    ts = _stems(term)
    if not ts:
        return False
    if all(t in back_stems for t in ts):
        return True
    if not back_words:
        return False
    return all(any(_same_word_form(w, bw) for bw in back_words)
               for w in _words_of(term))


def backcheck_issues(source_ru, back_ru, glossary_matches=None, domain=None, src_lang="RU"):
    """Расхождения между оригиналом и обратным переводом.

    Обе стороны здесь на языке ОРИГИНАЛА, поэтому и маркеры отрицания, и правила
    направлений берутся по src_lang: сравниваем русский с русским."""
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

    # Маркеры — языка ОРИГИНАЛА: обе стороны здесь на нём. Раньше стоял
    # жёсткий NEGATION_RU, и для нерусского оригинала проверка была мёртвой,
    # хотя докстринг обещал обратное. Нет маркеров для языка — молчим:
    # выдуманная находка хуже отсутствующей.
    neg = negation_markers(src_lang)
    if neg and _contains_any(source, neg) != _contains_any(back, neg):
        issues.append(_make_issue(
            "backcheck_negation_shift", "critical",
            "Отрицание изменилось при обратном переводе — утверждение и отрицание "
            "не должны меняться местами.",
            detected_by="backcheck_comparator"))

    pairs = rules_for(domain, src_lang, src_lang)["pairs"] or rules_for(domain, src_lang, "EN")["pairs"]
    by_name = {r["name"]: r for r in pairs}
    for rule in pairs:
        if not _contains_any(source, rule["source_terms"]):
            continue
        opposite = by_name.get(_PAIR_OPPOSITE.get(rule["name"], ""))
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
    back_words = _words_of(back)
    lost = []
    for hit in (glossary_matches or []):
        term = hit.get("_form") or hit.get("src") or ""
        if not term or not _has_exact_term(source, term):
            continue
        if not _term_survived(term, back_stems, back_words):
            lost.append(term)
    for term in lost:
        issues.append(_make_issue(
            "backcheck_term_lost", "major",
            "Термин «{0}» не пережил обратный перевод — в обратном тексте его нет. "
            "Возможна подмена понятия.".format(term),
            source_fragment=term, detected_by="backcheck_comparator"))

    return issues, lost


def _term_lost_penalty(source_ru, lost):
    """Штраф за потерянные термины — ДОЛЕЙ сегмента, а не плоским числом.

    Доля считается по содержательным словам: сколько их приходится на
    потерянные термины от всех слов оригинала. Мера та же, по которой считается
    и сам балл (`_words_of`), поэтому «термин» и «обычное слово» тут меряются
    одной линейкой, а не двумя.

    Зачем вообще: слова термина нет в обратном переводе, значит `_content_recall`
    УЖЕ вычел их из балла. Плоские −25 сверху были вторым счётом за ту же
    потерю — и одинаковым для одного слова в сорокасловном абзаце и для
    трёхсловной фразы в сегменте из восьми слов. Балл отвечает на вопрос
    «много ли смысла пережило круг», а «какой именно термин чинить» говорят
    `terms_lost` и `reasons`; смешивать эти два ответа в одном числе значит
    получать тревожную цифру там, где потеряно одно слово из сорока.

    Повторы одного термина считаются один раз: `glossary_matches` вправе
    отдать одну и ту же форму дважды, а потеряна она при этом одна.
    Знаменатель ноль (в оригинале нет содержательных слов) — мерить нечем,
    берём предельный случай: доля 1, то есть прежний потолок."""
    seen, words = set(), 0
    for term in (lost or []):
        key = _norm(term)
        if key in seen:
            continue
        seen.add(key)
        words += len(_words_of(term))
    total = len(_words_of(source_ru))
    share = min(1.0, words / total) if total else 1.0
    return BACKCHECK_PENALTY["term_lost_full"] * share


# Числа, единицы, отрицание и подмена стороны — объективные находки: они
# не зависят ни от длины сегмента, ни от морфологии, и судья их отменить
# не вправе.
BACKCHECK_HARD_TYPES = {"backcheck_number_mismatch", "backcheck_unit_mismatch",
                        "backcheck_negation_shift", "backcheck_pair_shift"}


def _hard_issue(issues):
    """Есть ли находка, при которой судью звать незачем — он её не отменит.

    `backcheck_term_lost` сюда НЕ входит ни при какой длине оригинала, и это
    главное свойство списка. «Пережила ли словоформа перефразировку» — то же
    грубое сравнение основ и префиксов, что дало и сам балл (`_content_recall`,
    `_same_word_form`), только суженное до слов глоссария. Это не независимая
    улика, а тот же счёт, сказанный второй раз, и ошибается он ровно там, где
    ошибается морфология: «туберкулёз лёгких» обратный перевод возвращает как
    «лёгочный туберкулёз», «вдохе» — как «вдоха». Ровно на такой вопрос и
    отвечает судья, читающий оба текста целиком.
    Прежде находка считалась жёсткой на длинном оригинале — и гасила судью
    у 303 сегментов боевого проекта, то есть отнимала апелляцию у претензии,
    которую апелляция и должна была снимать.

    Соблюдению глоссария это ничем не грозит: «использован ли утверждённый
    перевод» считает отдельная детерминированная проверка по ТЕКСТУ ПЕРЕВОДА
    (`_gloss_misses` / `/glossary-impact`), и от вердикта судьи она не зависит.

    Числа, единицы, отрицание и подмена стороны от длины и от морфологии
    не зависят и остаются жёсткими всегда."""
    return any(i.get("type") in BACKCHECK_HARD_TYPES for i in (issues or []))


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
    # На коротком оригинале балл — не измерение (см. lexically_blind), и вердикт
    # судьи там единственная мера. Поэтому годится и `minor` при подтверждённом
    # смысле: «плевры → pleura → плевра» судья описывает как «различается только
    # грамматическая форма» и ставит minor — по вопросу back-check («пережил ли
    # смысл круг») это чистое «да», а балл без подъёма остаётся нулём, то есть
    # приговором, которого никто не выносил. На длинном сегменте minor ничего
    # не поднимает: там ноль что-то значил.
    blind = bool(result.get("lex_blind"))
    lifts = sev == "none" or (blind and sev == "minor"
                              and verdict.get("same_meaning") is True)
    if cap is not None and score > cap:
        score = cap
        result["reasons"] = list(result.get("reasons", [])) + [
            "судья: " + (verdict.get("comment") or "смысл расходится")]
    elif lifts and score < JUDGE_FLOOR_NONE:
        # Поднимаем только когда жёстких находок нет: иначе судья затрёт
        # расхождение чисел или отрицания, которое видно объективно.
        if not any(i.get("type") in BACKCHECK_HARD_TYPES
                   for i in result.get("issues", [])):
            score = JUDGE_FLOOR_NONE
            result["reasons"] = ["судья: смысл эквивалентен, отличается формулировка"]
            if result.get("terms_lost"):
                # Улику не выбрасываем молча: её отменил тот, кто читал оба
                # текста. Оставь её — и ремонт пойдёт переписывать верный
                # перевод по претензии «термин не пережил обратный перевод».
                # Снимается ровно эта претензия — про КРУГ «перевод → обратный
                # перевод». Требование глоссария («в переводе стоит утверждённый
                # вариант») считает `_gloss_misses` по тексту перевода, судью
                # оно не спрашивает, и спрятать нарушение здесь нельзя.
                result["reasons"].append(
                    "«потерян термин: " + ", ".join(result["terms_lost"][:3])
                    + "» снято судьёй: он читал оба текста целиком, а претензия "
                      "выведена тем же сравнением основ, что дало и сам балл")
                result["terms_lost"] = []
                result["issues"] = [i for i in result.get("issues", [])
                                    if i.get("type") != "backcheck_term_lost"]
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


def run_backcheck(source_ru, back_ru, glossary_matches=None, semantic=None, semantic_fn=None,
                  domain=None, src_lang="RU"):
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

    issues, lost = backcheck_issues(source_ru, back_ru, glossary_matches, domain=domain, src_lang=src_lang)
    blind = lexically_blind(source_ru)
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

    penalty = 0.0
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
        # backcheck_term_lost поштучно здесь НЕ считается: штраф за термины
        # долевой и берётся со всего списка разом (см. _term_lost_penalty).
    if lost:
        penalty += _term_lost_penalty(source_ru, lost)
        reasons.append("потерян термин: " + ", ".join(lost[:3]) + ("…" if len(lost) > 3 else ""))

    if sem_note:
        reasons.append(sem_note)
    score = int(round(max(0.0, min(100.0, score - penalty))))
    # Балл занижен, а мерить было нечем — говорим об этом прямо, а не выдаём
    # «часть текста не совпала дословно» за разбор. Балл не поднимаем: выдумать
    # число вместо измерения хуже, чем признаться, что его нет.
    # НЕ при sem_note: «обратный перевод про другое» — это результат измерения,
    # только другой мерой (косинус), и две строки подряд «мы измерили» и
    # «мерить было нечем» противоречат друг другу.
    # Про судью здесь не обещаем: звали его или нет, run_backcheck не знает —
    # тумблер выключен по умолчанию, и обещание разбирательства застыло бы
    # в сегменте навсегда. Сказано только то, что известно точно: кто вправе
    # поднять балл.
    if blind and not hard and not sem_note and score < 100:
        reasons.append("оригинал короче %d содержательных слов: доля совпавших слов "
                       "на таком отрезке бывает только 0 или 100%%, поднять балл "
                       "вправе только судья" % BACKCHECK_MIN_STEMS)
    if not reasons and score < 100:
        reasons.append("часть текста не совпала дословно")

    return {
        "score": score,
        "band": band_of(score),
        "hard": hard,
        # «Балл посчитан по мере, которая на таком отрезке ничего не мерит».
        # Едет вместе с результатом, потому что читает его apply_judge_verdict,
        # а исходного текста у него нет.
        "lex_blind": blind,
        "recall": round(recall, 3),
        "semantic": round(semantic, 3) if semantic is not None else None,
        "issues": issues,
        "terms_lost": lost,
        "reasons": reasons,
    }
