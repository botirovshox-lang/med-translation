"""
auto_approval_engine.py — Controlled auto-approval after QA.
Only approves LOW-risk segments meeting strict safety criteria.
User must click [Run Auto Approval] button explicitly.
"""
from typing import Dict, List, Tuple
import json

from db import get_segments, update_segment, confirm_segment


class AutoApprovalEngine:
    """
    Automatically approve translations that meet strict safety criteria.

    Rules:
    - Auto-approval is OFF by default
    - User must click button explicitly
    - Only LOW risk segments eligible
    - All QA conditions must be met
    - Different rules per route (EXACT_TM, GOOGLE_SAFE, GPT)
    """

    def __init__(self, project_id: int):
        self.project_id = project_id
        self.segments = []
        self.exclusion_reasons = {}  # {segment_id: [reason1, reason2, ...]}

    def load_segments(self):
        """Load all segments for project."""
        self.segments = get_segments(self.project_id)

    def check_basic_requirements(self, seg: Dict) -> Tuple[bool, List[str]]:
        """
        Check basic requirements for any auto-approval.

        Returns:
            (eligible, list of failure reasons)
        """
        reasons = []

        # Status check: must be translated
        status = seg.get('status', '')
        if status not in ['translated', 'confirmed']:
            reasons.append('not_translated')
            return False, reasons

        # Risk level check: must be LOW
        risk_level = seg.get('risk_level', 'MEDIUM')
        if risk_level != 'LOW':
            reasons.append(f'risk_{risk_level}')
            return False, reasons

        # Target text check: must not be empty
        target_text = seg.get('target_text', '').strip()
        if not target_text:
            reasons.append('empty_target')
            return False, reasons

        # Local QA check: must have passed
        local_qa_status = seg.get('local_qa_status', '')
        if local_qa_status != 'pass':
            reasons.append(f'local_qa_{local_qa_status}')
            return False, reasons

        # QA alerts check: must not have critical alerts
        qa_alerts = seg.get('qa_alerts', '[]')
        if isinstance(qa_alerts, str):
            try:
                qa_alerts = json.loads(qa_alerts)
            except:
                qa_alerts = []

        if qa_alerts:
            alert_types = [a.get('type', 'unknown') for a in qa_alerts]
            reasons.append(f'qa_alerts:{",".join(alert_types)}')
            return False, reasons

        # Forbidden alert check
        if seg.get('forbidden_alert'):
            reasons.append('forbidden_alert')
            return False, reasons

        # Numerical check: must have passed
        numerical_passed = seg.get('numerical_qa_passed', True)
        if not numerical_passed:
            reasons.append('numerical_mismatch')
            return False, reasons

        # Consistency check: must not have conflicts
        consistency_alerts = seg.get('consistency_alerts', '[]')
        if isinstance(consistency_alerts, str):
            try:
                consistency_alerts = json.loads(consistency_alerts)
            except:
                consistency_alerts = []

        if consistency_alerts:
            reasons.append('consistency_conflict')
            return False, reasons

        # Glossary check: no glossary term issues
        glossary_issues = seg.get('glossary_issues', False)
        if glossary_issues:
            reasons.append('glossary_conflict')
            return False, reasons

        # Semantic check: no semantic alerts
        semantic_score = seg.get('google_safe_confidence', 1.0)
        if semantic_score and semantic_score < 0.95:
            reasons.append(f'semantic_alert_{semantic_score:.2f}')
            return False, reasons

        # Hallucination check: no hallucination suspicion
        if seg.get('hallucination_detected'):
            reasons.append('hallucination_suspicion')
            return False, reasons

        # All basic checks passed
        return True, []

    def check_exact_tm(self, seg: Dict) -> Tuple[bool, List[str]]:
        """
        Check if EXACT_TM segment is eligible.

        Rules:
        - route = EXACT_TM
        - LOW risk (checked by basic_requirements)
        - local QA pass (checked by basic_requirements)
        - trusted exact TM match (>= 99%)
        """
        reasons = []

        if seg.get('route') != 'EXACT_TM':
            reasons.append('route_not_exact_tm')
            return False, reasons

        # Check TM match score
        tm_score = seg.get('tm_match_score', 0)
        if tm_score < 99:
            reasons.append(f'tm_score_{tm_score}')
            return False, reasons

        # Basic requirements already checked
        return True, []

    def check_google_safe(self, seg: Dict) -> Tuple[bool, List[str]]:
        """
        Check if GOOGLE_SAFE segment is eligible.

        Rules:
        - provider = google
        - route = GOOGLE_SAFE
        - intent = metadata_simple|author_list|institution_simple
        - local QA pass
        - no entity/name corruption
        """
        reasons = []

        if seg.get('provider') != 'google':
            reasons.append('provider_not_google')
            return False, reasons

        if seg.get('route') != 'GOOGLE_SAFE':
            reasons.append('route_not_google_safe')
            return False, reasons

        # Check segment intent (only simple/metadata)
        intent = seg.get('segment_intent', '')
        allowed_intents = ['metadata_simple', 'author_list', 'institution_simple']
        if intent not in allowed_intents:
            reasons.append(f'intent_{intent}')
            return False, reasons

        # Check for entity corruption
        detected_features = seg.get('detected_features', '{}')
        if isinstance(detected_features, str):
            try:
                detected_features = json.loads(detected_features)
            except:
                detected_features = {}

        if detected_features.get('entity_corruption'):
            reasons.append('entity_corruption')
            return False, reasons

        if detected_features.get('name_corruption'):
            reasons.append('name_corruption')
            return False, reasons

        # Basic requirements already checked
        return True, []

    def check_gpt(self, seg: Dict) -> Tuple[bool, List[str]]:
        """
        Check if GPT-translated segment is eligible.

        Rules:
        - LOW risk (checked by basic_requirements)
        - QA passed if GPT QA ran
        - back-check passed if back-check ran
        - no alerts
        """
        reasons = []

        route = seg.get('route', '')
        if route not in ['GPT_REQUIRED', 'GPT_WITH_GLOSSARY_REQUIRED']:
            reasons.append(f'route_{route}')
            return False, reasons

        # Check QA final status if GPT QA was run
        qa_final_status = seg.get('qa_final_status', '')
        if qa_final_status and qa_final_status not in ['qa_passed', '']:
            reasons.append(f'qa_final_{qa_final_status}')
            return False, reasons

        # Check back-check if it was run
        back_translation = seg.get('back_translation')
        if back_translation:
            # Back-check was run, check report
            back_report = seg.get('back_translation_report', '')
            if isinstance(back_report, str) and back_report:
                try:
                    report = json.loads(back_report)
                    if not report.get('verdict') == 'passed':
                        reasons.append('back_check_failed')
                        return False, reasons
                except:
                    # Report parse error, exclude
                    reasons.append('back_check_report_error')
                    return False, reasons

        # Basic requirements already checked
        return True, []

    def check_never_auto_approve(self, seg: Dict) -> Tuple[bool, List[str]]:
        """
        Check segments that should NEVER be auto-approved.

        Never auto-approve:
        - MEDIUM/HIGH/CRITICAL risk
        - table cells
        - dosages
        - treatment protocols
        - diagnostic criteria
        - medical definitions
        - ambiguous abbreviations
        - complex official affiliations
        - any qa_warning/fail status
        """
        reasons = []

        # Risk level (already checked in basic, but double-check)
        risk_level = seg.get('risk_level', 'MEDIUM')
        if risk_level in ['MEDIUM', 'HIGH', 'CRITICAL']:
            reasons.append(f'never_auto_risk_{risk_level}')
            return False, reasons

        # Block type check
        block_type = seg.get('block_type', 'text')
        if block_type == 'table_cell':
            reasons.append('table_cell')
            return False, reasons

        # Detected features check
        detected_features = seg.get('detected_features', '{}')
        if isinstance(detected_features, str):
            try:
                detected_features = json.loads(detected_features)
            except:
                detected_features = {}

        never_auto_features = [
            'dosage', 'treatment_protocol', 'diagnostic_criteria',
            'medical_definition', 'ambiguous_abbreviation', 'complex_affiliation'
        ]

        for feature in never_auto_features:
            if detected_features.get(feature):
                reasons.append(f'never_auto_{feature}')
                return False, reasons

        return True, []

    def find_eligible_segments(self) -> Dict[int, List[str]]:
        """
        Find segments eligible for auto-approval.

        Returns:
            dict with segment_id → list of exclusion reasons (empty if eligible)
        """
        self.exclusion_reasons = {}

        for seg in self.segments:
            seg_id = seg['id']
            route = seg.get('route', '')

            # Check basic requirements first
            basic_ok, basic_reasons = self.check_basic_requirements(seg)
            if not basic_ok:
                self.exclusion_reasons[seg_id] = basic_reasons
                continue

            # Check never-auto-approve criteria
            never_ok, never_reasons = self.check_never_auto_approve(seg)
            if not never_ok:
                self.exclusion_reasons[seg_id] = never_reasons
                continue

            # Route-specific checks
            if route == 'EXACT_TM':
                route_ok, route_reasons = self.check_exact_tm(seg)
            elif route == 'GOOGLE_SAFE':
                route_ok, route_reasons = self.check_google_safe(seg)
            elif route in ['GPT_REQUIRED', 'GPT_WITH_GLOSSARY_REQUIRED']:
                route_ok, route_reasons = self.check_gpt(seg)
            else:
                # Unknown route
                route_ok, route_reasons = False, [f'route_{route}']

            if not route_ok:
                self.exclusion_reasons[seg_id] = route_reasons
            # If all checks pass, segment_id not in exclusion_reasons

        return self.exclusion_reasons

    def get_approval_preview(self) -> Dict:
        """
        Get preview of what will be approved.

        Returns:
            dict with candidates, exclusions by reason, examples
        """
        self.load_segments()
        exclusion_reasons = self.find_eligible_segments()

        # Find eligible segments (not in exclusion_reasons)
        eligible_ids = [seg['id'] for seg in self.segments
                       if seg['id'] not in exclusion_reasons]

        # Count exclusions by reason
        exclusion_counts = {}
        for seg_id, reasons in exclusion_reasons.items():
            for reason in reasons:
                exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1

        # Get example candidates
        candidates = [seg for seg in self.segments if seg['id'] in eligible_ids][:5]

        # Get example exclusions (one per top reason)
        excluded_examples = []
        for reason in sorted(exclusion_counts.keys(), key=lambda r: -exclusion_counts[r])[:5]:
            for seg_id, reasons in exclusion_reasons.items():
                if reason in reasons:
                    seg = next((s for s in self.segments if s['id'] == seg_id), None)
                    if seg:
                        excluded_examples.append({
                            'id': seg_id,
                            'source': seg.get('source_text', '')[:50],
                            'reason': reason,
                        })
                        break

        return {
            'candidates_count': len(eligible_ids),
            'excluded_count': len(exclusion_reasons),
            'exclusion_reasons': exclusion_counts,
            'example_candidates': [{
                'id': c['id'],
                'source': c.get('source_text', '')[:50],
                'route': c.get('route', '?'),
                'risk': c.get('risk_level', '?'),
            } for c in candidates],
            'example_excluded': excluded_examples,
        }

    def execute_auto_approval(self, progress_callback=None) -> Dict:
        """
        Execute auto-approval for eligible segments.

        Returns:
            dict with approval_count, failed_count, details
        """
        self.load_segments()
        exclusion_reasons = self.find_eligible_segments()

        # Find eligible segments
        eligible_ids = set(seg['id'] for seg in self.segments
                          if seg['id'] not in exclusion_reasons)

        approved_count = 0
        failed_count = 0
        errors = []

        for seg in self.segments:
            if seg['id'] not in eligible_ids:
                continue

            seg_id = seg['id']

            try:
                if progress_callback:
                    progress_callback(f"Approving segment {seg_id}...")

                # Confirm segment using existing function
                confirm_segment(seg_id)

                # Update metadata
                update_segment(seg_id, {
                    'approval_source': 'auto_approval_engine',
                    'auto_approved': True,
                })

                approved_count += 1

            except Exception as e:
                failed_count += 1
                errors.append({
                    'segment_id': seg_id,
                    'error': str(e),
                })

        if progress_callback:
            progress_callback(f"Auto-approval complete: {approved_count} approved, {failed_count} failed")

        return {
            'approved_count': approved_count,
            'failed_count': failed_count,
            'errors': errors,
            'excluded_count': len(exclusion_reasons),
            'exclusion_summary': {
                'total': len(exclusion_reasons),
                'by_reason': self._summarize_exclusions(exclusion_reasons),
            }
        }

    def _summarize_exclusions(self, exclusion_reasons: Dict[int, List[str]]) -> Dict:
        """Summarize exclusion reasons."""
        summary = {}
        for seg_id, reasons in exclusion_reasons.items():
            for reason in reasons:
                summary[reason] = summary.get(reason, 0) + 1
        return summary


def get_auto_approval_preview(project_id: int) -> Dict:
    """Quick entry point for preview."""
    engine = AutoApprovalEngine(project_id)
    return engine.get_approval_preview()


def run_auto_approval(project_id: int, progress_callback=None) -> Dict:
    """Quick entry point for approval execution."""
    engine = AutoApprovalEngine(project_id)
    return engine.execute_auto_approval(progress_callback)
