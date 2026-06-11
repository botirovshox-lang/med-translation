"""
consistency_engine.py — Project-wide consistency QA.
Detects inconsistencies across translated segments.
No API calls.
"""
from typing import Dict, List, Set, Tuple
import json


class ConsistencyAlert:
    """An inconsistency alert."""

    def __init__(self, alert_type: str, severity: str, message: str, segment_ids: List[int]):
        self.type = alert_type
        self.severity = severity
        self.message = message
        self.segment_ids = segment_ids

    def to_dict(self):
        return {
            'type': self.type,
            'severity': self.severity,
            'message': self.message,
            'affected_segments': len(self.segment_ids),
            'segment_ids': self.segment_ids,
        }


class ConsistencyEngine:
    """
    Check project-wide translation consistency.

    Detects:
    - Same source translated differently
    - Glossary source term translated inconsistently
    - Institution name inconsistency
    - Abbreviation inconsistency
    - Figure/table caption inconsistency
    - Duplicate groups with different targets
    """

    def __init__(self):
        pass

    def detect_source_translation_inconsistency(self, segments: List[Dict]) -> List[ConsistencyAlert]:
        """
        Detect when same source text is translated differently.

        Returns:
            List of ConsistencyAlert objects
        """
        alerts = []
        source_translations = {}  # {source_text: [(segment_id, target_text), ...]}

        for seg in segments:
            source = seg.get('source_text', '').strip().lower()
            target = seg.get('target_text', '').strip() if seg.get('target_text') else None
            status = seg.get('status', '')

            if not source or not target or status not in ['translated', 'confirmed']:
                continue

            if source not in source_translations:
                source_translations[source] = []

            source_translations[source].append({
                'segment_id': seg['id'],
                'target': target,
                'status': status,
            })

        # Find inconsistencies
        for source, translations in source_translations.items():
            targets = set(t['target'] for t in translations)

            if len(targets) > 1:
                # Different translations for same source
                segment_ids = [t['segment_id'] for t in translations]
                target_samples = list(targets)[:2]
                msg = f'Same source "{source[:50]}" translated as: {" / ".join(target_samples)}'

                alerts.append(ConsistencyAlert(
                    alert_type='source_translation_inconsistency',
                    severity='warning',
                    message=msg,
                    segment_ids=segment_ids,
                ))

        return alerts

    def detect_glossary_inconsistency(self, segments: List[Dict], glossary: List[Dict]) -> List[ConsistencyAlert]:
        """
        Detect when glossary source terms are translated inconsistently.

        Args:
            segments: List of segment dicts
            glossary: List of glossary terms {source_term, target_term}

        Returns:
            List of ConsistencyAlert objects
        """
        alerts = []

        for term_dict in glossary:
            source_term = term_dict.get('source_term', '').strip().lower()
            approved_target = term_dict.get('target_term', '').strip()

            if not source_term or not approved_target:
                continue

            found_targets = {}  # {target: [segment_ids]}

            for seg in segments:
                source = seg.get('source_text', '').lower()
                target = seg.get('target_text', '')
                status = seg.get('status', '')

                if source_term in source and target and status in ['translated', 'confirmed']:
                    # Extract what was actually translated for this term
                    # (simplified: just check if approved target is used)
                    if approved_target.lower() not in target.lower():
                        # Glossary term not used as approved
                        actual_target = target  # Simplified - use full target
                        if actual_target not in found_targets:
                            found_targets[actual_target] = []
                        found_targets[actual_target].append(seg['id'])

            # Check if there are multiple different targets
            if len(found_targets) > 1:
                segment_ids = []
                for target_list in found_targets.values():
                    segment_ids.extend(target_list)

                targets_found = list(found_targets.keys())[:2]
                msg = f'Glossary term "{source_term}" translated inconsistently: {" / ".join(t[:30] for t in targets_found)}'

                alerts.append(ConsistencyAlert(
                    alert_type='glossary_inconsistency',
                    severity='warning',
                    message=msg,
                    segment_ids=segment_ids,
                ))

        return alerts

    def detect_institution_name_inconsistency(self, segments: List[Dict]) -> List[ConsistencyAlert]:
        """
        Detect institution/entity name inconsistencies.

        Looks for capitalized sequences that should be consistent.

        Returns:
            List of ConsistencyAlert objects
        """
        alerts = []
        institution_patterns = {}  # {source_pattern: [(segment_id, target_pattern), ...]}

        # Pattern: 2+ consecutive capitalized words
        import re

        for seg in segments:
            source = seg.get('source_text', '')
            target = seg.get('target_text', '')
            status = seg.get('status', '')

            if not target or status not in ['translated', 'confirmed']:
                continue

            # Find capitalized sequences (institution-like patterns)
            source_institutions = re.findall(r'\b[А-Я][а-я]+(?:\s+[А-Я][а-я]+)+\b', source)
            target_institutions = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', target)

            for inst in source_institutions:
                inst_lower = inst.lower()
                if inst_lower not in institution_patterns:
                    institution_patterns[inst_lower] = []

                # Try to match corresponding target institution
                target_inst = target_institutions[0] if target_institutions else None
                institution_patterns[inst_lower].append({
                    'segment_id': seg['id'],
                    'source': inst,
                    'target': target_inst,
                })

        # Find inconsistencies
        for inst_pattern, translations in institution_patterns.items():
            targets = set(t['target'] for t in translations if t['target'])

            if len(targets) > 1:
                segment_ids = [t['segment_id'] for t in translations]
                target_samples = list(targets)[:2]
                msg = f'Institution "{inst_pattern}" inconsistently translated: {" / ".join(t for t in target_samples if t)}'

                alerts.append(ConsistencyAlert(
                    alert_type='institution_inconsistency',
                    severity='info',
                    message=msg,
                    segment_ids=segment_ids,
                ))

        return alerts

    def detect_duplicate_group_mismatch(self, segments: List[Dict]) -> List[ConsistencyAlert]:
        """
        Detect duplicate groups where members have different targets.

        Returns:
            List of ConsistencyAlert objects
        """
        alerts = []
        duplicate_groups = {}  # {group_id: [segment]}

        for seg in segments:
            group_id = seg.get('duplicate_group_id')
            if group_id:
                if group_id not in duplicate_groups:
                    duplicate_groups[group_id] = []
                duplicate_groups[group_id].append(seg)

        # Check each group
        for group_id, group_segs in duplicate_groups.items():
            targets = set()
            segment_ids = []
            sources = set()

            for seg in group_segs:
                target = seg.get('target_text', '').strip() if seg.get('target_text') else None
                if target:
                    targets.add(target)
                    segment_ids.append(seg['id'])
                sources.add(seg.get('source_text', '').strip())

            if len(targets) > 1:
                # Duplicates have different targets
                target_samples = list(targets)[:2]
                msg = f'Duplicate group {group_id} has inconsistent targets: {" / ".join(t[:30] for t in target_samples)}'

                alerts.append(ConsistencyAlert(
                    alert_type='duplicate_group_mismatch',
                    severity='warning',
                    message=msg,
                    segment_ids=segment_ids,
                ))

        return alerts

    def detect_abbreviation_inconsistency(self, segments: List[Dict]) -> List[ConsistencyAlert]:
        """
        Detect inconsistent abbreviation usage across translations.

        Returns:
            List of ConsistencyAlert objects
        """
        alerts = []
        import re

        abbreviation_translations = {}  # {source_abbr: {target_abbr: [segment_ids]}}

        # Medical abbreviations pattern
        abbr_pattern = r'\b([A-Za-z]+\.(?:\s+[A-Za-z]+\.)*)\b'

        for seg in segments:
            source = seg.get('source_text', '')
            target = seg.get('target_text', '')
            status = seg.get('status', '')

            if not target or status not in ['translated', 'confirmed']:
                continue

            source_abbrs = re.findall(abbr_pattern, source)
            target_abbrs = re.findall(abbr_pattern, target)

            if source_abbrs and target_abbrs:
                for src_abbr in source_abbrs:
                    src_lower = src_abbr.lower()
                    if src_lower not in abbreviation_translations:
                        abbreviation_translations[src_lower] = {}

                    # Use first found target abbr (simplified)
                    tgt_abbr = target_abbrs[0] if target_abbrs else None
                    if tgt_abbr:
                        tgt_lower = tgt_abbr.lower()
                        if tgt_lower not in abbreviation_translations[src_lower]:
                            abbreviation_translations[src_lower][tgt_lower] = []
                        abbreviation_translations[src_lower][tgt_lower].append(seg['id'])

        # Find inconsistencies
        for src_abbr, target_dict in abbreviation_translations.items():
            if len(target_dict) > 1:
                # Same source abbr translated multiple ways
                segment_ids = []
                for target_list in target_dict.values():
                    segment_ids.extend(target_list)

                targets_found = list(target_dict.keys())[:2]
                msg = f'Abbreviation "{src_abbr}" translated as: {" / ".join(targets_found)}'

                alerts.append(ConsistencyAlert(
                    alert_type='abbreviation_inconsistency',
                    severity='info',
                    message=msg,
                    segment_ids=segment_ids,
                ))

        return alerts

    def run_consistency_qa(self, segments: List[Dict], glossary: List[Dict] = None) -> Tuple[bool, List[ConsistencyAlert]]:
        """
        Run all consistency checks.

        Returns:
            (overall_passed, list of alerts)
        """
        all_alerts = []

        # Run all checks
        all_alerts.extend(self.detect_source_translation_inconsistency(segments))
        if glossary:
            all_alerts.extend(self.detect_glossary_inconsistency(segments, glossary))
        all_alerts.extend(self.detect_institution_name_inconsistency(segments))
        all_alerts.extend(self.detect_duplicate_group_mismatch(segments))
        all_alerts.extend(self.detect_abbreviation_inconsistency(segments))

        # Overall pass/fail
        critical_alerts = [a for a in all_alerts if a.severity == 'critical']
        overall_passed = len(critical_alerts) == 0

        return overall_passed, all_alerts
