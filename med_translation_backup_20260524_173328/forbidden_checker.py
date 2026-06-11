"""
forbidden_checker.py

Проверяет переведённый сегмент на наличие запрещённых переводов.

Логика двухэтапная:
  1. PRE-TRANSLATION (source scan):
     Находит RU-термины в исходнике, для которых есть запрещённые EN-варианты.
     → Предупреждает переводчика до перевода.

  2. POST-TRANSLATION (output scan):
     Ищет запрещённые EN-слова прямо в переведённом тексте.
     → Блокирует подтверждение, требует ревью.

Использование:
    from forbidden_checker import pre_check, post_check, ForbiddenAlert
    # до перевода:
    warnings = pre_check(source_ru)
    # после перевода:
    alerts   = post_check(source_ru, translated_en)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from terminology_loader import ForbiddenEntry, ForbiddenLoader, get_forbidden, get_glossary


# ─────────────────────────────────────────────────────────────────────────────
# Типы данных
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ForbiddenAlert:
    stage: str                 # "pre" | "post"
    severity: str              # "error" | "warning"
    russian_term: str          # RU-термин из исходника
    forbidden_en: str          # запрещённый EN-вариант
    reason: str                # причина из словаря
    preferred_en: Optional[str]  # предпочтительный вариант (из глоссария, если найден)
    message: str               # человекочитаемое описание

    @property
    def icon(self) -> str:
        return "🔴" if self.severity == "error" else "🟡"


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

_WORD_BOUNDARY = re.compile(r'\b{term}\b', re.IGNORECASE)


def _word_in_text(word: str, text: str) -> bool:
    """Проверяет наличие слова/фразы в тексте с учётом границ слов."""
    try:
        pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        return bool(pattern.search(text))
    except re.error:
        return word.lower() in text.lower()


def _get_preferred(russian: str) -> Optional[str]:
    """
    Ищет предпочтительный EN-вариант для русского термина в одобренном глоссарии.
    """
    try:
        gl = get_glossary()
        entry = gl.exact_lookup(russian)
        if entry and entry.tier == 'approved':
            return entry.english_variants[0] if entry.english_variants else entry.english
        # Если нет точного совпадения, попробуем кандидатов
        candidates = gl.find_candidates(russian)
        for c in candidates:
            if c.tier == 'approved' and c.russian.lower() == russian.lower():
                return c.english_variants[0] if c.english_variants else c.english
    except Exception:
        pass
    return None


def _classify_severity(reason: str) -> str:
    """dangerous_mismatch → error, остальное → warning."""
    if 'dangerous' in reason.lower() or 'mismatch' in reason.lower():
        return "error"
    return "warning"


# ─────────────────────────────────────────────────────────────────────────────
# PRE-TRANSLATION CHECK
# ─────────────────────────────────────────────────────────────────────────────

def pre_check(source_ru: str) -> List[ForbiddenAlert]:
    """
    Сканирует исходный RU-текст: находит термины с запрещёнными переводами.
    Предупреждает переводчика ДО начала перевода.

    Возвращает список ForbiddenAlert (может быть пустым).
    """
    fl = get_forbidden()
    alerts: List[ForbiddenAlert] = []
    seen: set = set()

    for entry in fl.entries:
        # Проверяем, встречается ли запрещённый RU-термин в исходнике
        if _word_in_text(entry.russian, source_ru):
            key = (entry.russian.lower(), entry.forbidden_english.lower())
            if key in seen:
                continue
            seen.add(key)

            preferred = _get_preferred(entry.russian)
            severity  = _classify_severity(entry.reason)

            msg = (
                f"Термин «{entry.russian}» имеет запрещённый перевод: "
                f"«{entry.forbidden_english}»"
            )
            if preferred:
                msg += f". Используй: «{preferred}»"

            alerts.append(ForbiddenAlert(
                stage        = "pre",
                severity     = severity,
                russian_term = entry.russian,
                forbidden_en = entry.forbidden_english,
                reason       = entry.reason,
                preferred_en = preferred,
                message      = msg,
            ))

    return alerts


# ─────────────────────────────────────────────────────────────────────────────
# POST-TRANSLATION CHECK
# ─────────────────────────────────────────────────────────────────────────────

def post_check(source_ru: str, translated_en: str) -> List[ForbiddenAlert]:
    """
    Сканирует результат перевода на запрещённые EN-слова.
    Работает в связке с исходником: проверяет только те запрещённые термины,
    чьи RU-источники встречаются в исходнике (снижает ложные срабатывания).

    Если RU-источник не найден в тексте — всё равно проверяем по EN,
    так как translator мог перефразировать (fallback).
    """
    if not translated_en.strip():
        return []

    fl = get_forbidden()
    alerts: List[ForbiddenAlert] = []
    seen: set = set()

    for entry in fl.entries:
        # Запрещённый EN есть в переводе?
        if not _word_in_text(entry.forbidden_english, translated_en):
            continue

        # POST-CHECK: дедупликация по запрещённому EN-слову
        # (несколько RU-терминов могут иметь один запрещённый EN — показываем 1 раз)
        key = entry.forbidden_english.lower()
        if key in seen:
            continue
        seen.add(key)

        # Дополнительная проверка: RU-источник должен быть в исходнике
        ru_in_source = _word_in_text(entry.russian, source_ru)

        # Если RU не в источнике — снижаем серьёзность (может быть другой контекст)
        severity = _classify_severity(entry.reason)
        if not ru_in_source:
            severity = "warning"

        preferred = _get_preferred(entry.russian)

        msg = (
            f"Запрещённый перевод «{entry.forbidden_english}» "
            f"обнаружен в выводе"
        )
        if entry.russian:
            msg += f" (для термина «{entry.russian}»)"
        if preferred:
            msg += f". Рекомендуемый вариант: «{preferred}»"

        alerts.append(ForbiddenAlert(
            stage        = "post",
            severity     = severity,
            russian_term = entry.russian,
            forbidden_en = entry.forbidden_english,
            reason       = entry.reason,
            preferred_en = preferred,
            message      = msg,
        ))

    return alerts
