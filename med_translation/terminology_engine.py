"""
terminology_engine.py

Движок сопоставления терминов для текущего сегмента.

Возможности:
  - точное совпадение (exact)
  - совпадение без учёта регистра (case-insensitive)
  - нечёткое совпадение (fuzzy, difflib)
  - приоритет: approved > reference
  - формирование контекста для инжекции в промпт

Использование:
    from terminology_engine import match_segment, build_prompt_context
    matches = match_segment("острый инфаркт миокарда с подъёмом ST")
    context = build_prompt_context(matches)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from med_cat_config import FUZZY_MIN_SCORE, MAX_GLOSSARY_TERMS_IN_PROMPT
from terminology_loader import GlossaryEntry, GlossaryLoader, get_glossary, tokenize


# ─────────────────────────────────────────────────────────────────────────────
# Типы данных
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TermMatch:
    entry: GlossaryEntry
    match_type: str    # "exact" | "case_insensitive" | "partial" | "fuzzy"
    score: float       # 0.0–1.0
    matched_span: str  # фрагмент исходного текста, который совпал

    @property
    def is_approved(self) -> bool:
        return self.entry.tier == 'approved'

    @property
    def priority(self) -> int:
        """Меньше = важнее."""
        tier_rank = 0 if self.is_approved else 1
        type_rank = {'exact': 0, 'case_insensitive': 1,
                     'partial': 2, 'fuzzy': 3}.get(self.match_type, 4)
        return tier_rank * 10 + type_rank

    @property
    def display_label(self) -> str:
        icons = {'exact': '✓', 'case_insensitive': '✓',
                 'partial': '~', 'fuzzy': '≈'}
        tier  = 'approved' if self.is_approved else 'reference'
        mtype = icons.get(self.match_type, '?')
        pct   = f"{int(self.score * 100)}%"
        return f"{mtype} {tier} [{pct}]"


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

_PUNCT = re.compile(r'[^\w\s]', re.UNICODE)


def _normalize_for_compare(s: str) -> str:
    """Нижний регистр + убираем пунктуацию (кроме пробелов)."""
    return _PUNCT.sub('', s.lower()).strip()


def _fuzzy_ratio(a: str, b: str) -> float:
    """SequenceMatcher ratio (0.0–1.0)."""
    return SequenceMatcher(None,
                           _normalize_for_compare(a),
                           _normalize_for_compare(b)).ratio()


def _term_in_segment(term: str, segment: str) -> Optional[Tuple[str, str]]:
    """
    Проверяет наличие term в segment по нескольким стратегиям.
    Возвращает (match_type, matched_span) или None.

    Стратегии (в порядке приоритета):
      1. Точное совпадение (целое слово / фраза)
      2. Совпадение без регистра
      3. Нечёткое совпадение (только для коротких терминов ≤ 60 символов)
    """
    # 1. Exact
    if term in segment:
        return 'exact', term

    # 2. Case-insensitive
    t_lower = term.lower()
    s_lower = segment.lower()
    if t_lower in s_lower:
        # найти реальный span
        idx = s_lower.find(t_lower)
        span = segment[idx: idx + len(term)]
        return 'case_insensitive', span

    # 3. Fuzzy — только для терминов ≤ 60 символов, иначе слишком дорого
    if len(term) <= 60:
        ratio = _fuzzy_ratio(term, segment[:len(term) * 3])  # сравниваем с началом сегмента
        if ratio >= FUZZY_MIN_SCORE:
            return 'fuzzy', term

        # Sliding window: ищем похожую подстроку
        term_tokens = tokenize(term)
        seg_tokens  = tokenize(segment)
        if term_tokens and term_tokens.issubset(seg_tokens):
            return 'partial', term

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Основной движок
# ─────────────────────────────────────────────────────────────────────────────

def match_segment(
    source_ru: str,
    *,
    glossary: Optional[GlossaryLoader] = None,
    max_results: int = MAX_GLOSSARY_TERMS_IN_PROMPT,
) -> List[TermMatch]:
    """
    Находит все термины глоссария в source_ru.

    Алгоритм:
      1. Получаем кандидатов через инвертированный индекс (быстро)
      2. Для каждого кандидата проверяем точное/fuzzy совпадение
      3. Сортируем: approved сначала, точные сначала, по длине термина убывая
      4. Дедупликация: не возвращаем два матча для одного RU-термина

    Параметры:
        source_ru   — исходный текст на русском
        glossary    — GlossaryLoader (если None, берётся синглтон)
        max_results — максимум терминов в выдаче (оптимизация токенов)
    """
    if not source_ru.strip():
        return []

    gl = glossary or get_glossary()
    candidates = gl.find_candidates(source_ru)

    matches: List[TermMatch] = []
    seen_ru_lower: set = set()

    for entry in candidates:
        ru_lower = entry.russian.lower()
        if ru_lower in seen_ru_lower:
            continue

        result = _term_in_segment(entry.russian, source_ru)
        if result is None:
            # Ещё одна попытка: проверяем, встречается ли термин как подстрока
            result = _term_in_segment(entry.russian.lower(), source_ru.lower())
            if result:
                mtype, span = result
                if mtype == 'exact':
                    mtype = 'case_insensitive'

        if result is not None:
            mtype, span = result
            score = {
                'exact': 1.0,
                'case_insensitive': 0.98,
                'partial': 0.85,
                'fuzzy': FUZZY_MIN_SCORE,
            }.get(mtype, 0.7)

            matches.append(TermMatch(
                entry        = entry,
                match_type   = mtype,
                score        = score,
                matched_span = span,
            ))
            seen_ru_lower.add(ru_lower)

    # Сортируем: приоритет (approved+exact → approved+fuzzy → reference+exact …)
    # внутри приоритета: длинные термины важнее (более специфичны)
    matches.sort(key=lambda m: (m.priority, -len(m.entry.russian)))

    return matches[:max_results]


# ─────────────────────────────────────────────────────────────────────────────
# Формирование контекста для промпта (оптимизация токенов)
# ─────────────────────────────────────────────────────────────────────────────

def build_prompt_context(matches: List[TermMatch]) -> str:
    """
    Формирует текстовый блок для инжекции в системный промпт.
    Только утверждённые и справочные термины, найденные в сегменте.

    Пример вывода:
        APPROVED TERMINOLOGY (use exactly):
        - гипертония → hypertension
        - инфаркт миокарда → myocardial infarction

        REFERENCE TERMINOLOGY (consider using):
        - миокард → myocardium; cardiac muscle
    """
    if not matches:
        return ""

    approved_lines: List[str] = []
    reference_lines: List[str] = []

    for m in matches:
        ru = m.entry.russian
        en = m.entry.english_variants[0] if m.entry.english_variants else m.entry.english
        # Если несколько синонимов — показываем через / для краткости
        all_en = ' / '.join(m.entry.english_variants[:3])
        line = f"- {ru} → {all_en}"

        if m.is_approved:
            approved_lines.append(line)
        else:
            reference_lines.append(line)

    parts: List[str] = []
    if approved_lines:
        parts.append("APPROVED TERMINOLOGY (use exactly):\n" +
                     "\n".join(approved_lines))
    if reference_lines:
        parts.append("REFERENCE TERMINOLOGY (consider using):\n" +
                     "\n".join(reference_lines))

    return "\n\n".join(parts)


def build_tm_context(tm_matches: List) -> str:
    """
    Формирует текстовый блок TM-примеров для промпта.
    Принимает список TMMatch из tm_loader.
    """
    if not tm_matches:
        return ""
    lines = ["TRANSLATION MEMORY (similar segments, use as style guide):"]
    for m in tm_matches[:3]:   # не более 3 сегментов чтобы не раздувать промпт
        # Показываем только первые 300 символов каждого сегмента
        src = m.entry.source_ru[:300]
        tgt = m.entry.target_en[:300]
        lines.append(f"  [{m.score}% match]\n  RU: {src}\n  EN: {tgt}")
    return "\n".join(lines)
