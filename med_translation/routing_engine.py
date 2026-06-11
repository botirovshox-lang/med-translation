"""
routing_engine.py — Intelligent routing orchestrator.
Combines structural classification, semantic scores, risk, glossary, and TM signals.
Core principle: How safe is it to NOT use GPT?
Google allowed ONLY if google_safe_confidence >= 0.98.
"""

from structural_classifier import classify_segment


class RoutingEngine:
    """
    Main routing orchestrator.
    Input: segment + all analysis results
    Output: route + intent + risk_level + all scores + detected_features
    """

    def __init__(self):
        self.classifier = classify_segment

    def route(self, segment, analysis_context):
        """
        Make routing decision.

        Args:
            segment: dict with 'id', 'source_text', 'block_type'
            analysis_context: dict with:
                - tm_match_score (0-100)
                - duplicate_group_id, is_representative
                - glossary_matches (list)
                - risk_result (from risk_engine)
                - forbidden_warnings (list)
                - semantic_scores (from semantic_scorer)
                - block_type (DOCX block type if available)

        Returns:
            dict: {
                'route': str,
                'segment_intent': str,
                'risk_level': str,
                'semantic_density_score': float,
                'medicality_score': float,
                'entity_complexity_score': float,
                'reversibility_risk_score': float,
                'clinical_criticality_score': float,
                'google_safe_confidence': float,
                'detected_features': dict,
                'risk_reasons': list,
                'qa_policy': str,
                'approval_policy': str,
                'routing_reason': str,
            }
        """
        source_text = segment.get('source_text', '')
        seg_id = segment.get('id')
        block_type = segment.get('block_type') or analysis_context.get('block_type')

        # Step 1: Classify segment intent structurally
        intent_result = self.classifier(source_text, block_type)
        segment_intent = intent_result['intent']
        intent_patterns = intent_result['detected_patterns']

        # Step 2: Get semantic scores
        semantic_scores = analysis_context.get('semantic_scores', {})
        semantic_density = semantic_scores.get('semantic_density_score', 0.0)
        medicality = semantic_scores.get('medicality_score', 0.0)
        entity_complexity = semantic_scores.get('entity_complexity_score', 0.0)
        reversibility_risk = semantic_scores.get('reversibility_risk_score', 0.0)
        clinical_criticality = semantic_scores.get('clinical_criticality_score', 0.0)
        google_safe_confidence = semantic_scores.get('google_safe_confidence', 0.0)

        # Step 3: Get risk analysis
        risk_result = analysis_context.get('risk_result', {})
        risk_level = risk_result.get('level', 'MEDIUM')
        risk_reasons = risk_result.get('risk_reasons', [])
        risk_features = risk_result.get('raw_matches', {})

        # Step 4: Get TM and duplicate info
        tm_match_score = analysis_context.get('tm_match_score', 0)
        duplicate_group_id = analysis_context.get('duplicate_group_id')
        is_representative = analysis_context.get('is_representative', True)

        # Step 5: Get glossary and forbidden info
        glossary_matches = analysis_context.get('glossary_matches', [])
        forbidden_warnings = analysis_context.get('forbidden_warnings', [])

        # Merge detected features from all sources
        detected_features = dict(risk_features or {})
        for key, value in intent_patterns.items():
            if key not in detected_features:
                detected_features[key] = value

        # Step 6: Make routing decision (priority order)
        routing_reason = ''

        # Rule 1: EXACT_TM (>= 99%)
        if tm_match_score and tm_match_score >= 99:
            route = 'EXACT_TM'
            routing_reason = f'Exact TM match ({tm_match_score:.0f}%)'
        # Rule 2: Duplicates
        elif duplicate_group_id is not None:
            if is_representative:
                route = 'DUPLICATE_REPRESENTATIVE'
                routing_reason = 'First segment in duplicate group'
            else:
                route = 'DUPLICATE_PROPAGATION_PENDING'
                routing_reason = 'Copy from representative'
        # Rule 3: CRITICAL risk → human review
        elif risk_level == 'CRITICAL':
            route = 'HUMAN_REVIEW_REQUIRED'
            routing_reason = 'CRITICAL risk level requires human review'
        # Rule 4: HIGH risk + glossary → GPT with glossary
        elif risk_level == 'HIGH':
            if glossary_matches or medicality > 0.5:
                route = 'GPT_WITH_GLOSSARY_REQUIRED'
                routing_reason = 'HIGH risk + medical terminology requires glossary injection'
            else:
                route = 'HUMAN_REVIEW_REQUIRED'
                routing_reason = 'HIGH risk without glossary requires human review'
        # Rule 5: Simple metadata/author lists → Google if safe
        elif segment_intent in ['metadata_simple', 'author_list']:
            if google_safe_confidence >= 0.98:
                route = 'GOOGLE_SAFE'
                routing_reason = f'Simple metadata, Google safe confidence {google_safe_confidence:.2f}'
            else:
                route = 'GPT_REQUIRED'
                routing_reason = f'Metadata but Google confidence insufficient ({google_safe_confidence:.2f} < 0.98)'
        # Rule 6: Complex affiliation/institution → GPT
        elif segment_intent in ['biography_or_affiliation', 'institution_complex']:
            route = 'GPT_REQUIRED'
            routing_reason = f'{segment_intent} requires GPT to avoid distortion'
        # Rule 7: Table/numeric with clinical content → human/GPT
        elif segment_intent == 'table_or_numeric':
            if clinical_criticality > 0.5:
                route = 'HUMAN_REVIEW_REQUIRED'
                routing_reason = f'Clinical criticality {clinical_criticality:.2f} in numeric content'
            else:
                route = 'GPT_REQUIRED'
                routing_reason = 'Numeric/tabular content requires precise translation'
        # Rule 8: Glossary-heavy medical → GPT with glossary
        elif len(glossary_matches) >= 2 or medicality > 0.6:
            route = 'GPT_WITH_GLOSSARY_REQUIRED'
            routing_reason = 'Medical terminology requires glossary-aware translation'
        # Rule 9: Forbidden terms detected → human
        elif forbidden_warnings:
            route = 'HUMAN_REVIEW_REQUIRED'
            routing_reason = f'Forbidden terms detected: {forbidden_warnings[0] if forbidden_warnings else "unknown"}'
        # Rule 10: Google Safe if confidence >= 0.98
        elif google_safe_confidence >= 0.98:
            route = 'GOOGLE_SAFE'
            routing_reason = f'Low risk, Google safe confidence {google_safe_confidence:.2f}'
        # Rule 11: Uncertain → default to GPT (positive safety logic)
        else:
            route = 'GPT_REQUIRED'
            routing_reason = f'Uncertain safety profile (confidence {google_safe_confidence:.2f}), default to GPT'

        # Step 7: Determine QA and approval policies based on risk
        qa_policy = self._select_qa_policy(risk_level)
        approval_policy = self._select_approval_policy(risk_level)

        return {
            'route': route,
            'segment_intent': segment_intent,
            'risk_level': risk_level,
            'semantic_density_score': round(semantic_density, 3),
            'medicality_score': round(medicality, 3),
            'entity_complexity_score': round(entity_complexity, 3),
            'reversibility_risk_score': round(reversibility_risk, 3),
            'clinical_criticality_score': round(clinical_criticality, 3),
            'google_safe_confidence': round(google_safe_confidence, 3),
            'detected_features': detected_features,
            'risk_reasons': risk_reasons,
            'qa_policy': qa_policy,
            'approval_policy': approval_policy,
            'routing_reason': routing_reason,
        }

    def _select_qa_policy(self, risk_level):
        """QA strictness based on risk level."""
        if risk_level == 'CRITICAL':
            return 'strict'
        elif risk_level == 'HIGH':
            return 'strict'
        elif risk_level == 'MEDIUM':
            return 'manual'
        else:  # LOW
            return 'auto_pass'

    def _select_approval_policy(self, risk_level):
        """Approval requirements based on risk level."""
        if risk_level == 'CRITICAL':
            return 'dual_human'
        elif risk_level == 'HIGH':
            return 'single_human'
        elif risk_level == 'MEDIUM':
            return 'single_human'
        else:  # LOW
            return 'automated'

    def get_route_explanation(self, route):
        """Human-readable explanation of route."""
        explanations = {
            'EXACT_TM': 'Use existing translation from memory',
            'DUPLICATE_REPRESENTATIVE': 'First segment in duplicate group — translate once',
            'DUPLICATE_PROPAGATION_PENDING': 'Copy translation from duplicate representative',
            'GOOGLE_SAFE': 'Low-risk metadata — use Google Translate (free)',
            'GPT_REQUIRED': 'Standard medical content — use OpenAI GPT',
            'GPT_WITH_GLOSSARY_REQUIRED': 'Glossary-heavy medical — inject terminology context',
            'HUMAN_REVIEW_REQUIRED': 'Critical or uncertain — requires human translator',
        }
        return explanations.get(route, 'Unknown route')


def route_segment(segment, analysis_context):
    """Fast entry point."""
    engine = RoutingEngine()
    return engine.route(segment, analysis_context)
