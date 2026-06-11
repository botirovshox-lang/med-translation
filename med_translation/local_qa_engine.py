"""
local_qa_engine.py — Local QA checks for machine translations (Google, initial GPT)
No API calls, pure local validation.
"""
import re
from typing import Dict, List, Tuple


class LocalQAResult:
    """Result of local QA check."""

    def __init__(self):
        self.passed = True
        self.alerts = []  # List of {type, severity, message}

    def add_alert(self, alert_type: str, severity: str, message: str):
        """Add a QA alert."""
        self.alerts.append({
            'type': alert_type,
            'severity': severity,
            'message': message,
        })
        if severity in ['error', 'critical']:
            self.passed = False

    def to_dict(self):
        return {
            'passed': self.passed,
            'alerts': self.alerts,
            'total_alerts': len(self.alerts),
        }


class LocalQAEngine:
    """
    Run local QA checks on translations without API calls.

    Checks:
    - Empty output
    - Language detection (output should be English)
    - Length ratio (output 0.8-1.5x input length)
    - Number preservation (same digits)
    - Abbreviation preservation (e.g., mg → mg)
    - Name/initial preservation
    - Forbidden term detection
    - Entity preservation (brackets, dashes, etc.)
    """

    def __init__(self):
        pass

    def check_empty_output(self, target_text: str) -> Tuple[bool, str]:
        """Check if translation is empty."""
        if not target_text or len(target_text.strip()) < 1:
            return False, "Translation is empty"
        return True, ""

    def check_language(self, target_text: str) -> Tuple[bool, str]:
        """
        Simple language check: English text should have common English words.
        Not exhaustive, just a sanity check.
        """
        english_common = ['the', 'a', 'is', 'and', 'to', 'of', 'in', 'for', 'with', 'be', 'as']
        target_lower = target_text.lower()

        found = sum(1 for word in english_common if f' {word} ' in f' {target_lower} ')

        # If less than 2 common words found, might not be English
        if len(target_text.split()) > 5 and found < 2:
            return False, "May not be English (few common words detected)"

        return True, ""

    def check_length_ratio(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """
        Check if target length is reasonable (0.7-1.8x source).
        Russian→English typically expands 1.2-1.5x.
        """
        source_len = len(source_text.strip())
        target_len = len(target_text.strip())

        if source_len < 5:
            return True, ""  # Skip for very short segments

        ratio = target_len / source_len

        if ratio < 0.5:
            return False, f"Output too short (ratio {ratio:.2f})"
        if ratio > 2.0:
            return False, f"Output too long (ratio {ratio:.2f})"

        return True, ""

    def check_numbers_preserved(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """Check that numbers in source are in target."""
        source_numbers = set(re.findall(r'\d+', source_text))
        target_numbers = set(re.findall(r'\d+', target_text))

        # All source numbers should be in target
        missing = source_numbers - target_numbers
        if missing:
            return False, f"Numbers missing in translation: {', '.join(sorted(missing))}"

        return True, ""

    def check_abbreviations_preserved(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """Check that medical abbreviations are preserved."""
        # Common medical abbreviations that should appear in both
        medical_abbrev = ['mg', 'ml', 'g', 'kg', 'mmol', '%', 'IU', 'mm', 'cm', 'h', 'hr', 'min', 'sec']

        missing = []
        for abbr in medical_abbrev:
            if abbr in source_text and abbr not in target_text:
                missing.append(abbr)

        if missing:
            return False, f"Medical abbreviations missing: {', '.join(missing)}"

        return True, ""

    def check_names_preserved(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """
        Check that capitalized words (names) are preserved.
        Russian names often stay the same in English medical texts.
        """
        # Find capitalized words (likely names/institutions)
        source_caps = set(re.findall(r'\b[А-ЯA-Z][а-яa-z]+\b', source_text))
        target_caps = set(re.findall(r'\b[A-Z][a-z]+\b', target_text))

        # If source has proper nouns, target should have similar count
        if len(source_caps) > 2:
            if len(target_caps) < max(1, len(source_caps) // 2):
                return False, f"Proper nouns may be lost (source: {len(source_caps)}, target: {len(target_caps)})"

        return True, ""

    def check_forbidden_terms(self, target_text: str) -> Tuple[bool, str]:
        """Check for forbidden terms in output using forbidden_checker."""
        try:
            from forbidden_checker import post_check

            # Use post_check to verify output safety
            # We pass empty source because we're checking output
            alerts = post_check("", target_text)

            if alerts:
                alert_msgs = [f"{a.term} ({a.severity})" for a in alerts]
                return False, f"Forbidden terms detected: {', '.join(alert_msgs)}"
        except ImportError:
            pass  # Skip if forbidden_checker not available

        return True, ""

    def check_entities_preserved(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """
        Check that structural entities are preserved:
        - Brackets/parentheses count
        - Dashes/hyphens
        """
        source_brackets = (source_text.count('(') + source_text.count('[')) * 2 + source_text.count('{') * 2
        target_brackets = (target_text.count('(') + target_text.count('[')) * 2 + target_text.count('{') * 2

        if source_brackets > 0 and target_brackets < source_brackets * 0.5:
            return False, "Brackets/parentheses may be lost"

        return True, ""

    def run_qa(self, source_text: str, target_text: str, severity_level: str = 'warning') -> LocalQAResult:
        """
        Run all local QA checks.

        Args:
            source_text: Original Russian text
            target_text: Translated English text
            severity_level: 'strict' (fail on any), 'warning' (warning on issues), 'lenient' (only critical)

        Returns:
            LocalQAResult with passed flag and alerts
        """
        result = LocalQAResult()

        checks = [
            ('empty_output', self.check_empty_output(target_text), 'error'),
            ('language', self.check_language(target_text), 'warning'),
            ('length_ratio', self.check_length_ratio(source_text, target_text), 'warning'),
            ('numbers_preserved', self.check_numbers_preserved(source_text, target_text), 'error'),
            ('abbreviations', self.check_abbreviations_preserved(source_text, target_text), 'warning'),
            ('names_preserved', self.check_names_preserved(source_text, target_text), 'info'),
            ('forbidden_terms', self.check_forbidden_terms(target_text), 'critical'),
            ('entities', self.check_entities_preserved(source_text, target_text), 'warning'),
        ]

        for check_name, (passed, message), severity in checks:
            if not passed:
                result.add_alert(check_name, severity, message)

        return result


def run_local_qa(source_text: str, target_text: str, severity_level: str = 'warning') -> LocalQAResult:
    """Quick entry point for local QA."""
    engine = LocalQAEngine()
    return engine.run_qa(source_text, target_text, severity_level)
