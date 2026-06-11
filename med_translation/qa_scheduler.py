"""
qa_scheduler.py — Adaptive QA scheduling based on route, risk, and anomalies.
Determines QA depth for each segment to balance safety and cost.
"""
from typing import Dict, List


class QAScheduler:
    """
    Determine optimal QA depth for each segment.

    Depth levels:
    - local_only: Run local checks only
    - local_plus_light_gpt: Local checks + light GPT QA
    - full_medical_qa: Local + full GPT medical QA
    - full_medical_qa_backcheck: Local + GPT + back-check
    - critical_full_review: Local + GPT + back-check + human review required
    """

    def __init__(self):
        pass

    def schedule_qa_depth(self, segment: Dict) -> str:
        """
        Determine QA depth for a segment based on multiple factors.

        Args:
            segment: Segment dict with routing, risk, provider, and preflight data

        Returns:
            qa_depth: one of above levels
        """
        route = segment.get('route', 'UNKNOWN')
        risk_level = segment.get('risk_level', 'MEDIUM')
        provider = segment.get('provider', 'unknown')
        status = segment.get('status', 'new')

        # CRITICAL risk → full review regardless of route
        if risk_level == 'CRITICAL':
            return 'critical_full_review'

        # HIGH risk → full medical QA + back-check
        if risk_level == 'HIGH':
            return 'full_medical_qa_backcheck'

        # Route-specific rules
        if route == 'EXACT_TM':
            # TM already validated, local checks only
            return 'local_only'

        if route == 'DUPLICATE_PROPAGATION_PENDING':
            # Reuse representative's QA
            return 'local_only'

        if route == 'GOOGLE_SAFE':
            # Google translated: local QA mandatory
            # GPT QA only if anomalies detected
            # Will be upgraded if local QA flags issues
            return 'local_only'

        if route == 'GPT_REQUIRED':
            # Medium risk by default
            # If translated by GPT, light QA should catch issues
            if risk_level == 'MEDIUM':
                return 'local_plus_light_gpt'
            else:  # LOW risk
                return 'local_only'

        if route == 'GPT_WITH_GLOSSARY_REQUIRED':
            # Glossary injection needed, higher sensitivity
            if risk_level == 'MEDIUM':
                return 'full_medical_qa'
            else:  # LOW risk
                return 'local_plus_light_gpt'

        if route == 'HUMAN_REVIEW_REQUIRED':
            return 'critical_full_review'

        # Default: medium risk gets light GPT QA
        return 'local_plus_light_gpt'

    def upgrade_qa_depth(self, current_depth: str, reason: str) -> str:
        """
        Upgrade QA depth if anomalies or concerns detected.

        Args:
            current_depth: Current QA depth level
            reason: Why upgrading (anomaly type)

        Returns:
            upgraded_depth: Same or higher level
        """
        depth_hierarchy = [
            'local_only',
            'local_plus_light_gpt',
            'full_medical_qa',
            'full_medical_qa_backcheck',
            'critical_full_review'
        ]

        current_idx = depth_hierarchy.index(current_depth) if current_depth in depth_hierarchy else 1

        # Determine upgrade amount
        if reason in ['forbidden_term_detected', 'critical_anomaly', 'entity_corruption']:
            # Critical issues require full review
            return 'critical_full_review'
        elif reason in ['consistency_conflict', 'glossary_conflict', 'semantic_uncertainty']:
            # Medium issues require back-check
            if current_idx < depth_hierarchy.index('full_medical_qa_backcheck'):
                return 'full_medical_qa_backcheck'
        elif reason in ['local_qa_warning', 'light_gpt_issue']:
            # Minor issues require full medical QA
            if current_idx < depth_hierarchy.index('full_medical_qa'):
                return 'full_medical_qa'

        # No upgrade needed
        return current_depth

    def needs_numerical_qa(self, segment: Dict) -> bool:
        """
        Check if segment needs numerical QA.

        Returns True for segments with:
        - Numbers, dosages, units
        - Lab values, percentages, ranges
        - Table cells with clinical content
        """
        source_text = segment.get('source_text', '')
        detected_features = segment.get('detected_features', {})

        if isinstance(detected_features, str):
            import json
            detected_features = json.loads(detected_features)

        # Check for clinical numerical features
        has_numbers = any(c.isdigit() for c in source_text)
        has_dosage = detected_features.get('dosage', False)
        has_lab_values = detected_features.get('lab_values', False)
        has_numeric_range = detected_features.get('numeric_range', False)

        return has_numbers and (has_dosage or has_lab_values or has_numeric_range)

    def needs_back_check(self, qa_depth: str, local_qa_status: str = None,
                        semantic_score: float = None) -> bool:
        """
        Determine if back-check is needed.

        Args:
            qa_depth: Current QA depth
            local_qa_status: Result of local QA (pass/warning/fail)
            semantic_score: Semantic uncertainty score (0-1)

        Returns:
            True if back-check should be scheduled
        """
        # Back-check always runs for high-depth QA
        if qa_depth in ['full_medical_qa_backcheck', 'critical_full_review']:
            return True

        # Back-check for local QA warnings/failures
        if local_qa_status in ['warning', 'fail']:
            return True

        # Back-check for high semantic uncertainty
        if semantic_score and semantic_score >= 0.7:
            return True

        return False

    def estimate_qa_tokens(self, qa_depth: str, source_text: str) -> Dict[str, int]:
        """
        Estimate tokens needed for QA at different depths.

        Returns:
            dict with 'light_qa', 'full_qa', 'back_check' token counts
        """
        # Rough estimate: ~1 token per 4 chars
        source_tokens = len(source_text) / 4

        # Light QA: ~800 tokens (prompt overhead)
        light_qa_tokens = int(800)

        # Full medical QA: ~1200 tokens (detailed check)
        full_qa_tokens = int(1200)

        # Back-check: ~1500 tokens (prompt + back-translation)
        back_check_tokens = int(source_tokens + 1500)

        result = {
            'light_qa': 0,
            'full_qa': 0,
            'back_check': 0,
        }

        if qa_depth == 'local_only':
            # No API tokens
            pass
        elif qa_depth == 'local_plus_light_gpt':
            result['light_qa'] = light_qa_tokens
        elif qa_depth == 'full_medical_qa':
            result['full_qa'] = full_qa_tokens
        elif qa_depth == 'full_medical_qa_backcheck':
            result['full_qa'] = full_qa_tokens
            result['back_check'] = back_check_tokens
        elif qa_depth == 'critical_full_review':
            result['full_qa'] = full_qa_tokens
            result['back_check'] = back_check_tokens

        return result

    def estimate_qa_cost_usd(self, tokens_dict: Dict[str, int]) -> float:
        """
        Estimate USD cost for QA tokens.

        Uses GPT-4o-mini pricing: ~$0.00015 input, $0.0006 output
        Average: ~$0.0001/token
        """
        total_tokens = sum(tokens_dict.values())
        return round(total_tokens * 0.0001, 4)
