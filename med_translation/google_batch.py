"""
google_batch.py — Conservative batch translation for GOOGLE_SAFE segments only.
Uses local QA, no auto-confirm, preserves safety constraints.
"""
from typing import Dict, List, Tuple
from db import connect, update_segment, get_segments
from google_translate import translate_google, GOOGLE_TRANSLATE_AVAILABLE
from local_qa_engine import run_local_qa
from forbidden_checker import post_check


class GoogleBatchTranslator:
    """
    Batch translate GOOGLE_SAFE segments using Google Cloud Translation API.

    Constraints:
    - Only route = GOOGLE_SAFE (google_safe_confidence >= 0.98)
    - Only status in ['new', 'untranslated', '']
    - Run local QA after translation
    - Save as google_draft (not confirmed)
    - Never auto-confirm
    """

    def __init__(self, project_id: int, batch_size: int = 50):
        self.project_id = project_id
        self.batch_size = batch_size
        self.segments = []
        self.eligible_segments = []

    def load_segments(self):
        """Load all segments for project."""
        self.segments = get_segments(self.project_id)
        return len(self.segments)

    def find_eligible_segments(self) -> List[Dict]:
        """
        Find segments eligible for Google batch translation.

        Criteria:
        - route = 'GOOGLE_SAFE'
        - status in ['new', 'untranslated', None, '']
        - google_safe_confidence >= 0.98
        - no target_text yet
        """
        eligible = []

        for seg in self.segments:
            # Check route
            if seg.get('route') != 'GOOGLE_SAFE':
                continue

            # Check status
            status = seg.get('status', '').lower().strip()
            if status not in ['new', 'untranslated', 'tm_prefilled', '']:
                continue

            # Check confidence
            confidence = seg.get('google_safe_confidence', 0)
            if confidence < 0.98:
                continue

            # Check if already translated
            if seg.get('target_text'):
                continue

            eligible.append(seg)

        self.eligible_segments = eligible
        return eligible

    def get_preview(self) -> Dict:
        """
        Get preview of what will be translated.

        Returns:
            dict with:
            - eligible_count: int
            - batch_count: int (how many batches)
            - estimated_cost_usd: float
            - estimated_gpt_savings_usd: float
            - examples_included: list[dict]
            - examples_excluded: list[dict with reason]
        """
        self.find_eligible_segments()

        eligible_count = len(self.eligible_segments)
        batch_count = (eligible_count + self.batch_size - 1) // self.batch_size

        # Estimate cost: Google Translate is ~$20/1M characters
        total_chars = sum(len(seg.get('source_text', '')) for seg in self.eligible_segments)
        estimated_cost_usd = round((total_chars / 1_000_000) * 20, 2)

        # Estimated GPT savings: ~$0.008 per segment (translate + QA)
        estimated_gpt_savings = round(eligible_count * 0.008, 2)

        # Get examples (first 3 eligible, first 3 excluded)
        examples_included = [
            {
                'id': seg['id'],
                'source_text': seg['source_text'][:100],
                'risk_level': seg.get('risk_level'),
                'confidence': f"{seg.get('google_safe_confidence', 0):.2f}",
            }
            for seg in self.eligible_segments[:3]
        ]

        examples_excluded = []
        for seg in self.segments[:50]:  # Check first 50 segments for examples
            if seg in self.eligible_segments:
                continue

            reason = None
            if seg.get('route') != 'GOOGLE_SAFE':
                reason = f"Route: {seg.get('route')}"
            elif seg.get('target_text'):
                reason = "Already translated"
            elif seg.get('google_safe_confidence', 0) < 0.98:
                reason = f"Confidence: {seg.get('google_safe_confidence', 0):.2f}"

            if reason:
                examples_excluded.append({
                    'id': seg['id'],
                    'source_text': seg.get('source_text', '')[:100],
                    'reason': reason,
                })

            if len(examples_excluded) >= 3:
                break

        return {
            'eligible_count': eligible_count,
            'batch_count': batch_count,
            'batch_size': self.batch_size,
            'estimated_cost_usd': estimated_cost_usd,
            'estimated_gpt_savings_usd': estimated_gpt_savings,
            'examples_included': examples_included,
            'examples_excluded': examples_excluded,
        }

    def translate_batch(self, progress_callback=None) -> Dict:
        """
        Execute batch translation.

        Returns:
            dict with:
            - translated_count: int
            - failed_count: int
            - qa_failed_count: int
            - total_cost_usd: float
            - results: list of {segment_id, status, qa_result}
        """
        if not GOOGLE_TRANSLATE_AVAILABLE:
            raise ValueError("Google Translate API not available")

        self.find_eligible_segments()

        translated_count = 0
        failed_count = 0
        qa_failed_count = 0
        total_cost_usd = 0.0
        results = []

        # Process in batches
        for batch_num in range(0, len(self.eligible_segments), self.batch_size):
            batch_segments = self.eligible_segments[batch_num : batch_num + self.batch_size]

            if progress_callback:
                progress_callback(f"Processing batch {batch_num // self.batch_size + 1}...")

            for seg in batch_segments:
                try:
                    source_text = seg.get('source_text', '')

                    # Translate via Google
                    target_text = translate_google(source_text, source_lang='ru', target_lang='en')

                    if not target_text:
                        results.append({
                            'segment_id': seg['id'],
                            'status': 'failed',
                            'reason': 'Empty translation',
                        })
                        failed_count += 1
                        continue

                    # Run local QA
                    qa_result = run_local_qa(source_text, target_text, severity_level='warning')

                    # Determine status based on QA
                    if qa_result.passed:
                        status = 'google_draft'
                    else:
                        status = 'google_needs_review'
                        qa_failed_count += 1

                    # Save segment
                    update_data = {
                        'target_text': target_text,
                        'provider': 'google',
                        'status': status,
                        'estimated_total_usd': 0,  # Already paid via Google API
                    }

                    # Store QA alerts if any
                    if qa_result.alerts:
                        import json
                        update_data['qa_alerts'] = json.dumps(qa_result.alerts)

                    update_segment(seg['id'], update_data)

                    translated_count += 1

                    results.append({
                        'segment_id': seg['id'],
                        'status': status,
                        'qa_alerts': qa_result.alerts,
                    })

                    # Estimate cost
                    char_count = len(source_text)
                    cost = (char_count / 1_000_000) * 20  # $20 per 1M chars
                    total_cost_usd += cost

                except Exception as e:
                    failed_count += 1
                    results.append({
                        'segment_id': seg['id'],
                        'status': 'error',
                        'error': str(e),
                    })

        return {
            'translated_count': translated_count,
            'failed_count': failed_count,
            'qa_failed_count': qa_failed_count,
            'total_cost_usd': round(total_cost_usd, 2),
            'results': results,
        }


def translate_google_batch(project_id: int, batch_size: int = 50, preview_only: bool = False):
    """
    Quick entry point for batch translation.

    Args:
        project_id: int
        batch_size: int — default 50 segments/request
        preview_only: bool — if True, return preview only

    Returns:
        dict with preview or translation results
    """
    translator = GoogleBatchTranslator(project_id, batch_size)
    translator.load_segments()

    if preview_only:
        return translator.get_preview()
    else:
        return translator.translate_batch()
