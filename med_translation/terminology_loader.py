"""
terminology_loader.py

Загружает и кэширует:
  - approved_glossary_FINAL.tsv   (10K записей)
  - reference_glossary_FINAL.tsv  (62K записей)
  - forbidden_translations_FINAL.tsv (189 записей)

Особенности:
  - UTF-8-sig (BOM) совместимость
  - Нормализация Unicode (NFC) + trim пробелов
  - Дедупликация при загрузке
  - Инвертированный индекс по токенам для быстрого поиска
  - Singleton-паттерн: файлы читаются один раз

Использование:
    from terminology_loader import get_glossary, get_forbidden
    g = get_glossary()
    matches = g.find_candidates("гипертоническая болезнь")
"""
from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
from typing import ClassVar, Dict, List, Optional, Set

from med_cat_config import (
    APPROVED_TSV, REFERENCE_TSV, FORBIDDEN_TSV, FINAL_OUTPUT_DIR
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Типы данных
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GlossaryEntry:
    russian: str
    english: str           # может содержать "; "-разделённые синонимы
    category: str
    confidence: str        # "approved" | "reference_only" | "needs_human_review"
    sources: str
    tier: str              # "approved" | "reference"

    @property
    def english_variants(self) -> List[str]:
        """Список отдельных EN-синонимов из консолидированного поля."""
        return [v.strip() for v in self.english.split(";") if v.strip()]


@dataclass(frozen=True)
class ForbiddenEntry:
    russian: str
    forbidden_english: str
    reason: str


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

_INVISIBLE = re.compile(r'[­​‌‍﻿ ]+')
_MULTI_WS  = re.compile(r'\s{2,}')
_TOKEN_RE  = re.compile(r'[а-яёА-ЯЁa-zA-Z0-9]{2,}', re.UNICODE)


def normalize(s: str) -> str:
    """
    Нормализует строку:
      - убирает невидимые символы (мягкий дефис, ZWNJ, BOM …)
      - нормализует Unicode → NFC
      - схлопывает пробелы
      - trim
    """
    s = _INVISIBLE.sub('', s)
    s = unicodedata.normalize('NFC', s)
    s = _MULTI_WS.sub(' ', s)
    return s.strip()


def tokenize(text: str) -> Set[str]:
    """Возвращает множество нижнерегистровых токенов (len ≥ 2)."""
    return {m.group().lower() for m in _TOKEN_RE.finditer(text)}


def _resolve_path(primary: Path, filename: str) -> Path:
    """Возвращает primary если файл существует, иначе FINAL_OUTPUT_DIR / filename."""
    if primary.exists():
        return primary
    fallback = FINAL_OUTPUT_DIR / filename
    if fallback.exists():
        log.warning("Используется fallback: %s", fallback)
        return fallback
    raise FileNotFoundError(
        f"Файл не найден ни по основному пути ({primary}), "
        f"ни по fallback ({fallback})"
    )


def _read_tsv(path: Path) -> List[Dict[str, str]]:
    """
    Читает TSV с UTF-8-sig.
    Пропускает строки где нет хотя бы двух заполненных полей.
    Нормализует все значения.
    """
    rows: List[Dict[str, str]] = []
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for lineno, raw in enumerate(reader, start=2):
                try:
                    row = {k: normalize(v) for k, v in raw.items() if k}
                    non_empty = sum(1 for v in row.values() if v)
                    if non_empty >= 2:
                        rows.append(row)
                except Exception as e:
                    log.debug("Строка %d пропущена (%s): %s", lineno, e, raw)
    except Exception as e:
        log.error("Ошибка чтения %s: %s", path, e)
        raise
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# GlossaryLoader — загрузчик глоссариев
# ─────────────────────────────────────────────────────────────────────────────

class GlossaryLoader:
    """
    Загружает approved + reference глоссарии в память.
    Строит инвертированный индекс для быстрого поиска по токенам.

    Singleton — вызывается один раз, далее кэшируется.
    """
    _instance: ClassVar[Optional['GlossaryLoader']] = None

    def __init__(self) -> None:
        self.entries: List[GlossaryEntry] = []
        self._token_index: Dict[str, List[int]] = defaultdict(list)
        self._ru_lower_index: Dict[str, int] = {}   # exact lookup: ru_lower → index
        self._approved_count: int = 0
        self._reference_count: int = 0
        self._load()

    @classmethod
    def get(cls) -> 'GlossaryLoader':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Загрузка ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        seen: Set[str] = set()   # ru_lower для дедупликации внутри tier

        # Approved — высший приоритет
        approved_path = _resolve_path(APPROVED_TSV, APPROVED_TSV.name)
        for row in _read_tsv(approved_path):
            self._add_row(row, tier='approved', seen=seen,
                          ru_col='Russian', en_col='English')

        self._approved_count = len(self.entries)

        # Reference — добавляем только записи, которых нет в approved
        reference_path = _resolve_path(REFERENCE_TSV, REFERENCE_TSV.name)
        ref_seen: Set[str] = set(e.russian.lower() for e in self.entries)

        for row in _read_tsv(reference_path):
            self._add_row(row, tier='reference', seen=ref_seen,
                          ru_col='Russian', en_col='English')

        self._reference_count = len(self.entries) - self._approved_count

        log.info(
            "GlossaryLoader: approved=%d reference=%d total=%d",
            self._approved_count, self._reference_count, len(self.entries)
        )

    def _add_row(
        self,
        row: Dict[str, str],
        tier: str,
        seen: Set[str],
        ru_col: str,
        en_col: str,
    ) -> None:
        ru = row.get(ru_col, '').strip()
        en = row.get(en_col, '').strip()
        if not ru or not en:
            return

        ru_lower = ru.lower()
        if ru_lower in seen:
            return
        seen.add(ru_lower)

        entry = GlossaryEntry(
            russian    = ru,
            english    = en,
            category   = row.get('Category', ''),
            confidence = row.get('Confidence', ''),
            sources    = row.get('Sources', ''),
            tier       = tier,
        )
        idx = len(self.entries)
        self.entries.append(entry)

        # Exact index
        self._ru_lower_index[ru_lower] = idx

        # Token index
        for tok in tokenize(ru):
            self._token_index[tok].append(idx)

    # ── Поиск ────────────────────────────────────────────────────────────────

    def find_candidates(self, source_text: str) -> List[GlossaryEntry]:
        """
        Возвращает список GlossaryEntry, чьи RU-термины встречаются
        (по токенам) в source_text. Approved-записи идут первыми.
        """
        tokens = tokenize(source_text)
        candidate_indices: Set[int] = set()
        for tok in tokens:
            candidate_indices.update(self._token_index.get(tok, []))

        # Сортируем: approved первыми, затем reference
        candidates = [self.entries[i] for i in candidate_indices]
        candidates.sort(key=lambda e: (0 if e.tier == 'approved' else 1, e.russian))
        return candidates

    def exact_lookup(self, russian: str) -> Optional[GlossaryEntry]:
        """Точный поиск по русскому термину (без учёта регистра)."""
        idx = self._ru_lower_index.get(russian.lower())
        return self.entries[idx] if idx is not None else None

    @property
    def stats(self) -> Dict[str, int]:
        return {
            'approved': self._approved_count,
            'reference': self._reference_count,
            'total': len(self.entries),
        }


# ─────────────────────────────────────────────────────────────────────────────
# ForbiddenLoader — загрузчик запрещённых переводов
# ─────────────────────────────────────────────────────────────────────────────

class ForbiddenLoader:
    """
    Загружает forbidden_translations_FINAL.tsv.

    Строит два индекса:
      - по русскому исходнику (для pre-translation check)
      - по запрещённому EN-слову (для post-translation scan)
    """
    _instance: ClassVar[Optional['ForbiddenLoader']] = None

    def __init__(self) -> None:
        self.entries: List[ForbiddenEntry] = []
        # ru_lower → List[ForbiddenEntry]
        self._by_ru: Dict[str, List[ForbiddenEntry]] = defaultdict(list)
        # forbidden_en_lower → List[ForbiddenEntry]
        self._by_forbidden_en: Dict[str, List[ForbiddenEntry]] = defaultdict(list)
        self._load()

    @classmethod
    def get(cls) -> 'ForbiddenLoader':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        path = _resolve_path(FORBIDDEN_TSV, FORBIDDEN_TSV.name)
        seen: Set[tuple] = set()

        for row in _read_tsv(path):
            ru  = row.get('Russian', '').strip()
            fen = row.get('Forbidden_English', '').strip()
            reason = row.get('Reason', '').strip()
            if not ru or not fen:
                continue
            key = (ru.lower(), fen.lower())
            if key in seen:
                continue
            seen.add(key)

            entry = ForbiddenEntry(russian=ru, forbidden_english=fen, reason=reason)
            self.entries.append(entry)
            self._by_ru[ru.lower()].append(entry)
            self._by_forbidden_en[fen.lower()].append(entry)

        log.info("ForbiddenLoader: %d записей", len(self.entries))

    def by_russian(self, russian: str) -> List[ForbiddenEntry]:
        return self._by_ru.get(russian.lower(), [])

    def by_forbidden_en(self, en_word: str) -> List[ForbiddenEntry]:
        return self._by_forbidden_en.get(en_word.lower(), [])

    def all_forbidden_en_words(self) -> Set[str]:
        return set(self._by_forbidden_en.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Публичный API
# ─────────────────────────────────────────────────────────────────────────────

def get_glossary() -> GlossaryLoader:
    """Возвращает загруженный (кэшированный) GlossaryLoader."""
    return GlossaryLoader.get()


def get_forbidden() -> ForbiddenLoader:
    """Возвращает загруженный (кэшированный) ForbiddenLoader."""
    return ForbiddenLoader.get()
