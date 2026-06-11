"""
numerical_qa_engine.py — Medical numerical QA validation.
Checks dosages, units, lab values, percentages, ranges, inequalities.
"""
import re
from typing import Dict, List, Tuple


class NumericalQAResult:
    """Result of numerical QA check."""

    def __init__(self):
        self.passed = True
        self.alerts = []
        self.issues = []

    def add_issue(self, issue_type: str, severity: str, message: str):
        """Add a numerical issue."""
        self.issues.append({
            'type': issue_type,
            'severity': severity,
            'message': message,
        })
        if severity in ['error', 'critical']:
            self.passed = False

    def to_dict(self):
        return {
            'passed': self.passed,
            'issues': self.issues,
            'total_issues': len(self.issues),
        }


class NumericalQAEngine:
    """
    Run numerical validation checks on medical translations.

    Checks:
    - Dosage preservation (mg, ml, g, IU, etc.)
    - Unit consistency
    - Lab value ranges
    - Percentage accuracy
    - Numeric ranges (e.g., "2-5 days")
    - Inequalities (>, <, >=, <=)
    - Decimal places preservation
    """

    def __init__(self):
        # Medical units and abbreviations
        self.medical_units = {
            'dosage': ['mg', 'g', 'μg', 'ng', 'ml', 'l', 'cc', 'IU', 'mIU', 'mmol', 'μmol'],
            'mass': ['mg', 'g', 'kg', 'μg', 'ng', 'pg'],
            'volume': ['ml', 'μl', 'l', 'dl', 'cc'],
            'time': ['sec', 'min', 'h', 'hr', 'day', 'days', 'week', 'month', 'year'],
            'lab': ['mmol/l', 'mg/dl', 'g/dl', 'U/l', 'mU/l', 'IU/l', 'ng/ml', 'pg/ml'],
        }

        # Numeric patterns
        self.patterns = {
            'number': r'\d+([.,]\d+)?',
            'dosage': r'(\d+(?:[.,]\d+)?)\s*(?:mg|g|μg|ng|ml|l|IU|mmol)',
            'range': r'(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)',
            'percentage': r'(\d+(?:[.,]\d+)?)\s*%',
            'inequality': r'([<>]=?|≤|≥)\s*(\d+(?:[.,]\d+)?)',
            'decimal': r'\d+[.,]\d{1,3}',
        }

    def check_dosage_preservation(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """Check if dosages are preserved correctly."""
        source_dosages = re.findall(self.patterns['dosage'], source_text, re.IGNORECASE)
        target_dosages = re.findall(self.patterns['dosage'], target_text, re.IGNORECASE)

        if not source_dosages:
            return True, ""

        if len(source_dosages) != len(target_dosages):
            return False, f"Dosage count mismatch: source {len(source_dosages)}, target {len(target_dosages)}"

        return True, ""

    def check_unit_consistency(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """Check if units (mg, ml, g, etc.) are consistent."""
        source_units = set(re.findall(r'(?:mg|g|μg|ng|ml|l|IU|mmol)', source_text, re.IGNORECASE))
        target_units = set(re.findall(r'(?:mg|g|μg|ng|ml|l|IU|mmol)', target_text, re.IGNORECASE))

        if not source_units:
            return True, ""

        if source_units != target_units:
            missing = source_units - target_units
            extra = target_units - source_units
            msg = f"Unit mismatch:"
            if missing:
                msg += f" missing {missing},"
            if extra:
                msg += f" unexpected {extra}"
            return False, msg

        return True, ""

    def check_lab_value_format(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """Check if lab values maintain format consistency."""
        # Look for patterns like "12.5 mmol/l" or "mg/dl"
        lab_pattern = r'(\d+(?:[.,]\d+)?)\s*(?:mmol/l|mg/dl|g/dl|U/l|mU/l|IU/l|ng/ml)'

        source_labs = re.findall(lab_pattern, source_text, re.IGNORECASE)
        target_labs = re.findall(lab_pattern, target_text, re.IGNORECASE)

        if not source_labs:
            return True, ""

        if len(source_labs) != len(target_labs):
            return False, f"Lab value count mismatch: source {len(source_labs)}, target {len(target_labs)}"

        return True, ""

    def check_percentage_accuracy(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """Check if percentages are preserved accurately."""
        source_percents = re.findall(self.patterns['percentage'], source_text)
        target_percents = re.findall(self.patterns['percentage'], target_text)

        if not source_percents:
            return True, ""

        if len(source_percents) != len(target_percents):
            return False, f"Percentage count mismatch: source {len(source_percents)}, target {len(target_percents)}"

        # Check values match (allowing for decimal place variation)
        for src, tgt in zip(source_percents, target_percents):
            src_val = float(src.replace(',', '.'))
            tgt_val = float(tgt.replace(',', '.'))
            if abs(src_val - tgt_val) > 0.1:  # Allow 0.1% tolerance
                return False, f"Percentage mismatch: {src}% vs {tgt}%"

        return True, ""

    def check_numeric_range_format(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """Check if numeric ranges (e.g., 2-5 days) are preserved."""
        source_ranges = re.findall(self.patterns['range'], source_text)
        target_ranges = re.findall(self.patterns['range'], target_text)

        if not source_ranges:
            return True, ""

        if len(source_ranges) != len(target_ranges):
            return False, f"Range count mismatch: source {len(source_ranges)}, target {len(target_ranges)}"

        return True, ""

    def check_inequality_preservation(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """Check if inequalities (>, <, >=) are preserved."""
        source_inequalities = re.findall(self.patterns['inequality'], source_text)
        target_inequalities = re.findall(self.patterns['inequality'], target_text)

        if not source_inequalities:
            return True, ""

        if len(source_inequalities) != len(target_inequalities):
            return False, f"Inequality count mismatch: source {len(source_inequalities)}, target {len(target_inequalities)}"

        return True, ""

    def check_decimal_preservation(self, source_text: str, target_text: str) -> Tuple[bool, str]:
        """Check if decimal places are preserved (e.g., 12.5 vs 125)."""
        source_decimals = re.findall(self.patterns['decimal'], source_text)
        target_decimals = re.findall(self.patterns['decimal'], target_text)

        if not source_decimals:
            return True, ""

        if len(source_decimals) != len(target_decimals):
            return False, f"Decimal count mismatch: source {len(source_decimals)}, target {len(target_decimals)}"

        # Check that decimal places are similar
        for src, tgt in zip(source_decimals, target_decimals):
            src_decimal_places = len(src.split('.')[1]) if '.' in src else len(src.split(',')[1]) if ',' in src else 0
            tgt_decimal_places = len(tgt.split('.')[1]) if '.' in tgt else len(tgt.split(',')[1]) if ',' in tgt else 0
            if src_decimal_places != tgt_decimal_places:
                return False, f"Decimal place mismatch: {src} ({src_decimal_places} places) vs {tgt} ({tgt_decimal_places} places)"

        return True, ""

    def run_qa(self, source_text: str, target_text: str) -> NumericalQAResult:
        """
        Run all numerical QA checks.

        Returns:
            NumericalQAResult with passed flag and issues list
        """
        result = NumericalQAResult()

        checks = [
            ('dosage_preservation', self.check_dosage_preservation(source_text, target_text), 'error'),
            ('unit_consistency', self.check_unit_consistency(source_text, target_text), 'error'),
            ('lab_value_format', self.check_lab_value_format(source_text, target_text), 'warning'),
            ('percentage_accuracy', self.check_percentage_accuracy(source_text, target_text), 'error'),
            ('numeric_range', self.check_numeric_range_format(source_text, target_text), 'warning'),
            ('inequality_preservation', self.check_inequality_preservation(source_text, target_text), 'warning'),
            ('decimal_preservation', self.check_decimal_preservation(source_text, target_text), 'warning'),
        ]

        for check_name, (passed, message), severity in checks:
            if not passed and message:
                result.add_issue(check_name, severity, message)

        return result


def run_numerical_qa(source_text: str, target_text: str) -> NumericalQAResult:
    """Quick entry point for numerical QA."""
    engine = NumericalQAEngine()
    return engine.run_qa(source_text, target_text)
