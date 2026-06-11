"""
risk_engine.py

Правил-основанная оценка риска медицинского сегмента.

Уровни риска (от высшего к низшему):
  CRITICAL — числа + дозировки + направления + диагностика (несколько HIGH-факторов)
  HIGH     — дозировки, положительный/отрицательный, острый/хронический, диагноз
  MEDIUM   — медицинская терминология, аббревиатуры, лабораторные значения
  LOW      — заголовки, простые словарные термины

Использование:
    from risk_engine import score_risk, RiskResult
    result = score_risk("Доза аспирина 500 мг каждые 6 часов")
    print(result.level, result.risk_reasons)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Типы данных
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RiskResult:
    level: str             # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    risk_score: int        # числовой счёт (0–100)
    risk_reasons: List[str]
    raw_matches: List[Tuple[str, str]]   # (category, matched_text)

    @property
    def color(self) -> str:
        return {
            'CRITICAL': '#FF0000',
            'HIGH':     '#FF6B00',
            'MEDIUM':   '#FFC107',
            'LOW':      '#28A745',
        }.get(self.level, '#999999')

    @property
    def badge(self) -> str:
        icons = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🟡', 'LOW': '🟢'}
        return f"{icons.get(self.level, '⚪')} {self.level}"

    @property
    def needs_numerical_qa(self) -> bool:
        return self.level in ('CRITICAL', 'HIGH') and any(
            'доза' in r.lower() or 'число' in r.lower() or 'концентрация' in r.lower()
            for r in self.risk_reasons
        )


# ─────────────────────────────────────────────────────────────────────────────
# Паттерны риска
# ─────────────────────────────────────────────────────────────────────────────

# ── HIGH RISK ────────────────────────────────────────────────────────────────

_DOSAGE = re.compile(
    r'\b\d+[,.]?\d*\s*'
    r'(?:мг|мл|мкг|г\b|кг|МЕ|ЕД|ед\.|%|мМоль|ммоль|мкмоль|нмоль|пмоль|'
    r'мм\s?рт|ммHg|мл/кг|мг/кг|мг/мл|мкг/кг|ЕД/кг|тыс\.?\s?ЕД)',
    re.IGNORECASE | re.UNICODE,
)

_NUMERIC_RANGE = re.compile(
    r'\b\d+(?:[,./]\d+)?\s*[-–]\s*\d+(?:[,./]\d+)?\b'
)

_POSITIVE_NEGATIVE = re.compile(
    r'\b(?:положительный|отрицательный|позитивный|негативный|'
    r'положительная|отрицательная|положительное|отрицательное|'
    r'серопозитивный|серонегативный|ВИЧ-положительный|ВИЧ-отрицательный)\b',
    re.IGNORECASE,
)

_ACUTE_CHRONIC = re.compile(
    r'\b(?:острый|хронический|острая|хроническая|острое|хроническое|'
    r'подострый|подострая|рецидивирующий|персистирующий)\b',
    re.IGNORECASE,
)

_ANATOMY_DIRECTIONS = re.compile(
    r'\b(?:передний|задний|медиальный|латеральный|проксимальный|дистальный|'
    r'верхний|нижний|правый|левый|центральный|периферический|'
    r'ипсилатеральный|контралатеральный|билатеральный|унилатеральный|'
    r'дорсальный|вентральный|краниальный|каудальный)\b',
    re.IGNORECASE,
)

_DIAGNOSIS = re.compile(
    r'\b(?:диагноз|диагностика|дифференциальный|патология|синдром|болезнь|'
    r'заболевание|недостаточность|дефицит|дисфункция|нарушение)\b',
    re.IGNORECASE,
)

_TREATMENT_CRITICAL = re.compile(
    r'\b(?:доза|дозировка|назначение|введение|инъекция|инфузия|трансфузия|'
    r'переливание|хирургическое|операция|резекция|трансплантация|'
    r'химиотерапия|лучевая|облучение)\b',
    re.IGNORECASE,
)

# ── MEDIUM RISK ──────────────────────────────────────────────────────────────

_MEDICAL_ABBREV = re.compile(
    r'\b(?:[А-ЯA-Z]{2,6}|'        # русские аббревиатуры
    r'ЭКГ|ЭЭГ|МРТ|КТ|УЗИ|ЭКО|ИВЛ|АД|ЧСС|ЧД|SpO2|ЭхоКГ|ФГДС|РХПГ|КФК|ЛДГ|'
    r'ЦНС|ЦВД|ПЦР|ВИЧ|СПИД|ТБ|ОРВИ|ОРЗ|ХСН|ХБП|ИМТ|ИБС)\b',
    re.UNICODE,
)

_LAB_VALUES = re.compile(
    r'\b(?:уровень|концентрация|активность|норма|нормальный|референс|'
    r'анализ|результат|показатель|индекс|коэффициент)\b',
    re.IGNORECASE,
)

_PROCEDURES_MED = re.compile(
    r'\b(?:биопсия|эндоскопия|томография|рентген|сцинтиграфия|ПЭТ|'
    r'пункция|катетеризация|ангиография|флюороскопия|маммография|'
    r'колоноскопия|бронхоскопия|гастроскопия)\b',
    re.IGNORECASE,
)

_MEDICATIONS = re.compile(
    r'\b(?:антибиотик|препарат|лекарство|таблетк|капсул|ампул|'
    r'мазь|раствор|суспензия|аэрозоль|пластырь|крем|гель)\b',
    re.IGNORECASE,
)

# ── LOW RISK ─────────────────────────────────────────────────────────────────
# Заголовки: короткие сегменты (< 5 слов) без медицинских паттернов
_HEADING_LEN = 40   # символов


# ─────────────────────────────────────────────────────────────────────────────
# Оценка риска
# ─────────────────────────────────────────────────────────────────────────────

def score_risk(source_ru: str) -> RiskResult:
    """
    Анализирует риск медицинского сегмента.

    Возвращает RiskResult с уровнем, очками и списком причин.
    """
    text = source_ru.strip()
    if not text:
        return RiskResult(level='LOW', risk_score=0,
                          risk_reasons=['Пустой сегмент'], raw_matches=[])

    raw_matches: List[Tuple[str, str]] = []
    risk_score = 0

    def _check(pattern: re.Pattern, category: str, points: int,
                reason: str) -> int:
        found = pattern.findall(text)
        if found:
            raw_matches.append((category, str(found[:3])))
            return points
        return 0

    # ── HIGH факторы (каждый добавляет очки) ─────────────────────────────────
    risk_score += _check(_DOSAGE,             'dosage',     35, '')
    risk_score += _check(_NUMERIC_RANGE,      'numbers',    15, '')
    risk_score += _check(_POSITIVE_NEGATIVE,  'pos_neg',    20, '')
    risk_score += _check(_ACUTE_CHRONIC,      'acute_chron',15, '')
    risk_score += _check(_ANATOMY_DIRECTIONS, 'directions', 20, '')
    risk_score += _check(_DIAGNOSIS,          'diagnosis',  15, '')
    risk_score += _check(_TREATMENT_CRITICAL, 'treatment',  25, '')

    # ── MEDIUM факторы ────────────────────────────────────────────────────────
    risk_score += _check(_MEDICAL_ABBREV,   'abbreviations', 10, '')
    risk_score += _check(_LAB_VALUES,       'lab_values',    10, '')
    risk_score += _check(_PROCEDURES_MED,   'procedures',     8, '')
    risk_score += _check(_MEDICATIONS,      'medications',   12, '')

    # ── Длина как LOW-сигнал ──────────────────────────────────────────────────
    word_count = len(text.split())
    if word_count <= 3 and risk_score < 20:
        risk_score = max(risk_score, 5)   # короткий сегмент → минимальный риск

    risk_score = min(risk_score, 100)

    # ── Уровень ───────────────────────────────────────────────────────────────
    if risk_score >= 65:
        level = 'CRITICAL'
    elif risk_score >= 35:
        level = 'HIGH'
    elif risk_score >= 12:
        level = 'MEDIUM'
    else:
        level = 'LOW'

    # ── Текстовые причины ─────────────────────────────────────────────────────
    reasons: List[str] = []
    category_labels = {
        'dosage':       'Числовые дозировки / единицы измерения',
        'numbers':      'Числовые диапазоны',
        'pos_neg':      'Положительный / отрицательный результат',
        'acute_chron':  'Острый / хронический / рецидивирующий',
        'directions':   'Анатомические направления',
        'diagnosis':    'Диагностическая лексика',
        'treatment':    'Терапевтическая лексика / операции',
        'abbreviations':'Медицинские аббревиатуры',
        'lab_values':   'Лабораторные показатели',
        'procedures':   'Медицинские процедуры',
        'medications':  'Лекарственные формы',
    }
    for cat, _ in raw_matches:
        label = category_labels.get(cat, cat)
        if label not in reasons:
            reasons.append(label)

    if not reasons:
        reasons = ['Низкий риск — общий медицинский текст']

    return RiskResult(
        level        = level,
        risk_score   = risk_score,
        risk_reasons = reasons,
        raw_matches  = raw_matches,
    )
