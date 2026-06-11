"""
gpt_batch.py — Controlled GPT batch translation for GPT_REQUIRED and GPT_WITH_GLOSSARY_REQUIRED
Integrated with Segment Editor, respects token limits, minimal glossary/TM injection.
"""
from typing import Dict, List, Tuple
from db import connect, get_segments, update_segment
from pipeline import translate_segment
from terminology_engine import match_segment
from tm import find_tm_suggestion


class GPTBatchTranslator:
    """
    Batch translate segments using OpenAI with controlled costs.

    Constraints:
    - Only GPT_REQUIRED or GPT_WITH_GLOSSARY_REQUIRED routes
    - Only status in ['new', 'untranslated', '']
    - Skip EXACT_TM, GOOGLE_SAFE, duplicate pending
    - Group by: route, risk, block_type, approximate length
    - Minimal glossary injection (matched terms only)
    - Top 1-3 TM matches only
    - Forbidden hints only if relevant
    """

    def __init__(self, project_id: int, route: str, model: str = 'gpt-4o-mini', batch_size: int = 10):
        """
        Args:
            project_id: int
            route: str — 'GPT_REQUIRED' or 'GPT_WITH_GLOSSARY_REQUIRED'
            model: str — OpenAI model
            batch_size: int — segments per batch
        """
        self.project_id = project_id
        self.route = route
        self.model = model
        self.batch_size = batch_size
        self.segments = []
        self.eligible_segments = []

    def load_segments(self):
        """Load all segments for project."""
        self.segments = get_segments(self.project_id)
        return len(self.segments)

    def find_eligible_segments(self) -> List[Dict]:
        """
        Find segments eligible for GPT batch translation.

        Criteria:
        - route matches selected route
        - status in ['new', 'untranslated', None, '']
        - not exact TM
        - not duplicate pending
        - no target_text yet
        """
        eligible = []

        for seg in self.segments:
            # Check route
            if seg.get('route') != self.route:
                continue

            # Skip EXACT_TM and GOOGLE_SAFE
            if seg.get('route') in ['EXACT_TM', 'GOOGLE_SAFE', 'DUPLICATE_PROPAGATION_PENDING']:
                continue

            # Check status
            status = seg.get('status', '').lower().strip()
            if status not in ['new', 'untranslated', '']:
                continue

            # Check if already translated
            if seg.get('target_text'):
                continue

            eligible.append(seg)

        self.eligible_segments = eligible
        return eligible

    def get_minimal_glossary(self, source_text: str) -> str:
        """
        Get minimal glossary for segment (matched terms only).

        Returns:
            Glossary string with ONLY matched approved terms for this segment.
            Format: "term1 — translation1\nterm2 — translation2"
        """
        try:
            matches = match_segment(source_text)
            if not matches:
                return ""

            glossary_lines = []
            for match in matches[:5]:  # Top 5 matches only
                if match.get('status') != 'approved':
                    continue

                source_term = match.get('source_term', '')
                target_term = match.get('target_term', '')

                if source_term and target_term:
                    glossary_lines.append(f"{source_term} — {target_term}")

            return "\n".join(glossary_lines)
        except Exception:
            return ""

    def get_minimal_tm(self, source_text: str) -> str:
        """
        Get minimal TM context (top 1-3 matches only).

        Returns:
            TM string with top matches. Format: "Previous: ru→en"
        """
        try:
            matches = find_tm_suggestion(source_text, top_n=3, min_similarity=0.8)

            if not matches:
                return ""

            # find_tm_suggestion returns list or single dict
            if isinstance(matches, dict):
                matches = [matches]

            if not matches or len(matches) == 0:
                return ""

            tm_lines = []
            for match in matches[:3]:
                score = match.get('score', 0)
                if score < 80:  # Only include 80%+ matches
                    continue

                source = match.get('source_text', '')
                target = match.get('target_text', '')

                if source and target:
                    tm_lines.append(f"TM ({score:.0f}%): {source[:50]}… → {target[:50]}…")

            return "\n".join(tm_lines)
        except Exception:
            return ""

    def group_by_characteristics(self) -> Dict[Tuple, List[Dict]]:
        """
        Group segments by route, risk, block_type, approximate length.

        Returns:
            dict with (route, risk, block_type, length_bucket) → [segments]
        """
        groups = {}

        for seg in self.eligible_segments:
            route = seg.get('route', 'unknown')
            risk = seg.get('risk_level', 'MEDIUM')
            block_type = seg.get('block_type', 'text')

            # Approximate length bucket: <100, 100-300, 300-500, >500 chars
            text_len = len(seg.get('source_text', ''))
            if text_len < 100:
                length_bucket = 'short'
            elif text_len < 300:
                length_bucket = 'medium'
            elif text_len < 500:
                length_bucket = 'long'
            else:
                length_bucket = 'very_long'

            key = (route, risk, block_type, length_bucket)

            if key not in groups:
                groups[key] = []
            groups[key].append(seg)

        return groups

    def get_preview(self) -> Dict:
        """
        Get preview of what will be translated.

        Returns:
            dict with:
            - eligible_count: int
            - batch_count: int
            - estimated_tokens: int
            - estimated_usd: float
            - expected_qa_depth: str
            - examples_included: list[dict]
            - warnings: list[str]
        """
        self.find_eligible_segments()

        eligible_count = len(self.eligible_segments)
        batch_count = (eligible_count + self.batch_size - 1) // self.batch_size

        # Estimate tokens: ~1 token per 4 chars (average)
        # Input: source (1x) + glossary (~200 tokens) + TM (~100 tokens) + instructions (~500)
        # Output: ~1.3x source length (Russian→English expansion)
        total_chars = sum(len(seg.get('source_text', '')) for seg in self.eligible_segments)
        avg_input_tokens_per_seg = (total_chars / eligible_count / 4) if eligible_count > 0 else 0
        avg_output_tokens_per_seg = avg_input_tokens_per_seg * 1.3

        estimated_tokens = int(
            eligible_count * (avg_input_tokens_per_seg + avg_output_tokens_per_seg + 700)
        )

        # Pricing: GPT-4o-mini ~$0.00015/input, $0.0006/output (approximate)
        # For conservative estimate: ~$0.0001 per token on average
        estimated_usd = round(estimated_tokens * 0.0001, 2)

        # QA depth based on risk and route
        qa_depth = 'light'
        if self.route == 'GPT_WITH_GLOSSARY_REQUIRED':
            qa_depth = 'standard'

        # Get examples
        examples = []
        for seg in self.eligible_segments[:3]:
            examples.append({
                'id': seg['id'],
                'source_text': seg.get('source_text', '')[:100],
                'risk': seg.get('risk_level'),
                'block_type': seg.get('block_type'),
                'intent': seg.get('segment_intent'),
            })

        # Warnings
        warnings = []
        if estimated_usd > 10:
            warnings.append(f"⚠️ High cost: ${estimated_usd:.2f}")
        if 'GLOSSARY' in self.route:
            warnings.append("Glossary context will be injected (minimal)")
        warnings.append("Translations will be saved as 'translated' (not confirmed)")
        warnings.append("Run QA separately before final approval")

        return {
            'eligible_count': eligible_count,
            'batch_count': batch_count,
            'batch_size': self.batch_size,
            'estimated_tokens': estimated_tokens,
            'estimated_usd': estimated_usd,
            'expected_qa_depth': qa_depth,
            'examples_included': examples,
            'warnings': warnings,
        }

    def translate_batch(self, progress_callback=None) -> Dict:
        """
        Execute batch translation.

        Returns:
            dict with:
            - translated_count: int
            - failed_count: int
            - total_estimated_tokens: int
            - total_estimated_usd: float
            - total_actual_tokens: int (from API if available)
            - total_actual_usd: float (from API if available)
            - results: list of {segment_id, status, tokens_used, cost_usd, error}
        """
        self.find_eligible_segments()
        groups = self.group_by_characteristics()

        translated_count = 0
        failed_count = 0
        total_estimated_tokens = 0
        total_estimated_usd = 0.0
        total_actual_tokens = 0
        total_actual_usd = 0.0
        results = []

        # Process groups in order
        for (route, risk, block_type, length_bucket), group_segments in groups.items():
            if progress_callback:
                progress_callback(f"Processing {route} ({risk}, {block_type}, {length_bucket})...")

            # Process in batches within group
            for batch_idx in range(0, len(group_segments), self.batch_size):
                batch_segments = group_segments[batch_idx : batch_idx + self.batch_size]

                for seg in batch_segments:
                    try:
                        source_text = seg.get('source_text', '')

                        # Get minimal glossary (matched terms only)
                        glossary = self.get_minimal_glossary(source_text)

                        # Get minimal TM (top 1-3 matches)
                        tm_context = self.get_minimal_tm(source_text)

                        # Combine into minimal context
                        minimal_context = ""
                        if glossary:
                            minimal_context += f"Glossary:\n{glossary}\n"
                        if tm_context:
                            minimal_context += f"\nPrevious Translations:\n{tm_context}"

                        # Call translate_segment
                        # Note: translate_segment expects glossary as context, not full glossary list
                        result = translate_segment(
                            source_text,
                            glossary=minimal_context,
                            model=self.model,
                            tm=tm_context
                        )

                        if not result:
                            results.append({
                                'segment_id': seg['id'],
                                'status': 'error',
                                'error': 'Empty translation',
                            })
                            failed_count += 1
                            continue

                        # Extract translation and token info
                        target_text = result
                        tokens_used = None
                        cost_usd = 0.0

                        # If result is dict with token info, extract it
                        if isinstance(result, dict):
                            target_text = result.get('text', '')
                            tokens_used = result.get('tokens_used')
                            cost_usd = result.get('cost', 0.0)

                        # Estimate tokens if not provided
                        if tokens_used is None:
                            avg_input = len(source_text) / 4 + 700  # Source + context overhead
                            avg_output = len(target_text) / 4
                            tokens_used = int(avg_input + avg_output)

                        # Save segment
                        update_data = {
                            'target_text': target_text,
                            'provider': 'openai',
                            'status': 'translated',
                            'estimated_total_tokens': tokens_used,
                            'estimated_total_usd': round(cost_usd, 4),
                        }

                        update_segment(seg['id'], update_data)

                        translated_count += 1
                        total_estimated_tokens += tokens_used
                        total_estimated_usd += cost_usd
                        total_actual_tokens += tokens_used
                        total_actual_usd += cost_usd

                        results.append({
                            'segment_id': seg['id'],
                            'status': 'translated',
                            'tokens_used': tokens_used,
                            'cost_usd': round(cost_usd, 4),
                        })

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
            'total_estimated_tokens': total_estimated_tokens,
            'total_estimated_usd': round(total_estimated_usd, 2),
            'total_actual_tokens': total_actual_tokens,
            'total_actual_usd': round(total_actual_usd, 2),
            'results': results,
        }


def translate_gpt_batch(project_id: int, route: str, model: str = 'gpt-4o-mini', batch_size: int = 10, preview_only: bool = False):
    """
    Quick entry point for GPT batch translation.

    Args:
        project_id: int
        route: str — 'GPT_REQUIRED' or 'GPT_WITH_GLOSSARY_REQUIRED'
        model: str — OpenAI model
        batch_size: int — segments per batch
        preview_only: bool — if True, return preview only

    Returns:
        dict with preview or translation results
    """
    translator = GPTBatchTranslator(project_id, route, model, batch_size)
    translator.load_segments()

    if preview_only:
        return translator.get_preview()
    else:
        return translator.translate_batch()
