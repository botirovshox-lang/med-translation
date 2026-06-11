"""
workflow_engine.py

Рекомендует рабочий процесс на основе уровня риска сегмента.

Шаги (WorkflowStep):
  TRANSLATE     — перевести сегмент
  QA            — общая проверка качества
  NUMERICAL_QA  — числовая QA (дозировки, единицы)
  BACK_CHECK    — обратный перевод / верификация
  SAFETY_REVIEW — ревью медицинским экспертом
  CONFIRM       — финальное подтверждение

Использование:
    from workflow_engine import recommend
    from risk_engine import score_risk
    risk   = score_risk("Доза 500 мг каждые 6 часов")
    wf     = recommend(risk)
    print(wf.summary)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from risk_engine import RiskResult


# ─────────────────────────────────────────────────────────────────────────────
# Шаги рабочего процесса
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowStep(Enum):
    TRANSLATE     = ("Перевод",          "Перевести сегмент с учётом глоссария и TM")
    QA            = ("Проверка QA",      "Проверить точность, стиль и терминологию")
    NUMERICAL_QA  = ("Числовая QA",      "Проверить все числа, дозировки и единицы измерения")
    BACK_CHECK    = ("Обратная проверка","Верифицировать обратным переводом или сравнением с источником")
    SAFETY_REVIEW = ("Ревью эксперта",   "Ревью медицинским специалистом")
    CONFIRM       = ("Подтвердить",      "Финальное подтверждение сегмента")

    @property
    def name_ru(self) -> str:
        return self.value[0]

    @property
    def description(self) -> str:
        return self.value[1]


@dataclass
class WorkflowRecommendation:
    steps: List[WorkflowStep]
    risk_level: str
    rationale: str

    @property
    def summary(self) -> str:
        """Краткая строка вида: Перевод → QA → Подтвердить"""
        return " → ".join(s.name_ru for s in self.steps)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def requires_human(self) -> bool:
        """Требует ли рабочий процесс участие человека-ревьюера."""
        return any(s in (WorkflowStep.SAFETY_REVIEW, WorkflowStep.BACK_CHECK)
                   for s in self.steps)


# ─────────────────────────────────────────────────────────────────────────────
# Правила рекомендации
# ─────────────────────────────────────────────────────────────────────────────

_LOW_STEPS = [
    WorkflowStep.TRANSLATE,
    WorkflowStep.CONFIRM,
]

_MEDIUM_STEPS = [
    WorkflowStep.TRANSLATE,
    WorkflowStep.QA,
    WorkflowStep.CONFIRM,
]

_HIGH_STEPS = [
    WorkflowStep.TRANSLATE,
    WorkflowStep.QA,
    WorkflowStep.BACK_CHECK,
    WorkflowStep.CONFIRM,
]

_CRITICAL_STEPS = [
    WorkflowStep.TRANSLATE,
    WorkflowStep.QA,
    WorkflowStep.NUMERICAL_QA,
    WorkflowStep.BACK_CHECK,
    WorkflowStep.SAFETY_REVIEW,
    WorkflowStep.CONFIRM,
]

_RATIONALE = {
    'LOW': (
        "Сегмент содержит минимальный медицинский риск. "
        "Стандартный перевод без расширенной проверки."
    ),
    'MEDIUM': (
        "Сегмент содержит медицинскую терминологию или аббревиатуры. "
        "Требуется проверка точности терминов."
    ),
    'HIGH': (
        "Сегмент содержит клинически значимую информацию: острое/хроническое состояние, "
        "анатомические направления или диагностическую лексику. "
        "Требуется обратная проверка."
    ),
    'CRITICAL': (
        "Сегмент содержит дозировки, числовые диапазоны или критические медицинские "
        "данные. Обязательны числовая QA и ревью медицинского эксперта."
    ),
}


def recommend(risk: RiskResult) -> WorkflowRecommendation:
    """
    Рекомендует рабочий процесс по результату оценки риска.

    Дополнительно добавляет NUMERICAL_QA для HIGH-уровня если
    обнаружены дозировки.
    """
    level = risk.level

    if level == 'LOW':
        steps = list(_LOW_STEPS)
    elif level == 'MEDIUM':
        steps = list(_MEDIUM_STEPS)
    elif level == 'HIGH':
        steps = list(_HIGH_STEPS)
        # HIGH + числовые дозировки → добавить NUMERICAL_QA
        if risk.needs_numerical_qa:
            steps.insert(2, WorkflowStep.NUMERICAL_QA)
    else:   # CRITICAL
        steps = list(_CRITICAL_STEPS)

    return WorkflowRecommendation(
        steps      = steps,
        risk_level = level,
        rationale  = _RATIONALE.get(level, ''),
    )
