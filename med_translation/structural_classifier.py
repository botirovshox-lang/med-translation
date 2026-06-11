"""
structural_classifier.py — Segment intent classification via structural patterns.
No API calls. Detects: author lists, affiliations, titles, metadata, clinical content.
"""

import re


class StructuralClassifier:
    """
    Classify segment intent based on structural patterns:
    - author lists, affiliations, institutions
    - titles, headings, captions
    - clinical/numeric tables
    - simple metadata
    """

    # Russian academic/professional markers
    ACADEMIC_DEGREES = {
        'д.м.н.', 'к.м.н.', 'доктор медицинских наук', 'кандидат медицинских наук',
        'дмн', 'км.н.', 'phd', 'md', 'professor', 'профессор', 'доцент', 'ассистент',
        'заведующий', 'научный сотрудник', 'ведущий научный сотрудник',
        'главный врач', 'врач', 'биолог', 'химик', 'физик'
    }

    NAMED_AFTER_MARKERS = {
        'им.', 'имени', 'nomidagi', 'named after', 'посвящена', 'имя',
        'им ', 'имени ', 'nomidagi ', 'named after ', 'посвящен'
    }

    MEDICAL_SPECIALTIES = {
        'фтиз', 'пульмон', 'кардиолог', 'неврол', 'гастроэнтер', 'гепатол',
        'нефрол', 'уролог', 'эндокринол', 'иммунол', 'инфекцион', 'онколог',
        'гинеколог', 'педиатр', 'психиатр', 'хирург', 'травматол', 'ортопед',
        'радиол', 'патолог', 'микробиол', 'паразитол', 'клиническ', 'диагност'
    }

    def __init__(self):
        pass

    def classify(self, text, block_type=None):
        """
        Classify segment intent.

        Returns:
            dict: {
                'intent': str,
                'confidence': float,
                'signals': list,
                'detected_patterns': dict,
            }
        """
        if not text or len(text.strip()) < 2:
            return {
                'intent': 'metadata_simple',
                'confidence': 1.0,
                'signals': ['empty or very short'],
                'detected_patterns': {}
            }

        text = text.strip()
        signals = []
        patterns = {}

        # 1. Check for affiliation / biography pattern FIRST (higher priority)
        affiliation_result = self._detect_affiliation(text)
        if affiliation_result['score'] > 0.6:
            return {
                'intent': 'biography_or_affiliation',
                'confidence': affiliation_result['score'],
                'signals': affiliation_result['signals'],
                'detected_patterns': affiliation_result['patterns']
            }

        # 2. Check for SIMPLE author list pattern (after affiliation)
        author_list_result = self._detect_author_list(text)
        if author_list_result['score'] > 0.5:
            return {
                'intent': 'author_list',
                'confidence': author_list_result['score'],
                'signals': author_list_result['signals'],
                'detected_patterns': author_list_result['patterns']
            }

        # 3. Check for institution name pattern
        institution_result = self._detect_institution(text)
        if institution_result['score'] > 0.5:
            intent = 'institution_complex' if institution_result['is_complex'] else 'institution_simple'
            return {
                'intent': intent,
                'confidence': institution_result['score'],
                'signals': institution_result['signals'],
                'detected_patterns': institution_result['patterns']
            }

        # 4. Check for table / numeric pattern
        table_result = self._detect_table_or_numeric(text)
        if table_result['score'] > 0.6:
            return {
                'intent': 'table_or_numeric',
                'confidence': table_result['score'],
                'signals': table_result['signals'],
                'detected_patterns': table_result['patterns']
            }

        # 5. Check for title/heading pattern
        title_result = self._detect_title(text)
        if title_result['score'] > 0.5:
            intent = 'medical_title' if title_result['is_medical'] else 'figure_caption'
            return {
                'intent': intent,
                'confidence': title_result['score'],
                'signals': title_result['signals'],
                'detected_patterns': title_result['patterns']
            }

        # 6. Check for simple metadata
        if len(text) < 50 and not any(c in text for c in ['(', ')', '[', ']', '—', '–']):
            return {
                'intent': 'metadata_simple',
                'confidence': 0.6,
                'signals': ['short, no complex structure'],
                'detected_patterns': {}
            }

        # Default: medical_content
        return {
            'intent': 'medical_content',
            'confidence': 0.5,
            'signals': ['default medical content'],
            'detected_patterns': {}
        }

    def _detect_author_list(self, text):
        """Detect SIMPLE author list: initials + surnames, NO degrees/titles/institutions"""
        signals = []
        patterns = {}
        score = 0.0

        text_lower = text.lower()

        # DISQUALIFY if has academic degrees or titles (then it's affiliation, not simple author list)
        for degree in self.ACADEMIC_DEGREES:
            if degree in text_lower:
                return {
                    'score': 0.0,  # Disqualify
                    'signals': ['has academic degree → not simple author list'],
                    'patterns': {}
                }

        # DISQUALIFY if has institution keywords
        inst_keywords = ['центр', 'институт', 'университет', 'кафедра', 'больница', 'клиника',
                        'center', 'institute', 'university', 'department', 'hospital', 'clinic']
        for keyword in inst_keywords:
            if keyword in text_lower:
                return {
                    'score': 0.0,
                    'signals': ['has institution keyword → not simple author list'],
                    'patterns': {}
                }

        # Pattern: "А.Б.; В.Г.; Д.Е."
        initial_pairs = re.findall(r'\b[A-ZА-Я]\.[A-ZА-Я]\.', text)
        if len(initial_pairs) >= 1:
            score += 0.3
            signals.append(f'found {len(initial_pairs)} initial pairs')
            patterns['initial_pairs'] = len(initial_pairs)

        # Pattern: "Иванов И.И.; Петров П.П."
        cyrillic_initials = re.findall(r'\b[А-Яа-я]+\s+[A-ZА-Я]\.[A-ZА-Я]\.', text)
        if len(cyrillic_initials) >= 1:
            score += 0.3
            signals.append(f'found {len(cyrillic_initials)} surname + initials pairs')
            patterns['surname_initial_pairs'] = len(cyrillic_initials)

        # Separator: ; or ,
        separators = text.count(';') + text.count(',')
        if separators >= 1:
            score += 0.2
            signals.append(f'found {separators} separators')
            patterns['separators'] = separators

        # No long words (institution names)
        long_words = len([w for w in text.split() if len(w) > 15])
        if long_words == 0:
            score += 0.2
            signals.append('no long words (no institutions)')
            patterns['long_words'] = 0
        else:
            score -= 0.2  # Penalty

        return {
            'score': min(1.0, score),
            'signals': signals,
            'patterns': patterns
        }

    def _detect_affiliation(self, text):
        """Detect affiliation: person(s) + institution + optional degree/title"""
        signals = []
        patterns = {}
        score = 0.0

        text_lower = text.lower()

        # Check for person initials
        initials = re.findall(r'\b[A-ZА-Я]\.[A-ZА-Я]\.', text)
        if initials:
            score += 0.15
            signals.append(f'person initials detected')
            patterns['person_initials'] = True

        # Check for academic degree
        degree_match = False
        for degree in self.ACADEMIC_DEGREES:
            if degree in text_lower:
                score += 0.2
                signals.append(f'academic degree: {degree}')
                patterns['academic_degree'] = degree
                degree_match = True
                break

        # Check for professional title
        title_match = False
        for specialty in self.MEDICAL_SPECIALTIES:
            if specialty in text_lower:
                score += 0.2
                signals.append(f'medical specialty: {specialty}')
                patterns['medical_specialty'] = specialty
                title_match = True
                break

        # Check for institution markers
        institution_length = len([w for w in text.split() if len(w) > 8])
        if institution_length >= 2:
            score += 0.15
            signals.append('long words suggest institution')
            patterns['long_words'] = institution_length

        # Check for named-after marker
        for marker in self.NAMED_AFTER_MARKERS:
            if marker in text_lower:
                score += 0.15
                signals.append(f'named-after marker: {marker}')
                patterns['named_after'] = marker
                break

        # Check for comma/dash (person — title — institution structure)
        dash_count = text.count('—') + text.count('–')
        if dash_count >= 1:
            score += 0.1
            signals.append('dash suggests structured affiliation')
            patterns['dashes'] = dash_count

        return {
            'score': min(1.0, score),
            'signals': signals,
            'patterns': patterns
        }

    def _detect_institution(self, text):
        """Detect institution name: long formal structure"""
        signals = []
        patterns = {}
        score = 0.0
        is_complex = False

        text_lower = text.lower()

        # Check for medical specialty in institution name
        for specialty in self.MEDICAL_SPECIALTIES:
            if specialty in text_lower:
                score += 0.25
                signals.append(f'medical specialty in name: {specialty}')
                patterns['medical_specialty'] = specialty
                break

        # Check for institution keywords
        inst_keywords = [
            'центр', 'институт', 'университет', 'кафедра', 'больница', 'клиника',
            'лаборатория', 'отделение', 'научно-практический', 'специализирован',
            'center', 'institute', 'university', 'department', 'hospital', 'clinic'
        ]
        for keyword in inst_keywords:
            if keyword in text_lower:
                score += 0.15
                signals.append(f'institution keyword: {keyword}')
                patterns['institution_keyword'] = keyword
                break

        # Check for length/complexity
        words = text.split()
        if len(words) > 4:
            score += 0.15
            signals.append('long institution name')
            patterns['word_count'] = len(words)
            is_complex = True

        # Check for named-after
        for marker in self.NAMED_AFTER_MARKERS:
            if marker in text_lower:
                score += 0.2
                signals.append('named-after structure')
                patterns['named_after'] = True
                is_complex = True
                break

        # Check for parentheses (additional info)
        if '(' in text and ')' in text:
            score += 0.1
            signals.append('parenthetical info suggests detail')
            patterns['has_parens'] = True

        return {
            'score': min(1.0, score),
            'signals': signals,
            'patterns': patterns,
            'is_complex': is_complex
        }

    def _detect_table_or_numeric(self, text):
        """Detect table or numeric content: dosage, values, ranges"""
        signals = []
        patterns = {}
        score = 0.0

        # Count numbers
        numbers = re.findall(r'\d+(?:[.,]\d+)?', text)
        if len(numbers) >= 1:
            score += 0.2
            signals.append(f'found {len(numbers)} numbers')
            patterns['number_count'] = len(numbers)

        # Units: mg, ml, %, mmol, etc.
        units = re.findall(r'\d+\s*(?:мг|мл|%|ммоль|г|ед|iu|mg|ml|g|percent)', text, re.IGNORECASE)
        if units:
            score += 0.35
            signals.append(f'found {len(units)} measurements')
            patterns['measurements'] = len(units)

        # Ranges: 5-10, 0,5-1,5
        ranges = re.findall(r'\d+[.,]?\d*\s*[-–]\s*\d+[.,]?\d*', text)
        if ranges:
            score += 0.2
            signals.append(f'found {len(ranges)} ranges')
            patterns['ranges'] = len(ranges)

        # Table separators: | or —
        if '|' in text:
            score += 0.2
            signals.append('pipe separator detected')
            patterns['pipe_separator'] = True

        # Multiple lines / newlines
        if '\n' in text or '\t' in text:
            score += 0.15
            signals.append('multi-line structure')
            patterns['multi_line'] = True

        return {
            'score': min(1.0, score),
            'signals': signals,
            'patterns': patterns
        }

    def _detect_title(self, text):
        """Detect title/heading/caption"""
        signals = []
        patterns = {}
        score = 0.0
        is_medical = False

        text_lower = text.lower()

        # Short (heading-like)
        if len(text) < 100 and len(text.split()) < 15:
            score += 0.25
            signals.append('short length suggests heading')
            patterns['short'] = True

        # No numbers (usually)
        numbers = re.findall(r'\d+', text)
        if not numbers:
            score += 0.1
            signals.append('no numbers')
            patterns['no_numbers'] = True

        # Title keywords
        title_keywords = ['глава', 'раздел', 'введение', 'заключение', 'резюме',
                         'abstract', 'chapter', 'section', 'introduction', 'conclusion']
        for keyword in title_keywords:
            if keyword in text_lower:
                score += 0.2
                signals.append(f'title keyword: {keyword}')
                patterns['title_keyword'] = keyword
                break

        # Medical title check
        for specialty in self.MEDICAL_SPECIALTIES:
            if specialty in text_lower:
                score += 0.15
                signals.append('medical content in title')
                patterns['medical_specialty'] = specialty
                is_medical = True
                break

        # Capitalization pattern (English titles often start with capitals)
        if text[0].isupper() and text[-1].isalpha():
            score += 0.1
            signals.append('capitalization pattern')
            patterns['capitalized'] = True

        return {
            'score': min(1.0, score),
            'signals': signals,
            'patterns': patterns,
            'is_medical': is_medical
        }


def classify_segment(text, block_type=None):
    """Fast entry point."""
    classifier = StructuralClassifier()
    return classifier.classify(text, block_type)
