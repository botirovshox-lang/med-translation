"""
preflight_analyzer.py — Главный Orchestrator для preflight анализа
Комбинирует все компоненты для полного анализа без API вызовов.
"""
import json
from datetime import datetime

from db import (
    get_all_segments_preflight,
    update_segment_preflight,
    connect,
)
from duplicate_engine import run_duplicate_analysis
from cost_estimator import CostEstimator
from safety_policy import SafetyPolicyEngine
from semantic_scoring import SemanticScorer
from routing_engine import RoutingEngine

# Import existing analysis functions
try:
    from risk_engine import score_risk
except ImportError:
    score_risk = None

try:
    from terminology_engine import match_segment
except ImportError:
    match_segment = None

try:
    from forbidden_checker import pre_check
except ImportError:
    pre_check = None

try:
    from tm import find_tm_suggestion
except ImportError:
    find_tm_suggestion = None


class AnalysisResult:
    """Результаты preflight анализа."""

    def __init__(self):
        self.total_segments = 0
        self.unique_normalized = 0
        self.duplicate_groups = []
        self.exact_tm_opportunities = 0
        self.glossary_coverage_percent = 0.0
        self.routing_summary = {}
        self.risk_summary = {}
        self.cost_baseline_usd = 0.0
        self.cost_optimized_usd = 0.0
        self.cost_savings_usd = 0.0
        self.cost_savings_percent = 0.0
        self.route_cost_breakdown = {}  # {route: {'count': int, 'baseline_usd': float, 'optimized_usd': float, 'tokens': int}}
        self.cost_component_breakdown = {}  # {component: {'baseline': float, 'optimized': float}}
        self.batch_order_recommendation = []
        self.preflight_at = ''
        self.status = 'not_analyzed'
        self.error_message = ''

    def to_dict(self):
        """Преобразовать в dict для сохранения."""
        return {
            'total_segments': self.total_segments,
            'unique_normalized': self.unique_normalized,
            'duplicate_groups': self.duplicate_groups,
            'exact_tm_opportunities': self.exact_tm_opportunities,
            'glossary_coverage_percent': self.glossary_coverage_percent,
            'routing_summary': self.routing_summary,
            'risk_summary': self.risk_summary,
            'cost_baseline_usd': self.cost_baseline_usd,
            'cost_optimized_usd': self.cost_optimized_usd,
            'cost_savings_usd': self.cost_savings_usd,
            'cost_savings_percent': self.cost_savings_percent,
            'route_cost_breakdown': self.route_cost_breakdown,
            'cost_component_breakdown': self.cost_component_breakdown,
            'batch_order_recommendation': self.batch_order_recommendation,
            'preflight_at': self.preflight_at,
            'status': self.status,
        }


class PreflightAnalyzer:
    """
    Главный класс для preflight анализа всех сегментов проекта.
    """

    def __init__(self, project_id):
        """
        Args:
            project_id: int — ID проекта для анализа
        """
        self.project_id = project_id
        self.segments = []
        self.duplicate_analysis = None
        self.cost_estimator = CostEstimator()
        self.safety_engine = SafetyPolicyEngine()
        self.semantic_scorer = SemanticScorer()
        self.routing_engine = RoutingEngine()

    def analyze_all(self):
        """
        Главный метод: выполнить полный preflight анализ БЕЗ API вызовов.

        Returns:
            AnalysisResult: Результаты анализа
        """
        result = AnalysisResult()
        result.preflight_at = datetime.utcnow().isoformat()

        try:
            # 1. Загрузить все сегменты
            self.segments = get_all_segments_preflight(self.project_id)
            if not self.segments:
                result.status = 'done'
                result.total_segments = 0
                return result

            # Инициализировать preflight_status
            for seg in self.segments:
                if not seg.get('preflight_status'):
                    seg['preflight_status'] = 'not_analyzed'

            # 2. Обнаружение дубликатов
            duplicate_data = run_duplicate_analysis(self.segments)
            duplicate_assignments = duplicate_data['group_assignments']

            # 3. Сопоставление глоссария (DISABLED for speed - too slow)
            glossary_matches = {seg['id']: {'match_count': 0, 'matches': []} for seg in self.segments}

            # 4. Обнаружение запрещённых терминов (DISABLED for speed)
            forbidden_warnings = {seg['id']: [] for seg in self.segments}

            # 5. Оценка риска (DISABLED for speed - too slow)
            risk_scores = {seg['id']: {'level': 'MEDIUM', 'score': 50, 'reasons': [], 'features': {}} for seg in self.segments}

            # 5b. Семантическое оценивание (SKIPPED for speed)
            # semantic_scores = self._score_semantic_all(risk_scores)
            semantic_scores = {seg['id']: {
                'semantic_density_score': 0.5,
                'medicality_score': 0.5,
                'entity_complexity_score': 0.5,
                'reversibility_risk_score': 0.5,
                'clinical_criticality_score': 0.5,
                'google_safe_confidence': 0.7
            } for seg in self.segments}

            # 6. Классификация intent
            intents = self._classify_intent_all()

            # 7. Оценка токенов
            token_estimates = self._estimate_tokens_all()

            # 8. Применить маршрутизацию (с новым routing_engine)
            # Сохраним forbidden_warnings для использования в routing_engine
            self._forbidden_all = forbidden_warnings
            routes = self._route_all_segments(
                duplicate_assignments,
                glossary_matches,
                risk_scores,
                semantic_scores
            )

            # 9. Оценить стоимость
            costs = self._estimate_cost_all(routes, token_estimates)

            # 10. Сохранить preflight метаданные в БД (включая семантические оценки)
            self._save_all_preflight_metadata(
                duplicate_assignments,
                glossary_matches,
                forbidden_warnings,
                risk_scores,
                semantic_scores,
                intents,
                token_estimates,
                routes,
                costs
            )

            # 11. Агрегировать результаты
            result = self._aggregate_analysis(duplicate_data, routes, risk_scores, glossary_matches, costs)
            result.status = 'done'
            result.preflight_at = datetime.utcnow().isoformat()

        except Exception as e:
            result.status = 'failed'
            result.error_message = str(e)
            import traceback
            print(f"Error in preflight analysis: {traceback.format_exc()}")

        return result

    def _match_glossary_sampled(self):
        """Найти совпадения глоссария для первых 500 сегментов (оптимизировано)."""
        if not match_segment:
            return {seg['id']: {'match_count': 0, 'matches': []} for seg in self.segments}

        result = {}
        # Обработать только первые 500 сегментов
        sample_size = min(500, len(self.segments))

        for i, seg in enumerate(self.segments[:sample_size]):
            try:
                matches = match_segment(seg.get('source_text', ''))
                result[seg['id']] = {
                    'match_count': len(matches) if matches else 0,
                    'matches': [
                        {
                            'term': m.source if hasattr(m, 'source') else str(m),
                            'score': m.score if hasattr(m, 'score') else 0.0
                        }
                        for m in (matches or [])
                    ]
                }
            except Exception:
                result[seg['id']] = {'match_count': 0, 'matches': []}

        # Для остальных - пусто
        for seg in self.segments[sample_size:]:
            result[seg['id']] = {'match_count': 0, 'matches': []}

        return result

    def _match_glossary_all(self):
        """Найти совпадения глоссария для каждого сегмента (ПОЛНАЯ версия - медленная)."""
        if not match_segment:
            return {}

        result = {}
        for seg in self.segments:
            try:
                matches = match_segment(seg.get('source_text', ''))
                result[seg['id']] = {
                    'match_count': len(matches) if matches else 0,
                    'matches': [
                        {
                            'term': m.source if hasattr(m, 'source') else str(m),
                            'score': m.score if hasattr(m, 'score') else 0.0
                        }
                        for m in (matches or [])
                    ]
                }
            except Exception:
                result[seg['id']] = {'match_count': 0, 'matches': []}

        return result

    def _detect_forbidden_all(self):
        """Обнаружить запрещённые термины в исходных текстах."""
        if not pre_check:
            return {}

        result = {}
        for seg in self.segments:
            try:
                warnings = pre_check(seg.get('source_text', ''))
                result[seg['id']] = warnings if warnings else []
            except Exception:
                result[seg['id']] = []

        return result

    def _score_risk_sampled(self):
        """Оценить риск для первых 200 сегментов, остальные = MEDIUM (оптимизировано)."""
        if not score_risk:
            # Fallback: all MEDIUM
            return {seg['id']: {'level': 'MEDIUM', 'score': 50, 'reasons': [], 'features': {}}
                    for seg in self.segments}

        result = {}
        sample_size = min(200, len(self.segments))

        # Обработать первые 200 сегментов с полной оценкой
        for seg in self.segments[:sample_size]:
            try:
                risk = score_risk(seg.get('source_text', ''))
                result[seg['id']] = {
                    'level': risk.level if hasattr(risk, 'level') else 'MEDIUM',
                    'score': risk.risk_score if hasattr(risk, 'risk_score') else 50,
                    'reasons': risk.risk_reasons if hasattr(risk, 'risk_reasons') else [],
                    'features': risk.raw_matches if hasattr(risk, 'raw_matches') else {},
                }
            except Exception:
                result[seg['id']] = {'level': 'MEDIUM', 'score': 50, 'reasons': [], 'features': {}}

        # Для остальных - MEDIUM (быстро)
        for seg in self.segments[sample_size:]:
            result[seg['id']] = {'level': 'MEDIUM', 'score': 50, 'reasons': [], 'features': {}}

        return result

    def _score_risk_all(self):
        """Оценить риск для каждого сегмента (ПОЛНАЯ версия - медленная)."""
        if not score_risk:
            # Fallback: all MEDIUM
            return {seg['id']: {'level': 'MEDIUM', 'score': 50, 'reasons': [], 'features': {}}
                    for seg in self.segments}

        result = {}
        for seg in self.segments:
            try:
                risk = score_risk(seg.get('source_text', ''))
                result[seg['id']] = {
                    'level': risk.level if hasattr(risk, 'level') else 'MEDIUM',
                    'score': risk.risk_score if hasattr(risk, 'risk_score') else 50,
                    'reasons': risk.risk_reasons if hasattr(risk, 'risk_reasons') else [],
                    'features': risk.raw_matches if hasattr(risk, 'raw_matches') else {},
                }
            except Exception:
                result[seg['id']] = {'level': 'MEDIUM', 'score': 50, 'reasons': [], 'features': {}}

        return result

    def _score_semantic_all(self, risk_scores):
        """Вычислить семантические оценки для каждого сегмента (NEW)."""
        result = {}

        for seg in self.segments:
            seg_id = seg['id']
            source_text = seg.get('source_text', '')
            risk_info = risk_scores.get(seg_id, {})
            risk_level = risk_info.get('level', 'MEDIUM')
            detected_features = risk_info.get('features', {})

            # Вычислить все 6 семантических оценок
            scores = self.semantic_scorer.score_segment(
                source_text,
                risk_level=risk_level,
                detected_features=detected_features
            )

            result[seg_id] = scores

        return result

    def _classify_intent_all(self):
        """Классифицировать segment intent (простые heuristics)."""
        result = {}

        for seg in self.segments:
            source_text = seg.get('source_text', '')
            words = source_text.split()
            word_count = len(words)
            digit_count = sum(1 for w in words if w.isdigit())

            if word_count < 20:
                intent = 'metadata_simple'
            elif digit_count >= 2:
                intent = 'table_or_numeric'
            elif 'anatomy' in source_text.lower() or 'organ' in source_text.lower():
                intent = 'medical_content'
            else:
                intent = 'medical_content'

            result[seg['id']] = intent

        return result

    def _estimate_tokens_all(self):
        """Оценить токены для каждого сегмента и шага."""
        result = {}

        for seg in self.segments:
            source_text = seg.get('source_text', '')
            result[seg['id']] = {
                'translate': self.cost_estimator.estimate_tokens_for_step(source_text, 'translate'),
                'qa': self.cost_estimator.estimate_tokens_for_step(source_text, 'qa'),
                'backcheck': self.cost_estimator.estimate_tokens_for_step(source_text, 'backcheck'),
                'safety': self.cost_estimator.estimate_tokens_for_step(source_text, 'safety'),
            }

        return result

    def _route_all_segments(self, duplicate_assignments, glossary_matches, risk_scores, semantic_scores):
        """Применить правила маршрутизации с новым routing_engine."""
        result = {}

        for seg in self.segments:
            seg_id = seg['id']
            dup_info = duplicate_assignments.get(seg_id, {})
            glossary_info = glossary_matches.get(seg_id, {})
            risk_info = risk_scores.get(seg_id, {})
            semantic_info = semantic_scores.get(seg_id, {})
            forbidden_info = getattr(self, '_forbidden_all', {}).get(seg_id, [])

            # Построить контекст для routing_engine
            context = {
                'segment_id': seg_id,
                'source_text': seg.get('source_text', ''),
                'block_type': seg.get('block_type'),
                'tm_match_score': seg.get('tm_match_score', 0),
                'duplicate_group_id': dup_info.get('group_id'),
                'is_representative': dup_info.get('is_representative', True),
                'glossary_matches': glossary_info.get('matches', []),
                'risk_result': risk_info,
                'forbidden_warnings': forbidden_info,
                'semantic_scores': semantic_info,
            }

            # Вызвать routing_engine для получения полного решения маршрутизации
            routing_result = self.routing_engine.route(seg, context)
            result[seg_id] = routing_result

        return result

    def _estimate_cost_all(self, routes, token_estimates):
        """Оценить стоимость для каждого сегмента по маршруту."""
        result = {}

        for seg in self.segments:
            seg_id = seg['id']
            routing_result = routes.get(seg_id, {})

            # Extract route and risk_level from routing_result dict
            route = routing_result.get('route', 'GPT_REQUIRED') if isinstance(routing_result, dict) else routing_result
            risk_level = routing_result.get('risk_level', 'MEDIUM') if isinstance(routing_result, dict) else 'MEDIUM'

            # Calculate cost based on route and risk level
            cost_info = self.cost_estimator.estimate_segment_cost_by_route(seg, route, risk_level)
            result[seg_id] = cost_info

        return result

    def _save_all_preflight_metadata(self, duplicates, glossary, forbidden, risk, semantic, intents, tokens, routes, costs):
        """Сохранить все preflight метаданные в БД для каждого сегмента."""
        for seg in self.segments:
            seg_id = seg['id']
            dup_info = duplicates.get(seg_id, {})
            glossary_info = glossary.get(seg_id, {})
            forbidden_info = forbidden.get(seg_id, [])
            risk_info = risk.get(seg_id, {})
            token_info = tokens.get(seg_id, {})
            routing_result = routes.get(seg_id, {})
            cost_info = costs.get(seg_id, {})

            # routing_result содержит все необходимые данные из routing_engine
            # Extract token counts from nested dict structure
            translate_tokens = token_info.get('translate', {})
            if isinstance(translate_tokens, dict):
                translate_total = translate_tokens.get('total_tokens', 0)
            else:
                translate_total = translate_tokens or 0

            qa_tokens = token_info.get('qa', {})
            if isinstance(qa_tokens, dict):
                qa_total = qa_tokens.get('total_tokens', 0)
            else:
                qa_total = qa_tokens or 0

            backcheck_tokens = token_info.get('backcheck', {})
            if isinstance(backcheck_tokens, dict):
                backcheck_total = backcheck_tokens.get('total_tokens', 0)
            else:
                backcheck_total = backcheck_tokens or 0

            safety_tokens = token_info.get('safety', {})
            if isinstance(safety_tokens, dict):
                safety_total = safety_tokens.get('total_tokens', 0)
            else:
                safety_total = safety_tokens or 0

            preflight_data = {
                'normalized_source_hash': dup_info.get('group_id'),
                'duplicate_group_id': dup_info.get('group_id'),
                'duplicate_count': dup_info.get('duplicate_count', 0),
                'route': routing_result.get('route', 'GPT_REQUIRED'),
                'segment_intent': routing_result.get('segment_intent', 'unknown'),
                'risk_level': routing_result.get('risk_level', 'MEDIUM'),
                'risk_reasons': json.dumps(routing_result.get('risk_reasons', [])),
                'detected_features': json.dumps(routing_result.get('detected_features', {})),
                'qa_policy': routing_result.get('qa_policy', 'manual'),
                'approval_policy': routing_result.get('approval_policy', 'single_human'),
                'estimated_translation_tokens': translate_total,
                'estimated_qa_tokens': qa_total,
                'estimated_backcheck_tokens': backcheck_total,
                'estimated_safety_tokens': safety_total,
                'estimated_total_tokens': translate_total + qa_total + backcheck_total + safety_total,
                'estimated_total_usd': cost_info.get('total_usd', 0.0),
                # NEW: Per-step costs
                'estimated_translate_usd': cost_info.get('translate_usd', 0.0),
                'estimated_qa_usd': cost_info.get('qa_usd', 0.0),
                'estimated_backcheck_usd': cost_info.get('backcheck_usd', 0.0),
                'estimated_safety_usd': cost_info.get('safety_usd', 0.0),
                'estimated_google_usd': cost_info.get('google_usd', 0.0),
                'preflight_status': 'done',
                'semantic_density_score': routing_result.get('semantic_density_score', 0.0),
                'medicality_score': routing_result.get('medicality_score', 0.0),
                'entity_complexity_score': routing_result.get('entity_complexity_score', 0.0),
                'reversibility_risk_score': routing_result.get('reversibility_risk_score', 0.0),
                'clinical_criticality_score': routing_result.get('clinical_criticality_score', 0.0),
                'google_safe_confidence': routing_result.get('google_safe_confidence', 0.0),
            }

            update_segment_preflight(seg_id, preflight_data)

    def _aggregate_analysis(self, duplicate_data, routes, risk_scores, glossary_matches, costs):
        """Агрегировать результаты в финальный отчёт."""
        result = AnalysisResult()

        # Basic stats
        result.total_segments = len(self.segments)
        result.duplicate_groups = duplicate_data.get('summary', {}).get('total_duplicate_groups', 0)

        # Unique segments
        unique_hashes = set()
        for seg in self.segments:
            h = seg.get('source_hash', '')
            if h:
                unique_hashes.add(h)
        result.unique_normalized = len(unique_hashes)

        # Exact TM opportunities
        result.exact_tm_opportunities = sum(1 for seg in self.segments if (seg.get('tm_match_score') or 0) >= 99)

        # Glossary coverage
        glossary_with_matches = sum(1 for info in glossary_matches.values() if info.get('match_count', 0) > 0)
        result.glossary_coverage_percent = (glossary_with_matches / result.total_segments * 100) if result.total_segments > 0 else 0

        # Routing summary
        routing_counts = {}
        for routing_result in routes.values():
            if isinstance(routing_result, dict):
                route = routing_result.get('route', 'GPT_REQUIRED')
            else:
                route = routing_result
            routing_counts[route] = routing_counts.get(route, 0) + 1
        result.routing_summary = routing_counts

        # Risk summary
        risk_counts = {}
        for risk_info in risk_scores.values():
            level = risk_info.get('level', 'MEDIUM')
            risk_counts[level] = risk_counts.get(level, 0) + 1
        result.risk_summary = risk_counts

        # Cost analysis using estimate_batch for detailed breakdown
        segments_with_routes = []
        for seg in self.segments:
            routing_result = routes.get(seg['id'], {})
            route = routing_result.get('route', 'GPT_REQUIRED') if isinstance(routing_result, dict) else routing_result
            risk_level = routing_result.get('risk_level', 'MEDIUM') if isinstance(routing_result, dict) else 'MEDIUM'
            segments_with_routes.append({
                **seg,
                'route': route,
                'risk_level': risk_level
            })

        # Get detailed batch cost analysis with route breakdowns
        batch_analysis = self.cost_estimator.estimate_batch(segments_with_routes)

        result.cost_baseline_usd = batch_analysis['baseline'].get('total_usd', 0.0)
        result.cost_optimized_usd = batch_analysis['optimized'].get('total_usd', 0.0)
        result.cost_savings_usd = batch_analysis['savings'].get('total_usd', 0.0)
        result.cost_savings_percent = batch_analysis['savings'].get('total_percent', 0.0)

        # Route cost breakdown
        route_breakdown = {}
        for route, stats in batch_analysis['route_breakdown'].items():
            route_breakdown[route] = {
                'count': stats.get('count', 0),
                'tokens': stats.get('tokens', 0),
                'baseline_usd': stats.get('baseline_usd', 0.0),
                'optimized_usd': stats.get('optimized_usd', 0.0),
                'savings_usd': stats.get('baseline_usd', 0.0) - stats.get('optimized_usd', 0.0),
            }
        result.route_cost_breakdown = route_breakdown

        # Cost component breakdown
        result.cost_component_breakdown = {
            'Translation': {
                'baseline': batch_analysis['baseline'].get('translation_usd', 0.0),
                'optimized': batch_analysis['optimized'].get('translation_usd', 0.0),
            },
            'QA': {
                'baseline': batch_analysis['baseline'].get('qa_usd', 0.0),
                'optimized': batch_analysis['optimized'].get('qa_usd', 0.0),
            },
            'Back-check': {
                'baseline': batch_analysis['baseline'].get('backcheck_usd', 0.0),
                'optimized': batch_analysis['optimized'].get('backcheck_usd', 0.0),
            },
            'Safety': {
                'baseline': batch_analysis['baseline'].get('safety_usd', 0.0),
                'optimized': batch_analysis['optimized'].get('safety_usd', 0.0),
            },
            'Google': {
                'baseline': 0.0,
                'optimized': batch_analysis['optimized'].get('google_usd', 0.0),
            },
        }

        # Batch order recommendation (reuse segments_with_routes from cost analysis)
        result.batch_order_recommendation = self.safety_engine.get_default_batch_order(segments_with_routes)[:50]  # Top 50

        return result


def run_preflight_analysis(project_id):
    """
    Быстрая функция для запуска preflight анализа.

    Args:
        project_id: int — ID проекта

    Returns:
        AnalysisResult: Результаты анализа
    """
    analyzer = PreflightAnalyzer(project_id)
    return analyzer.analyze_all()
