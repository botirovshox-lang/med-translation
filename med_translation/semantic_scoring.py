"""
semantic_scoring.py — Многофакторное семантическое оценивание
Легковесные локальные эвристики для определения безопасности Google Translate
и сложности перевода без использования больших словарей ключевых слов.
"""

import re


class SemanticScorer:
    """
    6-факторное семантическое оценивание сегментов (0.0-1.0 диапазон).
    Используются легковесные эвристики вместо больших список ключевых слов.
    """

    # Russian medical morphology families (broad patterns, not keywords)
    RUSSIAN_MEDICAL_ROOTS = {
        'лог': 'science/study',      # логия, логи, логия
        'терап': 'therapy',           # терапия, терапевт
        'пат': 'disease/suffering',   # патология, патогенез
        'генез': 'origin/development',# генез, генеза
        'невро': 'nerve',             # невролог, неврология
        'кардио': 'heart',            # кардиолог, кардиопатия
        'эндокрин': 'endocrine',      # эндокринолог
        'пневм': 'lung/air',          # пневмония, пневмолог
        'пульмон': 'lung',            # пульмонология
        'фтиз': 'tuberculosis',       # фтизиатрия
        'инфекц': 'infection',        # инфекция, инфекционист
        'гепат': 'liver',             # гепатология
        'нефр': 'kidney',             # нефролог
        'уролог': 'urology',          # уролог
        'гастро': 'stomach/gastric',  # гастроэнтерология
        'онко': 'tumor/cancer',       # онколог, онкология
        'гинек': 'woman/gynecology',  # гинеколог
        'педиатр': 'child',           # педиатрия
        'псих': 'mind/psychology',    # психиатр
        'хирург': 'surgery',          # хирург, хирургия
        'травмат': 'trauma',          # травматолог
        'ортопед': 'orthopedic',      # ортопедия
        'радиол': 'radiation',        # радиология
        'фармак': 'drug/pharmacy',    # фармакология
        'иммун': 'immunity',          # иммунология
        'бактери': 'bacteria',        # бактериология
        'вирус': 'virus',             # вирусология
        'клиник': 'clinical',         # клиника, клинический
        'диагност': 'diagnosis',      # диагностика
        'симптом': 'symptom',         # симптом, симптоматология
        'синдром': 'syndrome',        # синдром
        'анат': 'anatomy',            # анатомия
        'физиол': 'physiology',       # физиология
        'биолог': 'biology',          # биология, биолог
    }

    # Типичные медицинские сокращения (без точек)
    MEDICAL_ABBREVIATIONS = {
        'mg', 'ml', 'iu', 'mm', 'cm', 'mm3', 'ml/min',
        'iv', 'im', 'sc', 'po', 'pr', 'od', 'bid', 'tid', 'qid',
        'prn', 'hs', 'am', 'pm', 'qd', 'qw', 'qm',
        'hgb', 'wbc', 'rbc', 'plt', 'bp', 'hr', 'rr', 'temp',
        'ekg', 'echo', 'ct', 'mri', 'us', 'xray', 'pet',
        'icu', 'er', 'ed', 'or', 'ipm', 'icu',
        'pt', 'inr', 'ptt', 'ast', 'alt', 'alp', 'ggt',
        'fasting', 'postprandial', 'glucose', 'insulin',
        'hba1c', 'a1c', 'tsH', 'tsh', 'ft4', 'ft3',
        'nterminal', 'bnp', 'troponin', 'ck',
        'creatinine', 'bun', 'egfr', 'uacr',
        'lvef', 'ef', 'cor', 'v', 'i', 'ii', 'iii', 'iv',
    }

    def __init__(self):
        """Инициализировать scorer."""
        pass

    def semantic_density_score(self, text):
        """
        Плотность медицинской терминологии / сокращений / инициалов.
        Высокий скор = много специальных медицинских терминов.

        Args:
            text: str — исходный текст

        Returns:
            float: 0.0-1.0 (высокий = плотный медицинский текст)
        """
        if not text or len(text) < 5:
            return 0.0

        text_lower = text.lower()
        words = text_lower.split()
        word_count = max(len(words), 1)

        density_score = 0.0

        # 1. Медицинские морфемы (русские корни)
        suffix_matches = 0
        for root in self.RUSSIAN_MEDICAL_ROOTS.keys():
            if root in text_lower:
                suffix_matches += text_lower.count(root)

        if suffix_matches > 0:
            density_score += min(0.4, suffix_matches / word_count)

        # 2. Медицинские сокращения (слова в ALL CAPS или с точками)
        abbreviation_matches = 0
        for abbrev in self.MEDICAL_ABBREVIATIONS:
            # Поиск как отдельного слова (с точками или без)
            pattern = re.compile(r'\b' + re.escape(abbrev) + r'\.?\b', re.IGNORECASE)
            matches = pattern.findall(text_lower)
            abbreviation_matches += len(matches)

        if abbreviation_matches > 0:
            density_score += min(0.35, abbreviation_matches / word_count)

        # 3. Инициалы (одиночные ЗАГЛАВНЫЕ буквы с точками или без, типа "Dr.", "Mr.")
        initial_pattern = re.compile(r'\b[A-Z]\.?\s+[A-Z][a-z]+')
        initial_count = len(initial_pattern.findall(text))
        if initial_count > 0:
            density_score += min(0.15, initial_count / max(word_count / 10, 1))

        # 4. Числа с единицами (5mg, 10ml, 25%)
        numeric_unit_pattern = re.compile(r'\d+\s*(?:mg|ml|iu|%|mmol|g|kg|mm|cm)\b', re.IGNORECASE)
        numeric_matches = len(numeric_unit_pattern.findall(text))
        if numeric_matches > 0:
            density_score += min(0.1, numeric_matches / max(word_count / 10, 1))

        return min(1.0, density_score)

    def medicality_score(self, text):
        """
        Насколько "медицинским" является содержание vs обычный текст.
        Использует русские морфемы медицинского происхождения.

        Args:
            text: str — исходный текст

        Returns:
            float: 0.0-1.0 (высокий = очень медицинский)
        """
        if not text or len(text) < 5:
            return 0.0

        text_lower = text.lower()
        word_count = max(len(text_lower.split()), 1)
        medicality = 0.0

        # 1. Russian medical morphology families
        russian_matches = 0
        for root in self.RUSSIAN_MEDICAL_ROOTS.keys():
            if root in text_lower:
                russian_matches += text_lower.count(root)

        if russian_matches > 0:
            medicality += min(0.4, russian_matches / (word_count / 2))

        # 2. Latin/Greek medical suffixes (English-style)
        english_suffixes = ['-itis', '-osis', '-emia', '-ectomy', '-tomy', '-plasty',
                           '-penia', '-lysis', '-opathy', '-algia', '-dynia']
        suffix_matches = 0
        for suffix in english_suffixes:
            if suffix in text_lower:
                suffix_matches += text_lower.count(suffix)

        if suffix_matches > 0:
            medicality += min(0.25, suffix_matches / (word_count / 2))

        # 3. Medical abbreviations in caps
        caps_pattern = re.compile(r'\b[A-Z]{2,}\b')
        caps_count = len(caps_pattern.findall(text))
        if caps_count > 0:
            medicality += min(0.15, caps_count / max(word_count / 10, 1))

        # 4. Scientific/clinical phrase patterns (в том числе на русском)
        clinical_keywords = ['диагноз', 'симптом', 'синдром', 'болезнь', 'заболевание',
                            'лечение', 'терапия', 'операция', 'хирургия', 'исследование',
                            'анализ', 'тест', 'лабораторный', 'клинический', 'медицинский',
                            'диагностика', 'прогноз', 'рецидив', 'рекомендация',
                            'contraindication', 'adverse', 'efficacy', 'dosage', 'protocol']
        clinical_matches = 0
        for keyword in clinical_keywords:
            if keyword in text_lower:
                clinical_matches += 1

        if clinical_matches > 0:
            medicality += min(0.2, clinical_matches / 10)

        return min(1.0, medicality)

    def entity_complexity_score(self, text, detected_features=None):
        """
        Сложность сущностей: количество и разнообразие обнаруженных сущностей
        (анатомия, болезни, дозировка и т.д.).

        Args:
            text: str — исходный текст
            detected_features: dict — результаты detection (anatomy, dosage, etc.)

        Returns:
            float: 0.0-1.0 (высокий = много разнообразных сущностей)
        """
        if not text:
            return 0.0

        complexity = 0.0

        # 1. Использование detected_features если доступно
        if detected_features and isinstance(detected_features, dict):
            feature_count = sum(1 for v in detected_features.values() if v)
            max_features = 8  # Примерно сколько может быть типов
            if feature_count > 0:
                complexity += min(0.5, feature_count / max_features)

        # 2. Количество именованных сущностей (капитализированные слова)
        capitalized_pattern = re.compile(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b')
        entity_count = len(capitalized_pattern.findall(text))
        word_count = max(len(text.split()), 1)
        if entity_count > 0:
            complexity += min(0.25, entity_count / max(word_count / 5, 1))

        # 3. Сложные структуры (скобки, дефисы, слеши = часто используются для структурирования мединф)
        structural_elements = (
            text.count('(') + text.count('[') + text.count('{') +
            text.count(',') + text.count(';') + text.count(':')
        )
        if structural_elements > 0:
            complexity += min(0.15, structural_elements / max(word_count / 3, 1))

        # 4. Интерстиция (есть ли "and/or", "both", "either" — показывает разветвлённость)
        branching_keywords = ['and/or', 'either', 'both', 'multiple', 'various', 'several']
        branching_count = sum(1 for kw in branching_keywords if kw in text.lower())
        if branching_count > 0:
            complexity += min(0.1, branching_count / 3)

        return min(1.0, complexity)

    def reversibility_risk_score(self, text):
        """
        Риск потери смысла при back-translation (обратном переводе).
        Высокий скор = высокий риск, низкий скор = безопасен для Google (можно back-translate).

        Args:
            text: str — исходный текст

        Returns:
            float: 0.0-1.0 (высокий = высокий риск потери смысла)
        """
        if not text:
            return 0.0

        text_lower = text.lower()
        word_count = max(len(text.split()), 1)

        risk = 0.0

        # 1. Плотность числовых значений (диапазоны, десятичные, проценты = сложно back-translate)
        numeric_pattern = re.compile(r'\d+[\d,.\-/]+\d*|\d+\.?\d+%?')
        numeric_count = len(numeric_pattern.findall(text))
        if numeric_count > 0:
            risk += min(0.3, numeric_count / max(word_count / 5, 1))

        # 2. Сокращения и акронимы (тяжело back-translate без контекста)
        abbreviation_count = len([w for w in text.split() if len(w) <= 4 and w.isupper()])
        if abbreviation_count > 0:
            risk += min(0.25, abbreviation_count / max(word_count / 10, 1))

        # 3. Специальные символы и пунктуация (/, -, дефис в составе слова)
        special_char_count = text.count('/') + text.count('-') + text.count('–')
        if special_char_count > 0:
            risk += min(0.2, special_char_count / 10)

        # 4. Скрытые структуры (таблицы в виде текста с разделителями)
        if '|' in text or '→' in text or '←' in text:
            risk += 0.15

        # 5. Вложенные структуры (скобки в скобках = очень сложно)
        nested_count = max(
            text.count('(('), text.count('[['),
            text.count('(('), text.count('{{')
        )
        if nested_count > 0:
            risk += 0.1

        # 6. Наличие инструкций, условий (if, else, when = логические зависимости)
        logic_keywords = ['if', 'then', 'else', 'when', 'unless', 'provided', 'in case']
        logic_count = sum(1 for kw in logic_keywords if ' ' + kw + ' ' in ' ' + text_lower + ' ')
        if logic_count > 0:
            risk += min(0.15, logic_count / 3)

        return min(1.0, risk)

    def clinical_criticality_score(self, text, risk_level='MEDIUM'):
        """
        Клиническая критичность: комбинация уровня риска + дозировки + числовых параметров.
        Высокий скор = очень критично (требует человека или лучшую модель).

        Args:
            text: str — исходный текст
            risk_level: str — 'CRITICAL'|'HIGH'|'MEDIUM'|'LOW' из risk_engine

        Returns:
            float: 0.0-1.0 (высокий = критично)
        """
        if not text:
            return 0.0

        criticality = 0.0

        # 1. Risk level baseline (из risk_engine)
        risk_base_scores = {
            'CRITICAL': 0.95,
            'HIGH': 0.65,
            'MEDIUM': 0.35,
            'LOW': 0.05,
        }
        criticality = risk_base_scores.get(risk_level, 0.5)

        # 2. Дозировка (очень критично — ошибка может привести к передозировке)
        dosage_pattern = re.compile(
            r'(\d+(?:\.\d+)?)\s*(?:mg|ml|iu|g|mcg|μg|unit|units)\b',
            re.IGNORECASE
        )
        dosage_count = len(dosage_pattern.findall(text))
        if dosage_count > 0:
            criticality += min(0.2, dosage_count * 0.1)

        # 3. Критические параметры (давление, частота сердцебиения, etc.)
        critical_params = [
            'blood pressure', 'systolic', 'diastolic', 'heart rate', 'respiratory rate',
            'temperature', 'oxygen saturation', 'glucose level', 'blood sugar',
            'hemoglobin', 'hematocrit', 'platelet', 'white blood cell', 'red blood cell'
        ]
        param_count = sum(1 for param in critical_params if param in text.lower())
        if param_count > 0:
            criticality += min(0.15, param_count * 0.05)

        # 4. Противопоказания, побочные эффекты (очень критично)
        critical_keywords = ['contraindication', 'side effect', 'adverse', 'toxicity',
                           'overdose', 'allergic', 'anaphylaxis', 'severe', 'fatal']
        critical_count = sum(1 for kw in critical_keywords if kw in text.lower())
        if critical_count > 0:
            criticality += min(0.1, critical_count * 0.05)

        return min(1.0, criticality)

    def google_safe_confidence(self, text, risk_level='MEDIUM', detected_features=None):
        """
        Позитивная уверенность в безопасности Google Translate.
        Высокий скор = БЕЗОПАСНО отправить в Google (ТОЛЬКО если >= 0.98).
        Низкий скор = НЕБЕЗОПАСНО (требует лучшей модели).

        ПОЗИТИВНАЯ ЛОГИКА:
        - Высокий скор (0.9-1.0) = низкий риск + простая структура = GOOGLE OK
        - Средний скор (0.5-0.89) = неопределённость = ROUTE UPWARD (GPT_REQUIRED)
        - Низкий скор (0.0-0.49) = высокий риск + сложность = GOOGLE BLOCKED

        Args:
            text: str — исходный текст
            risk_level: str — 'CRITICAL'|'HIGH'|'MEDIUM'|'LOW'
            detected_features: dict — результаты detection

        Returns:
            float: 0.0-1.0 (высокий = БЕЗОПАСНО для Google)
        """
        if not text or len(text) < 5:
            return 0.0

        # Начинаем с базовой позитивной уверенности (1.0)
        confidence = 1.0

        # 1. Risk level penalty (INVERSION: LOW = хорошо, HIGH = плохо)
        risk_penalties = {
            'CRITICAL': -0.95,  # Полностью блокируем Google
            'HIGH': -0.60,      # Почти блокируем
            'MEDIUM': -0.25,    # Слегка снижаем
            'LOW': 0.0,         # Ничего не снижаем
        }
        confidence += risk_penalties.get(risk_level, -0.25)

        # 2. Entity complexity penalty (много сущностей = сложнее для Google)
        entity_complexity = self.entity_complexity_score(text, detected_features)
        if entity_complexity > 0.6:
            confidence -= 0.35
        elif entity_complexity > 0.3:
            confidence -= 0.15

        # 3. Reversibility risk penalty (высокий риск потери смысла = плохо для Google)
        reversibility_risk = self.reversibility_risk_score(text)
        if reversibility_risk > 0.6:
            confidence -= 0.40
        elif reversibility_risk > 0.3:
            confidence -= 0.20

        # 4. Semantic density penalty (очень медицинский = может быть проблемой)
        semantic_density = self.semantic_density_score(text)
        if semantic_density > 0.7:
            confidence -= 0.30
        elif semantic_density > 0.4:
            confidence -= 0.15

        # 5. Medicality penalty (очень медицинский текст требует лучшей модели)
        medicality = self.medicality_score(text)
        if medicality > 0.7:
            confidence -= 0.25
        elif medicality > 0.4:
            confidence -= 0.10

        # 6. Clinical criticality penalty (критичное содержание требует GPT)
        clinical_criticality = self.clinical_criticality_score(text, risk_level)
        if clinical_criticality > 0.7:
            confidence -= 0.50
        elif clinical_criticality > 0.4:
            confidence -= 0.25

        # Гарантируем диапазон 0.0-1.0
        confidence = max(0.0, min(1.0, confidence))

        return round(confidence, 3)

    def score_segment(self, text, risk_level='MEDIUM', detected_features=None):
        """
        Вычислить все 6 оценок для сегмента.

        Args:
            text: str — исходный текст
            risk_level: str — уровень риска из risk_engine
            detected_features: dict — обнаруженные признаки

        Returns:
            dict: {
                'semantic_density_score': float,
                'medicality_score': float,
                'entity_complexity_score': float,
                'reversibility_risk_score': float,
                'clinical_criticality_score': float,
                'google_safe_confidence': float,
            }
        """
        return {
            'semantic_density_score': round(self.semantic_density_score(text), 3),
            'medicality_score': round(self.medicality_score(text), 3),
            'entity_complexity_score': round(self.entity_complexity_score(text, detected_features), 3),
            'reversibility_risk_score': round(self.reversibility_risk_score(text), 3),
            'clinical_criticality_score': round(self.clinical_criticality_score(text, risk_level), 3),
            'google_safe_confidence': round(self.google_safe_confidence(text, risk_level, detected_features), 3),
        }


def score_segment_fast(text, risk_level='MEDIUM', detected_features=None):
    """
    Быстрая функция для оценки сегмента.

    Args:
        text: str — исходный текст
        risk_level: str — уровень риска
        detected_features: dict — обнаруженные признаки

    Returns:
        dict: Все 6 оценок
    """
    scorer = SemanticScorer()
    return scorer.score_segment(text, risk_level, detected_features)
