"""
review_queue_engine.py — Review Queue for problematic segments.
Finds, prioritizes, and manages segments needing manual review.
All actions update existing segment records (no separate DB).
"""
from typing import Dict, List, Tuple
import json


class ReviewQueueEngine:
    """
    Manage review queue for segments with QA issues, alerts, or low confidence.

    Statuses that trigger review queue:
    - google_needs_review
    - qa_warning
    - qa_failed
    - human_review_required
    - glossary_conflict
    - numeric_alert
    - consistency_alert
    - semantic_alert
    - backcheck_low
    - forbidden_detected
    """

    # Priority levels (higher = more urgent)
    PRIORITY_LEVELS = {
        'CRITICAL': 100,
        'HIGH': 80,
        'MEDIUM': 50,
        'LOW': 20,
    }

    # Alert type priorities (urgency within same risk level)
    ALERT_PRIORITIES = {
        'forbidden_detected': 95,
        'numeric_mismatch': 90,
        'semantic_drift': 85,
        'entity_corruption': 85,
        'name_corruption': 85,
        'glossary_conflict': 70,
        'consistency_conflict': 65,
        'qa_warning': 60,
        'qa_failed': 60,
        'google_needs_review': 50,
        'backcheck_low': 40,
    }

    def __init__(self, segments: List[Dict]):
        self.segments = segments
        self.review_queue = []

    def identify_problematic_segments(self) -> List[Dict]:
        """
        Find all segments that need review.

        Criteria:
        - status in ['translated', 'google_draft', 'google_needs_review']
        - Has one of: qa_warning, qa_failed, human_review_required, etc.
        """
        problematic = []

        for seg in self.segments:
            status = seg.get('status', '')
            if status not in ['translated', 'google_draft', 'google_needs_review']:
                continue

            # Check for review-triggering conditions
            needs_review = False
            alerts = []

            # QA status checks
            local_qa_status = seg.get('local_qa_status', '')
            if local_qa_status in ['warning', 'fail']:
                needs_review = True
                alerts.append(f'local_qa_{local_qa_status}')

            qa_final_status = seg.get('qa_final_status', '')
            if qa_final_status in ['qa_warning', 'qa_failed', 'human_review_required']:
                needs_review = True
                alerts.append(qa_final_status)

            # Provider-specific checks
            provider = seg.get('provider', '')
            if provider == 'google' and status == 'google_needs_review':
                needs_review = True
                alerts.append('google_needs_review')

            # QA alerts check
            qa_alerts = seg.get('qa_alerts', '[]')
            if isinstance(qa_alerts, str):
                try:
                    qa_alerts = json.loads(qa_alerts)
                except:
                    qa_alerts = []

            if qa_alerts:
                needs_review = True
                for alert in qa_alerts:
                    alerts.append(alert.get('type', 'unknown_alert'))

            # Consistency alerts
            consistency_alerts = seg.get('consistency_alerts', '[]')
            if isinstance(consistency_alerts, str):
                try:
                    consistency_alerts = json.loads(consistency_alerts)
                except:
                    consistency_alerts = []

            if consistency_alerts:
                needs_review = True
                alerts.append('consistency_conflict')

            # Numerical issues
            numerical_passed = seg.get('numerical_qa_passed', True)
            if not numerical_passed:
                needs_review = True
                alerts.append('numeric_mismatch')

            # Glossary issues
            glossary_issues = seg.get('glossary_issues', False)
            if glossary_issues:
                needs_review = True
                alerts.append('glossary_conflict')

            # Forbidden alerts
            if seg.get('forbidden_alert'):
                needs_review = True
                alerts.append('forbidden_detected')

            # Hallucination
            if seg.get('hallucination_detected'):
                needs_review = True
                alerts.append('hallucination_detected')

            # Back-check issues
            back_translation = seg.get('back_translation')
            if back_translation:
                back_report = seg.get('back_translation_report', '')
                if isinstance(back_report, str) and back_report:
                    try:
                        report = json.loads(back_report)
                        if not report.get('verdict') == 'passed':
                            needs_review = True
                            alerts.append('backcheck_low')
                    except:
                        pass

            if needs_review:
                problematic.append({
                    'segment': seg,
                    'alerts': list(set(alerts)),  # Remove duplicates
                })

        return problematic

    def calculate_priority(self, seg: Dict, alerts: List[str]) -> int:
        """
        Calculate priority score for a segment.

        Higher score = more urgent.

        Factors:
        1. Risk level (CRITICAL > HIGH > MEDIUM > LOW)
        2. Alert type (forbidden > numeric > semantic > glossary > consistency)
        3. Whether it's completed/in-progress
        """
        score = 0

        # Risk level (base priority)
        risk_level = seg.get('risk_level', 'MEDIUM')
        score += self.PRIORITY_LEVELS.get(risk_level, 50)

        # Alert type (boost)
        for alert in alerts:
            alert_base = alert.split('_')[0]  # e.g., 'numeric' from 'numeric_mismatch'
            boost = self.ALERT_PRIORITIES.get(alert, 30)
            score = max(score, boost + self.PRIORITY_LEVELS.get(risk_level, 50))

        # Status boost (confirmed should not be in queue, but if it is, lower priority)
        status = seg.get('status', '')
        if status == 'google_draft':
            score += 10  # Slightly lower priority for drafts
        elif status in ['translated']:
            pass  # Normal priority

        return score

    def get_review_queue(self, filters: Dict = None) -> List[Dict]:
        """
        Get prioritized review queue.

        Args:
            filters: dict with 'route', 'risk', 'provider', 'alert_type', 'status'

        Returns:
            List of segments with priority, sorted by priority (descending)
        """
        problematic = self.identify_problematic_segments()

        # Apply filters
        if filters:
            problematic = self._apply_filters(problematic, filters)

        # Calculate priority and sort
        prioritized = []
        for item in problematic:
            seg = item['segment']
            alerts = item['alerts']

            priority = self.calculate_priority(seg, alerts)
            top_alert = alerts[0] if alerts else 'unknown'

            prioritized.append({
                'id': seg['id'],
                'source_text': seg.get('source_text', '')[:100],
                'target_text': seg.get('target_text', '')[:100],
                'route': seg.get('route', '?'),
                'provider': seg.get('provider', '?'),
                'risk_level': seg.get('risk_level', '?'),
                'qa_final_status': seg.get('qa_final_status', ''),
                'status': seg.get('status', ''),
                'local_qa_status': seg.get('local_qa_status', ''),
                'top_alert': top_alert,
                'alerts': alerts,
                'priority': priority,
                'segment': seg,  # Full segment for detailed view
            })

        # Sort by priority (descending)
        prioritized.sort(key=lambda x: (-x['priority'], x['id']))

        return prioritized

    def _apply_filters(self, problematic: List[Dict], filters: Dict) -> List[Dict]:
        """Apply filters to problematic segments."""
        filtered = problematic

        if 'route' in filters and filters['route']:
            filtered = [item for item in filtered
                       if item['segment'].get('route') == filters['route']]

        if 'risk' in filters and filters['risk']:
            filtered = [item for item in filtered
                       if item['segment'].get('risk_level') == filters['risk']]

        if 'provider' in filters and filters['provider']:
            filtered = [item for item in filtered
                       if item['segment'].get('provider') == filters['provider']]

        if 'alert_type' in filters and filters['alert_type']:
            alert_type = filters['alert_type']
            filtered = [item for item in filtered
                       if alert_type in item['alerts']]

        if 'status' in filters and filters['status']:
            filtered = [item for item in filtered
                       if item['segment'].get('status') == filters['status']]

        return filtered

    def get_segment_details(self, segment_id: int) -> Dict:
        """
        Get detailed information about a segment for review.

        Returns:
            dict with all relevant QA/alert information
        """
        seg = next((s for s in self.segments if s['id'] == segment_id), None)
        if not seg:
            return {}

        # Parse JSON fields
        qa_alerts = seg.get('qa_alerts', '[]')
        if isinstance(qa_alerts, str):
            try:
                qa_alerts = json.loads(qa_alerts)
            except:
                qa_alerts = []

        consistency_alerts = seg.get('consistency_alerts', '[]')
        if isinstance(consistency_alerts, str):
            try:
                consistency_alerts = json.loads(consistency_alerts)
            except:
                consistency_alerts = []

        numerical_issues = seg.get('numerical_qa_issues', '[]')
        if isinstance(numerical_issues, str):
            try:
                numerical_issues = json.loads(numerical_issues)
            except:
                numerical_issues = []

        back_report = seg.get('back_translation_report', '')
        if isinstance(back_report, str) and back_report:
            try:
                back_report = json.loads(back_report)
            except:
                back_report = {}

        # Get glossary conflicts (simplified - check if glossary_issues flag set)
        glossary_conflicts = []
        if seg.get('glossary_issues'):
            glossary_conflicts = [{'issue': 'Glossary term mismatch or missing'}]

        return {
            'id': seg['id'],
            'source_text': seg.get('source_text', ''),
            'target_text': seg.get('target_text', ''),
            'route': seg.get('route', ''),
            'provider': seg.get('provider', ''),
            'risk_level': seg.get('risk_level', ''),
            'status': seg.get('status', ''),
            'qa_alerts': qa_alerts,
            'consistency_alerts': consistency_alerts,
            'numerical_issues': numerical_issues,
            'glossary_conflicts': glossary_conflicts,
            'forbidden_alert': seg.get('forbidden_alert', False),
            'hallucination_detected': seg.get('hallucination_detected', False),
            'back_translation': seg.get('back_translation', ''),
            'back_translation_report': back_report,
            'suggested_action': self._suggest_action(seg, qa_alerts, consistency_alerts),
        }

    def _suggest_action(self, seg: Dict, qa_alerts: List, consistency_alerts: List) -> str:
        """Suggest what action to take for this segment."""
        risk_level = seg.get('risk_level', 'MEDIUM')
        qa_status = seg.get('qa_final_status', '')
        provider = seg.get('provider', '')

        # CRITICAL risk
        if risk_level == 'CRITICAL':
            return 'Requires expert medical review. Do not approve without domain expert.'

        # Forbidden detected
        if seg.get('forbidden_alert'):
            return 'Forbidden term detected. Edit translation to replace or rephrase.'

        # Back-check failed
        back_report = seg.get('back_translation_report', '')
        if back_report:
            try:
                report = json.loads(back_report) if isinstance(back_report, str) else back_report
                if not report.get('verdict') == 'passed':
                    return 'Back-check failed. Review source/target alignment. Rerun back-check after editing.'
            except:
                pass

        # Numerical issues
        if not seg.get('numerical_qa_passed', True):
            return 'Numerical validation failed. Check dosages, units, ranges, and decimal places.'

        # Consistency conflicts
        if consistency_alerts:
            return f'Translation inconsistent with {len(consistency_alerts)} other segment(s). Align translations.'

        # QA warnings
        if qa_status == 'qa_warning':
            return 'QA found issues. Edit and rerun local QA. Rerun GPT QA if needed.'

        # Google needs review
        if provider == 'google' and seg.get('status') == 'google_needs_review':
            return 'Google translation flagged. Review for clinical accuracy. Edit if needed.'

        # High risk
        if risk_level == 'HIGH':
            return 'High-risk segment. Review carefully. Rerun QA after any edits.'

        # Default
        return 'Review and approve if correct. Rerun local QA after editing.'

    def get_statistics(self) -> Dict:
        """Get review queue statistics."""
        queue = self.get_review_queue()

        stats = {
            'total_in_queue': len(queue),
            'by_risk': {},
            'by_alert_type': {},
            'by_status': {},
        }

        for item in queue:
            # Risk breakdown
            risk = item['risk_level']
            stats['by_risk'][risk] = stats['by_risk'].get(risk, 0) + 1

            # Alert type breakdown
            for alert in item['alerts']:
                stats['by_alert_type'][alert] = stats['by_alert_type'].get(alert, 0) + 1

            # Status breakdown
            status = item['status']
            stats['by_status'][status] = stats['by_status'].get(status, 0) + 1

        return stats


def get_review_queue(segments: List[Dict], filters: Dict = None) -> List[Dict]:
    """Quick entry point for review queue."""
    engine = ReviewQueueEngine(segments)
    return engine.get_review_queue(filters)


def get_segment_review_details(segments: List[Dict], segment_id: int) -> Dict:
    """Quick entry point for segment details."""
    engine = ReviewQueueEngine(segments)
    return engine.get_segment_details(segment_id)


def get_review_statistics(segments: List[Dict]) -> Dict:
    """Quick entry point for statistics."""
    engine = ReviewQueueEngine(segments)
    return engine.get_statistics()
