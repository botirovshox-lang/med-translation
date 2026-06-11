"""
cost_estimator.py — Детальная оценка токенов и USD с двумя сценариями.
Без API вызовов. Базовое и оптимизированное сценарии.
"""

import json
from typing import Dict, List, Tuple


class CostEstimator:
    """
    Оценка затрат для перевода: токены + USD.

    Две сценария:
    - Baseline: все сегменты через GPT translate + QA + backcheck
    - Optimized: использует маршруты (GOOGLE_SAFE, EXACT_TM, дубликаты = $0)
    """

    # ═════════════════════════════════════════════════════════════
    # CONFIGURABLE PRICING (use these as template)
    # ═════════════════════════════════════════════════════════════

    # GPT-4o pricing (USD per 1M tokens, as of 2026-05)
    GPT_TRANSLATE_INPUT_PRICE_PER_1M = 5.0      # $0.005 per 1K = $5 per 1M
    GPT_TRANSLATE_OUTPUT_PRICE_PER_1M = 15.0    # $0.015 per 1K = $15 per 1M
    GPT_QA_INPUT_PRICE_PER_1M = 5.0
    GPT_QA_OUTPUT_PRICE_PER_1M = 15.0
    GPT_BACKCHECK_INPUT_PRICE_PER_1M = 5.0
    GPT_BACKCHECK_OUTPUT_PRICE_PER_1M = 15.0
    GPT_SAFETY_INPUT_PRICE_PER_1M = 5.0
    GPT_SAFETY_OUTPUT_PRICE_PER_1M = 15.0

    # Google Translate pricing (USD per 1M characters, free tier up to 500K/month)
    GOOGLE_TRANSLATE_PRICE_PER_1M_CHARS = 25.0  # $0.025 per 1K chars = $25 per 1M

    # Prompt overhead (tokens added by system prompts)
    PROMPT_OVERHEAD = {
        'translate': 400,      # System prompt + task instructions
        'qa': 1000,           # Full QA rubric + criteria
        'backcheck': 1000,    # Back-translation instructions
        'safety': 500,        # Safety check rubric
    }

    # Token estimation: cyrillic chars per token
    CHARS_PER_TOKEN_CYRILLIC = 3.2
    CHARS_PER_TOKEN_LATIN = 4.0

    def __init__(self, config_dict=None):
        """
        Initialize with optional config overrides.

        Args:
            config_dict: dict with keys like GPT_TRANSLATE_INPUT_PRICE_PER_1M
        """
        if config_dict:
            for key, value in config_dict.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    # ═════════════════════════════════════════════════════════════
    # TOKEN ESTIMATION
    # ═════════════════════════════════════════════════════════════

    def estimate_tokens_for_step(self, text, step='translate'):
        """
        Estimate input and output tokens for one step separately.

        Args:
            text: str — source text
            step: str — 'translate'|'qa'|'backcheck'|'safety'

        Returns:
            dict: {
                'input_tokens': int,
                'output_tokens': int,
                'total_tokens': int,
            }
        """
        if not text or len(text.strip()) < 1:
            return {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}

        # Estimate based on character count (more accurate than word count)
        cyrillic_count = sum(1 for c in text if ord(c) > 127)  # Non-ASCII
        latin_count = len(text) - cyrillic_count

        # Base token count
        base_source_tokens = int(
            (cyrillic_count / self.CHARS_PER_TOKEN_CYRILLIC) +
            (latin_count / self.CHARS_PER_TOKEN_LATIN)
        )

        # For Russian→English translation: +30% output expansion
        expansion_factor = 1.3 if 'translate' in step else 1.0
        output_tokens_base = int(base_source_tokens * expansion_factor * 1.2)

        # Prompt overhead
        overhead = self.PROMPT_OVERHEAD.get(step, 300)

        # Step-specific calculations
        if step == 'translate':
            input_tokens = base_source_tokens + overhead
            output_tokens = output_tokens_base + 100  # Buffer
        elif step == 'qa':
            # Include both source and target in QA prompt
            input_tokens = base_source_tokens + output_tokens_base + overhead
            output_tokens = int((base_source_tokens + output_tokens_base) * 0.4) + 200
        elif step == 'backcheck':
            # Back-translation comparison
            input_tokens = output_tokens_base + overhead
            output_tokens = base_source_tokens + 100
        elif step == 'safety':
            # Safety review (lightweight)
            input_tokens = base_source_tokens + 200 + overhead
            output_tokens = 300
        else:
            input_tokens = base_source_tokens + overhead
            output_tokens = int(base_source_tokens * 0.3)

        return {
            'input_tokens': max(1, input_tokens),
            'output_tokens': max(1, output_tokens),
            'total_tokens': max(1, input_tokens + output_tokens),
        }

    # ═════════════════════════════════════════════════════════════
    # USD COST CALCULATION
    # ═════════════════════════════════════════════════════════════

    def calculate_step_cost(self, input_tokens, output_tokens, step='translate'):
        """
        Calculate USD cost for one step given token counts.

        Args:
            input_tokens: int
            output_tokens: int
            step: str — 'translate'|'qa'|'backcheck'|'safety'

        Returns:
            float: USD cost
        """
        # Get pricing for this step
        input_price_per_1m = getattr(self, f'GPT_{step.upper()}_INPUT_PRICE_PER_1M', 5.0)
        output_price_per_1m = getattr(self, f'GPT_{step.upper()}_OUTPUT_PRICE_PER_1M', 15.0)

        input_cost = (input_tokens / 1_000_000) * input_price_per_1m
        output_cost = (output_tokens / 1_000_000) * output_price_per_1m

        return round(input_cost + output_cost, 4)

    def calculate_google_cost(self, text):
        """
        Calculate cost for Google Translate (characters-based pricing).

        Args:
            text: str — source text

        Returns:
            float: USD cost
        """
        char_count = len(text.strip())
        cost = (char_count / 1_000_000) * self.GOOGLE_TRANSLATE_PRICE_PER_1M_CHARS
        return round(cost, 4)

    # ═════════════════════════════════════════════════════════════
    # PER-SEGMENT ESTIMATION
    # ═════════════════════════════════════════════════════════════

    def estimate_segment(self, segment, risk_level='MEDIUM'):
        """
        Estimate full cost breakdown for one segment (all steps).

        Args:
            segment: dict with 'source_text'
            risk_level: str — 'LOW'|'MEDIUM'|'HIGH'|'CRITICAL'

        Returns:
            dict with detailed token and USD estimates for each step
        """
        source_text = segment.get('source_text', '')

        # Estimate tokens for each step
        translate_tokens = self.estimate_tokens_for_step(source_text, 'translate')
        qa_tokens = self.estimate_tokens_for_step(source_text, 'qa')
        backcheck_tokens = self.estimate_tokens_for_step(source_text, 'backcheck')
        safety_tokens = self.estimate_tokens_for_step(source_text, 'safety')

        # Calculate USD for each step
        translate_usd = self.calculate_step_cost(
            translate_tokens['input_tokens'],
            translate_tokens['output_tokens'],
            'translate'
        )
        qa_usd = self.calculate_step_cost(
            qa_tokens['input_tokens'],
            qa_tokens['output_tokens'],
            'qa'
        )
        backcheck_usd = self.calculate_step_cost(
            backcheck_tokens['input_tokens'],
            backcheck_tokens['output_tokens'],
            'backcheck'
        )
        safety_usd = self.calculate_step_cost(
            safety_tokens['input_tokens'],
            safety_tokens['output_tokens'],
            'safety'
        )

        # Google cost (char-based)
        google_usd = self.calculate_google_cost(source_text)

        return {
            # Tokens per step
            'translation_input_tokens': translate_tokens['input_tokens'],
            'translation_output_tokens': translate_tokens['output_tokens'],
            'qa_input_tokens': qa_tokens['input_tokens'],
            'qa_output_tokens': qa_tokens['output_tokens'],
            'backcheck_input_tokens': backcheck_tokens['input_tokens'],
            'backcheck_output_tokens': backcheck_tokens['output_tokens'],
            'safety_input_tokens': safety_tokens['input_tokens'],
            'safety_output_tokens': safety_tokens['output_tokens'],

            # Total tokens
            'total_estimated_tokens': (
                translate_tokens['total_tokens'] +
                qa_tokens['total_tokens'] +
                backcheck_tokens['total_tokens'] +
                safety_tokens['total_tokens']
            ),

            # USD per step
            'translate_usd': translate_usd,
            'qa_usd': qa_usd,
            'backcheck_usd': backcheck_usd,
            'safety_usd': safety_usd,
            'google_usd': google_usd,

            # Character estimate for Google
            'google_chars_estimate': len(source_text.strip()),
        }

    def estimate_segment_cost_by_route(self, segment, route, risk_level='MEDIUM'):
        """
        Estimate cost for one segment based on its route.

        Args:
            segment: dict with 'source_text'
            route: str — the routing decision (EXACT_TM, GOOGLE_SAFE, GPT_REQUIRED, etc)
            risk_level: str — 'LOW'|'MEDIUM'|'HIGH'|'CRITICAL'

        Returns:
            dict with {
                'total_usd': float,
                'total_tokens': int,
                'translate_usd': float,
                'qa_usd': float,
                'backcheck_usd': float,
                'safety_usd': float,
                'google_usd': float,
            }
        """
        # Get full segment estimate (all steps)
        full_estimate = self.estimate_segment(segment, risk_level)

        # Apply route-specific logic
        translate_usd = 0.0
        qa_usd = 0.0
        backcheck_usd = 0.0
        safety_usd = 0.0
        google_usd = 0.0
        total_tokens = 0

        if route == 'EXACT_TM':
            # No API cost - TM match
            pass

        elif route == 'DUPLICATE_PROPAGATION_PENDING':
            # No API cost - copy from representative
            pass

        elif route == 'GOOGLE_SAFE':
            # Use Google Translate (cheaper than GPT)
            google_usd = full_estimate['google_usd']
            total_tokens = full_estimate.get('total_estimated_tokens', 0)

        elif route == 'DUPLICATE_REPRESENTATIVE':
            # Translate only, no QA cost yet
            translate_usd = full_estimate['translate_usd']
            total_tokens = (
                full_estimate.get('translation_input_tokens', 0) +
                full_estimate.get('translation_output_tokens', 0)
            )

        elif route in ['GPT_REQUIRED', 'GPT_WITH_GLOSSARY_REQUIRED']:
            # Translate + QA (always)
            translate_usd = full_estimate['translate_usd']
            qa_usd = full_estimate['qa_usd']

            # Backcheck only for HIGH/CRITICAL
            if risk_level in ['HIGH', 'CRITICAL']:
                backcheck_usd = full_estimate['backcheck_usd']

            # Safety only for CRITICAL
            if risk_level == 'CRITICAL':
                safety_usd = full_estimate['safety_usd']

            total_tokens = full_estimate.get('total_estimated_tokens', 0)

        elif route == 'HUMAN_REVIEW_REQUIRED':
            # No API cost - human review only
            pass

        else:
            # Default to GPT_REQUIRED logic
            translate_usd = full_estimate['translate_usd']
            qa_usd = full_estimate['qa_usd']
            if risk_level in ['HIGH', 'CRITICAL']:
                backcheck_usd = full_estimate['backcheck_usd']
            if risk_level == 'CRITICAL':
                safety_usd = full_estimate['safety_usd']
            total_tokens = full_estimate.get('total_estimated_tokens', 0)

        total_usd = round(translate_usd + qa_usd + backcheck_usd + safety_usd + google_usd, 4)

        return {
            'total_usd': total_usd,
            'total_tokens': total_tokens,
            'translate_usd': round(translate_usd, 4),
            'qa_usd': round(qa_usd, 4),
            'backcheck_usd': round(backcheck_usd, 4),
            'safety_usd': round(safety_usd, 4),
            'google_usd': round(google_usd, 4),
        }

    # ═════════════════════════════════════════════════════════════
    # BATCH COST ESTIMATION (Baseline vs Optimized)
    # ═════════════════════════════════════════════════════════════

    def estimate_batch(self, segments_with_routes: List[Dict]) -> Dict:
        """
        Estimate batch costs with two scenarios: Baseline and Optimized.

        Args:
            segments_with_routes: list of dicts with 'source_text', 'route', 'risk_level'

        Returns:
            dict with both scenarios and detailed breakdown
        """
        baseline_results = {
            'translation_usd': 0.0,
            'qa_usd': 0.0,
            'backcheck_usd': 0.0,
            'safety_usd': 0.0,
            'total_usd': 0.0,
            'total_tokens': 0,
        }

        optimized_results = {
            'translation_usd': 0.0,
            'qa_usd': 0.0,
            'backcheck_usd': 0.0,
            'safety_usd': 0.0,
            'google_usd': 0.0,
            'total_usd': 0.0,
            'total_tokens': 0,
        }

        # Savings tracking
        savings = {
            'exact_tm_savings': 0.0,
            'duplicate_savings': 0.0,
            'google_savings': 0.0,
            'qa_adaptive_savings': 0.0,
        }

        route_stats = {}

        for seg in segments_with_routes:
            source_text = seg.get('source_text', '')
            route = seg.get('route', 'GPT_REQUIRED')
            risk_level = seg.get('risk_level', 'MEDIUM')

            # Estimate this segment
            est = self.estimate_segment(seg, risk_level)

            # ─── BASELINE SCENARIO: All segments through GPT ───
            baseline_results['translation_usd'] += est['translate_usd']
            baseline_results['qa_usd'] += est['qa_usd']
            baseline_results['backcheck_usd'] += est['backcheck_usd']
            baseline_results['safety_usd'] += est['safety_usd']
            baseline_results['total_tokens'] += est['total_estimated_tokens']

            # ─── OPTIMIZED SCENARIO: Route-aware ───
            opt_trans_usd = 0.0
            opt_qa_usd = 0.0
            opt_backcheck_usd = 0.0
            opt_safety_usd = 0.0
            opt_google_usd = 0.0
            segment_savings = 0.0

            if route == 'EXACT_TM':
                # No API cost
                segment_savings = est['translate_usd'] + est['qa_usd']
                savings['exact_tm_savings'] += segment_savings

            elif route == 'DUPLICATE_PROPAGATION_PENDING':
                # No API cost
                segment_savings = est['translate_usd'] + est['qa_usd']
                savings['duplicate_savings'] += segment_savings

            elif route == 'GOOGLE_SAFE':
                # Use Google (cheaper) instead of GPT
                opt_google_usd = est['google_usd']
                segment_savings = est['translate_usd'] - opt_google_usd
                savings['google_savings'] += segment_savings

            elif route == 'DUPLICATE_REPRESENTATIVE':
                # Translate once, no QA needed yet (QA done at confirmation)
                opt_trans_usd = est['translate_usd']
                segment_savings = est['qa_usd']
                savings['qa_adaptive_savings'] += segment_savings

            else:  # GPT_REQUIRED, GPT_WITH_GLOSSARY_REQUIRED, HUMAN_REVIEW_REQUIRED
                # Translate + QA (always for these routes)
                opt_trans_usd = est['translate_usd']
                opt_qa_usd = est['qa_usd']

                # Backcheck only for HIGH/CRITICAL (not MEDIUM/LOW)
                if risk_level in ['HIGH', 'CRITICAL']:
                    opt_backcheck_usd = est['backcheck_usd']
                else:
                    segment_savings += est['backcheck_usd']
                    savings['qa_adaptive_savings'] += est['backcheck_usd']

                # Safety check only for CRITICAL
                if risk_level == 'CRITICAL':
                    opt_safety_usd = est['safety_usd']
                else:
                    segment_savings += est['safety_usd']

            optimized_results['translation_usd'] += opt_trans_usd
            optimized_results['qa_usd'] += opt_qa_usd
            optimized_results['backcheck_usd'] += opt_backcheck_usd
            optimized_results['safety_usd'] += opt_safety_usd
            optimized_results['google_usd'] += opt_google_usd
            optimized_results['total_usd'] += (
                opt_trans_usd + opt_qa_usd + opt_backcheck_usd + opt_safety_usd + opt_google_usd
            )

            # Track route statistics
            if route not in route_stats:
                route_stats[route] = {
                    'count': 0,
                    'tokens': 0,
                    'baseline_usd': 0.0,
                    'optimized_usd': 0.0,
                }
            route_stats[route]['count'] += 1
            route_stats[route]['tokens'] += est['total_estimated_tokens']
            route_stats[route]['baseline_usd'] += (
                est['translate_usd'] + est['qa_usd'] + est['backcheck_usd'] + est['safety_usd']
            )
            route_stats[route]['optimized_usd'] += (
                opt_trans_usd + opt_qa_usd + opt_backcheck_usd + opt_safety_usd + opt_google_usd
            )

        # Finalize
        baseline_results['total_usd'] = round(
            baseline_results['translation_usd'] +
            baseline_results['qa_usd'] +
            baseline_results['backcheck_usd'] +
            baseline_results['safety_usd'],
            2
        )

        optimized_results['total_usd'] = round(optimized_results['total_usd'], 2)

        savings_usd = baseline_results['total_usd'] - optimized_results['total_usd']
        savings_percent = (
            (savings_usd / baseline_results['total_usd'] * 100)
            if baseline_results['total_usd'] > 0
            else 0
        )

        return {
            'baseline': {
                'total_usd': baseline_results['total_usd'],
                'translation_usd': round(baseline_results['translation_usd'], 2),
                'qa_usd': round(baseline_results['qa_usd'], 2),
                'backcheck_usd': round(baseline_results['backcheck_usd'], 2),
                'safety_usd': round(baseline_results['safety_usd'], 2),
                'total_tokens': baseline_results['total_tokens'],
            },
            'optimized': {
                'total_usd': optimized_results['total_usd'],
                'translation_usd': round(optimized_results['translation_usd'], 2),
                'qa_usd': round(optimized_results['qa_usd'], 2),
                'backcheck_usd': round(optimized_results['backcheck_usd'], 2),
                'safety_usd': round(optimized_results['safety_usd'], 2),
                'google_usd': round(optimized_results['google_usd'], 2),
                'total_tokens': optimized_results['total_tokens'],
            },
            'savings': {
                'total_usd': round(savings_usd, 2),
                'total_percent': round(savings_percent, 1),
                'exact_tm_usd': round(savings['exact_tm_savings'], 2),
                'duplicate_usd': round(savings['duplicate_savings'], 2),
                'google_usd': round(savings['google_savings'], 2),
                'qa_adaptive_usd': round(savings['qa_adaptive_savings'], 2),
            },
            'route_breakdown': route_stats,
        }


# Fast entry point
def estimate_batch_costs(segments_with_routes):
    """Quick function to estimate batch costs."""
    estimator = CostEstimator()
    return estimator.estimate_batch(segments_with_routes)
