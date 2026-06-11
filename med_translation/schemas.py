"""
schemas.py — Pydantic модели для структурированных ответов от OpenAI (v5.5)
"""
from pydantic import BaseModel, Field
from typing import List, Optional

class TermItem(BaseModel):
    source_term: str
    target_term: str
    category: str
    confidence: float

class TermExtractionResult(BaseModel):
    terms: List[TermItem]

class SegmentQAReport(BaseModel):
    accuracy_score: float = Field(ge=0, le=100)
    terminology_score: float = Field(ge=0, le=100)
    completeness_score: float = Field(ge=0, le=100)
    numerical_score: float = Field(ge=0, le=100)
    overall_score: float = Field(ge=0, le=100)
    critical_issues: List[str]
    minor_issues: List[str]
    corrected_translation: str
    verdict: str = Field(description="pass|warning|fail")

class BackTranslationReport(BaseModel):
    back_translation: str
    semantic_score: float = Field(ge=0, le=100, description="0-100")
    meaning_drift: List[str]
    omissions: List[str]
    additions: List[str]
    verdict: str = Field(description="pass|warning|fail")

class SafetyDecisionReport(BaseModel):
    safety_status: str = Field(description="safe_to_confirm|needs_review|high_risk")
    reason: str
    what_user_should_check: List[str]
    source_meaning_summary: str
    back_translation_meaning_summary: str
    glossary_risks: List[str]
    qa_risks: List[str]
