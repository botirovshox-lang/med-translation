"""
tm_loader.py

Загружает и кэширует TM из tm_reference_FINAL.tsv (366 сегментов).

TM содержит параграф-уровневые пары EN↔RU из MedlinePlus PDF.
Используется для контекстной подсказки переводчику.

Использование:
    from tm_loader import get_tm
    tm = get_tm()
    matches = tm.search("гипертония у беременных", top_n=5)
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import ClassVar, List, Optional, Tuple

from med_cat_config import TM_TSV, FINAL_OUTPUT_DIR, TM_AUTO_INSERT, TM_GREEN, TM_YELLOW

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Типы данных
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TMEntry:
    source_ru: str
    target_en: str
    confidence: str    # "reference_only" | "approved"
    notes: str


@dataclass
class TMMatch:
    entry: TMEntry
    score: int         # 0–100
    match_type: str    # "exact" | "high" | "medium" | "low"
    label: str         # зелёный / жёлтый / справочно / автовставка

    @property
    def color(self) -> str:
        if self.score >= TM_AUTO_INSERT:  return "green"
        if self.score >= TM_GREEN:        return "green"
        if self.score >= TM_YELLOW:       return "yellow"
        return "gray"

    @property
    def auto_insert(self) -> bool:
        return self.score >= TM_AUTO_INSERT


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

_INVISIBLE   = re.compile(r'[­​‌‍﻿ ]+')
_MULTI_WS    = re.compile(r'\s{2,}')
_PUNCT_STRIP = re.compile(r'[^\w\s]', re.UNICODE)


def _norm(s: str) -> str:
    """Нормализует строку: NFC + trim невидимых + схлопка пробелов."""
    s = _INVISIBLE.sub('', s)
    s = unicodedata.normalize('NFC', s)
    s = _MULTI_WS.sub(' ', s)
    return s.strip().lower()


def _norm_cmp(s: str) -> str:
    """Агрессивная нормализация для нечёткого сравнения: убираем пунктуацию и маркеры."""
    s = _norm(s)
    s = _PUNCT_STRIP.sub(' ', s)
    s = _MULTI_WS.sub(' ', s)
    return s.strip()


def _fuzzy_score(a: str, b: str) -> int:
    """
    Fuzzy similarity (0–100) между двумя строками.

    Для коротких запросов vs длинных TM-сегментов:
    - сначала проверяем совпадение без пунктуации (устраняет маркеры •, :, «»)
    - затем SequenceMatcher с нормализованным текстом
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0

    # Точное совпадение (с пунктуацией)
    if na == nb:
        return 100

    # Сравнение без пунктуации (убирает маркеры списков • , : « »)
    ca, cb = _norm_cmp(a), _norm_cmp(b)

    if ca == cb:
        return 100

    # Подстрока (без пунктуации): запрос целиком входит в TM или наоборот
    if ca and cb:
        if ca in cb:
            # Запрос = подстрока TM — качество зависит от покрытия
            coverage = len(ca) / max(len(cb), 1)
            return min(96, 70 + int(coverage * 26))
        if cb in ca:
            return 96

    # Fuzzy: сравниваем первые 600 символов TM (начало сегмента важнее)
    ratio = SequenceMatcher(None, ca, cb[:600]).ratio()
    # Корректируем по длинным TM: если TM намного длиннее запроса
    if len(cb) > len(ca) * 3 and ratio < 0.5:
        # Попробуем совпадение начала TM с запросом
        ratio_head = SequenceMatcher(None, ca, cb[:len(ca) * 2]).ratio()
        ratio = max(ratio, ratio_head)
    return int(ratio * 100)


def _match_label(score: int) -> Tuple[str, str]:
    """Возвращает (match_type, label) по числовому score."""
    if score >= TM_AUTO_INSERT:
        return "exact",  "Авто-вставка (100%)"
    if score >= TM_GREEN:
        return "high",   f"Хорошее совпадение ({score}%)"
    if score >= TM_YELLOW:
        return "medium", f"Среднее совпадение ({score}%)"
    return "low",   f"Справочно ({score}%)"


# ─────────────────────────────────────────────────────────────────────────────
# TMLoader
# ─────────────────────────────────────────────────────────────────────────────

class TMLoader:
    """
    Загружает TM один раз. Поиск линейный (366 записей — допустимо).
    Singleton.
    """
    _instance: ClassVar[Optional['TMLoader']] = None

    def __init__(self) -> None:
        self.entries: List[TMEntry] = []
        self._load()

    @classmethod
    def get(cls) -> 'TMLoader':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        path = TM_TSV if TM_TSV.exists() else (FINAL_OUTPUT_DIR / TM_TSV.name)
        if not path.exists():
            log.error("TM файл не найден: %s", path)
            return

        import csv, unicodedata as ud

        invisible = re.compile(r'[­​‌‍﻿ ]+')
        multi_ws  = re.compile(r'\s{2,}')

        def clean(s: str) -> str:
            s = invisible.sub('', s)
            s = ud.normalize('NFC', s)
            s = multi_ws.sub(' ', s)
            return s.strip()

        seen = set()
        with open(path, encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                ru = clean(row.get('Source_RU', ''))
                en = clean(row.get('Target_EN', ''))
                if not ru or not en:
                    continue
                key = ru[:80]
                if key in seen:
                    continue
                seen.add(key)
                self.entries.append(TMEntry(
                    source_ru  = ru,
                    target_en  = en,
                    confidence = clean(row.get('Confidence', '')),
                    notes      = clean(row.get('Notes', '')),
                ))

        log.info("TMLoader: %d сегментов", len(self.entries))

    def search(self, query: str, top_n: int = 10) -> List[TMMatch]:
        """
        Ищет top_n наиболее похожих TM-сегментов.
        Только сегменты с score ≥ TM_YELLOW (94) возвращаются,
        остальные отфильтровываются (не полезны переводчику).
        """
        results: List[TMMatch] = []

        for entry in self.entries:
            score = _fuzzy_score(query, entry.source_ru)
            if score < TM_YELLOW:
                continue
            mtype, label = _match_label(score)
            results.append(TMMatch(entry=entry, score=score,
                                   match_type=mtype, label=label))

        results.sort(key=lambda m: -m.score)
        return results[:top_n]

    def exact_lookup(self, query: str) -> Optional[TMMatch]:
        """Точный поиск (100%)."""
        qn = _norm(query)
        for entry in self.entries:
            if _norm(entry.source_ru) == qn:
                mtype, label = _match_label(100)
                return TMMatch(entry=entry, score=100,
                               match_type=mtype, label=label)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Публичный API
# ─────────────────────────────────────────────────────────────────────────────

def get_tm() -> TMLoader:
    """Возвращает загруженный (кэшированный) TMLoader."""
    return TMLoader.get()
