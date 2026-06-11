"""
qa_orchestrator.py — Full-file QA orchestration.
Coordinates 6-stage QA pipeline for entire translated project.

Stage 1: Local QA (all segments, no API)
Stage 2: Consistency QA (all project, no API)
Stage 3: Adaptive GPT QA (route/risk dependent)
Stage 4: Numerical QA (medical content dependent)
Stage 5: Back-check (high-risk/uncertainty dependent)
Stage 6: Final QA decision (per-segment status)
"""
from typing import Dict, List, Tuple
import json

from db import get_segments, get_glossary, update_segment
from local_qa_engine import run_local_qa
from consistency_engine import ConsistencyEngine
from qa_scheduler import QAScheduler
from numerical_qa_engine import run_numerical_qa
from pipeline import qa_segment, back_translate_check, safety_decision
from forbidden_checker import post_check


class QAOrchestrator:
    """
    Orchestrate full-file QA for translated project.

    Ensures every translated segment receives QA status while balancing
    cost efficiency with medical safety.
    """

    def __init__(self, project_id: int, model: str = 'gpt-4o-mini'):
        self.project_id = project_id
        self.model = model
        self.segments = []
        self.glossary = []
        self.scheduler = QAScheduler()
        self.consistency_engine = ConsistencyEngine()

    def load_project_data(self):
        """Load segments and glossary for project."""
        self.segments = get_segments(self.project_id)
        try:
            self.glossary = get_glossary(self.project_id)
        except:
            self.glossary = []

    def stage1_local_qa_all(self) -> Dict:
        """
        Stage 1: Run local QA on all translated segments.

        No API calls. Pure local heuristics.

        Returns:
            dict with local_qa_results per segment_id
        """
        results = {}

        for seg in self.segments:
            seg_id = seg['id']
            source = seg.get('source_text', '')
            target = seg.get('target_text', '')
            status = seg.get('status', '')

            # Only QA segments that have been translated
            if status not in ['translated', 'confirmed']:
                results[seg_id] = {
                    'local_qa_status': 'not_translated',
                    'alerts': [],
                }
                continue

            if not target:
                results[seg_id] = {
                    'local_qa_status': 'fail',
                    'alerts': [{'type': 'empty_target', 'severity': 'critical', 'message': 'Empty translation'}],
                }
                continue

            # Run local QA
            local_qa_result = run_local_qa(source, target, severity_level='warning')

            # Determine status
            if local_qa_result.passed:
                local_qa_status = 'pass'
            else:
                # Check severity of alerts
                has_critical = any(a['severity'] == 'critical' for a in local_qa_result.alerts)
                has_error = any(a['severity'] == 'error' for a in local_qa_result.alerts)

                if has_critical:
                    local_qa_status = 'fail'
                elif has_error:
                    local_qa_status = 'fail'
                else:
                    local_qa_status = 'warning'

            results[seg_id] = {
                'local_qa_status': local_qa_status,
                'alerts': local_qa_result.alerts,
            }

            # Save to DB
            update_segment(seg_id, {
                'qa_alerts': json.dumps(local_qa_result.alerts),
                'local_qa_status': local_qa_status,
            })

        return results

    def stage2_consistency_qa(self, local_qa_results: Dict) -> Dict:
        """
        Stage 2: Project-wide consistency checks.

        No API calls. Detects inconsistencies across segments.

        Returns:
            dict with consistency_alerts by segment_id
        """
        # Run consistency engine
        overall_passed, consistency_alerts = self.consistency_engine.run_consistency_qa(
            self.segments,
            self.glossary
        )

        # Map alerts to segment IDs
        segment_consistency = {}
        for seg in self.segments:
            segment_consistency[seg['id']] = {
                'consistency_alerts': [],
                'has_consistency_issue': False,
            }

        for alert in consistency_alerts:
            for seg_id in alert.segment_ids:
                segment_consistency[seg_id]['consistency_alerts'].append(alert.to_dict())
                segment_consistency[seg_id]['has_consistency_issue'] = True

        # Save to DB
        for seg_id, consistency_data in segment_consistency.items():
            if consistency_data['consistency_alerts']:
                update_segment(seg_id, {
                    'consistency_alerts': json.dumps(consistency_data['consistency_alerts']),
                })

        return segment_consistency

    def stage3_adaptive_qa_plan(self, local_qa_results: Dict, consistency_results: Dict) -> Dict:
        """
        Stage 3: Determine which segments need GPT QA and how deep.

        Returns:
            dict with qa_depth_scheduled per segment_id
        """
        qa_plan = {}

        for seg in self.segments:
            seg_id = seg['id']
            status = seg.get('status', '')

            if status not in ['translated', 'confirmed']:
                qa_plan[seg_id] = {
                    'qa_depth': 'none',
                    'reason': 'not_translated',
                    'should_run_gpt_qa': False,
                    'should_run_back_check': False,
                }
                continue

            # Determine base QA depth
            qa_depth = self.scheduler.schedule_qa_depth(seg)

            # Upgrade if local QA found issues
            local_status = local_qa_results.get(seg_id, {}).get('local_qa_status', 'pass')
            if local_status in ['warning', 'fail']:
                qa_depth = self.scheduler.upgrade_qa_depth(qa_depth, 'local_qa_warning')

            # Upgrade if consistency issues
            consistency_data = consistency_results.get(seg_id, {})
            if consistency_data.get('has_consistency_issue', False):
                qa_depth = self.scheduler.upgrade_qa_depth(qa_depth, 'consistency_conflict')

            # Check if needs back-check
            needs_back_check = self.scheduler.needs_back_check(
                qa_depth,
                local_status
            )

            should_run_gpt_qa = qa_depth in [
                'local_plus_light_gpt',
                'full_medical_qa',
                'full_medical_qa_backcheck',
                'critical_full_review'
            ]

            qa_plan[seg_id] = {
                'qa_depth': qa_depth,
                'reason': local_status,
                'should_run_gpt_qa': should_run_gpt_qa,
                'should_run_back_check': needs_back_check,
                'local_qa_status': local_status,
            }

        return qa_plan

    def stage4_numerical_qa(self, qa_plan: Dict) -> Dict:
        """
        Stage 4: Run numerical QA for medical content.

        Detects dosage, unit, lab value issues.

        Returns:
            dict with numerical_qa_results per segment_id
        """
        results = {}

        for seg in self.segments:
            seg_id = seg['id']
            source = seg.get('source_text', '')
            target = seg.get('target_text', '')
            status = seg.get('status', '')

            if status not in ['translated', 'confirmed'] or not target:
                results[seg_id] = {
                    'needs_numerical_qa': False,
                    'numerical_issues': [],
                }
                continue

            # Check if segment needs numerical QA
            needs_numerical = self.scheduler.needs_numerical_qa(seg)

            if not needs_numerical:
                results[seg_id] = {
                    'needs_numerical_qa': False,
                    'numerical_issues': [],
                }
                continue

            # Run numerical QA
            numerical_result = run_numerical_qa(source, target)

            results[seg_id] = {
                'needs_numerical_qa': True,
                'numerical_issues': numerical_result.issues,
                'numerical_passed': numerical_result.passed,
            }

            # Upgrade QA depth if numerical issues found
            if not numerical_result.passed:
                current_depth = qa_plan[seg_id]['qa_depth']
                upgraded = self.scheduler.upgrade_qa_depth(current_depth, 'numerical_mismatch')
                if upgraded != current_depth:
                    qa_plan[seg_id]['qa_depth'] = upgraded
                    qa_plan[seg_id]['should_run_gpt_qa'] = True

            # Save to DB
            update_segment(seg_id, {
                'numerical_qa_issues': json.dumps(numerical_result.issues),
                'numerical_qa_passed': numerical_result.passed,
            })

        return results

    def stage5_back_check_scheduling(self, qa_plan: Dict) -> Dict:
        """
        Stage 5: Schedule back-checks for high-risk segments.

        Determines which segments should get back-translation checks.

        Returns:
            dict with back_check_status per segment_id
        """
        back_check_plan = {}

        for seg_id, plan in qa_plan.items():
            back_check_plan[seg_id] = {
                'should_run_back_check': plan.get('should_run_back_check', False),
                'qa_depth': plan.get('qa_depth'),
            }

        return back_check_plan

    def stage6_final_qa_decision(self, local_qa_results: Dict, qa_plan: Dict,
                                 numerical_results: Dict, back_check_results: Dict = None) -> Dict:
        """
        Stage 6: Final QA decision for each segment.

        Produces final QA status and depth used.

        Returns:
            dict with qa_final_status per segment_id
        """
        final_decisions = {}

        for seg in self.segments:
            seg_id = seg['id']
            status = seg.get('status', '')

            if status not in ['translated', 'confirmed']:
                final_decisions[seg_id] = {
                    'qa_final_status': 'not_applicable',
                    'qa_depth_used': 'none',
                    'reason': 'not_translated',
                }
                continue

            local_status = local_qa_results.get(seg_id, {}).get('local_qa_status', 'pass')
            qa_depth = qa_plan.get(seg_id, {}).get('qa_depth', 'local_only')
            numerical_passed = numerical_results.get(seg_id, {}).get('numerical_passed', True)

            # Determine final status
            if local_status == 'fail':
                final_status = 'qa_failed'
            elif local_status == 'warning':
                final_status = 'qa_warning'
            elif not numerical_passed:
                final_status = 'qa_warning'
            elif qa_depth == 'critical_full_review':
                final_status = 'human_review_required'
            else:
                final_status = 'qa_passed'

            # Estimate cost
            token_estimate = self.scheduler.estimate_qa_tokens(qa_depth, seg.get('source_text', ''))
            cost_estimate = self.scheduler.estimate_qa_cost_usd(token_estimate)

            final_decisions[seg_id] = {
                'qa_final_status': final_status,
                'qa_depth_used': qa_depth,
                'local_qa_status': local_status,
                'estimated_qa_tokens': sum(token_estimate.values()),
                'estimated_qa_usd': cost_estimate,
            }

            # Save to DB
            update_segment(seg_id, {
                'qa_final_status': final_status,
                'qa_depth_used': qa_depth,
                'estimated_qa_usd': cost_estimate,
            })

        return final_decisions

    def orchestrate_full_qa(self, progress_callback=None) -> Dict:
        """
        Execute full 6-stage QA pipeline.

        Returns:
            dict with:
            - stage1_results
            - stage2_results
            - stage3_results
            - stage4_results
            - stage5_results
            - stage6_results
            - summary (counts and costs)
        """
        if progress_callback:
            progress_callback("Loading project data...")
        self.load_project_data()

        if progress_callback:
            progress_callback("Stage 1: Running local QA on all segments...")
        stage1_results = self.stage1_local_qa_all()

        if progress_callback:
            progress_callback("Stage 2: Running consistency checks...")
        stage2_results = self.stage2_consistency_qa(stage1_results)

        if progress_callback:
            progress_callback("Stage 3: Creating adaptive QA plan...")
        stage3_results = self.stage3_adaptive_qa_plan(stage1_results, stage2_results)

        if progress_callback:
            progress_callback("Stage 4: Running numerical QA...")
        stage4_results = self.stage4_numerical_qa(stage3_results)

        if progress_callback:
            progress_callback("Stage 5: Scheduling back-checks...")
        stage5_results = self.stage5_back_check_scheduling(stage3_results)

        if progress_callback:
            progress_callback("Stage 6: Final QA decisions...")
        stage6_results = self.stage6_final_qa_decision(
            stage1_results,
            stage3_results,
            stage4_results,
            stage5_results
        )

        # Generate summary
        summary = self._generate_summary(
            stage1_results,
            stage3_results,
            stage6_results
        )

        if progress_callback:
            progress_callback(f"QA complete! {summary['total_translated']} segments analyzed.")

        return {
            'stage1_results': stage1_results,
            'stage2_results': stage2_results,
            'stage3_results': stage3_results,
            'stage4_results': stage4_results,
            'stage5_results': stage5_results,
            'stage6_results': stage6_results,
            'summary': summary,
        }

    def _generate_summary(self, stage1_results: Dict, stage3_results: Dict,
                         stage6_results: Dict) -> Dict:
        """Generate QA summary statistics."""
        total_translated = sum(1 for r in stage1_results.values()
                              if r['local_qa_status'] != 'not_translated')
        local_qa_pass = sum(1 for r in stage1_results.values()
                           if r['local_qa_status'] == 'pass')
        local_qa_warning = sum(1 for r in stage1_results.values()
                              if r['local_qa_status'] == 'warning')
        local_qa_fail = sum(1 for r in stage1_results.values()
                           if r['local_qa_status'] == 'fail')

        gpt_qa_needed = sum(1 for r in stage3_results.values()
                           if r.get('should_run_gpt_qa', False))
        back_check_needed = sum(1 for r in stage3_results.values()
                               if r.get('should_run_back_check', False))

        final_passed = sum(1 for r in stage6_results.values()
                          if r['qa_final_status'] == 'qa_passed')
        final_warning = sum(1 for r in stage6_results.values()
                           if r['qa_final_status'] == 'qa_warning')
        final_failed = sum(1 for r in stage6_results.values()
                          if r['qa_final_status'] == 'qa_failed')
        final_human_review = sum(1 for r in stage6_results.values()
                                if r['qa_final_status'] == 'human_review_required')

        estimated_qa_cost = sum(r.get('estimated_qa_usd', 0) for r in stage6_results.values())

        return {
            'total_translated': total_translated,
            'local_qa_pass': local_qa_pass,
            'local_qa_warning': local_qa_warning,
            'local_qa_fail': local_qa_fail,
            'gpt_qa_needed': gpt_qa_needed,
            'back_check_needed': back_check_needed,
            'final_passed': final_passed,
            'final_warning': final_warning,
            'final_failed': final_failed,
            'final_human_review': final_human_review,
            'estimated_qa_usd': round(estimated_qa_cost, 2),
        }


def run_full_qa_orchestration(project_id: int, model: str = 'gpt-4o-mini',
                             progress_callback=None) -> Dict:
    """Quick entry point for full QA orchestration."""
    orchestrator = QAOrchestrator(project_id, model)
    return orchestrator.orchestrate_full_qa(progress_callback)
