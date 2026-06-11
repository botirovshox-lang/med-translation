"""
safety_policy.py — Правила безопасности, маршрутизации и политики одобрения
Без API вызовов, локальные правила и пороги.
"""


class SafetyPolicyEngine:
    """
    Механизм принятия решений для маршрутизации и политик.
    """

    # Пороги для уровней риска
    RISK_THRESHOLDS = {
        'CRITICAL': (75, 100),
        'HIGH': (50, 74),
        'MEDIUM': (25, 49),
        'LOW': (0, 24),
    }

    # Правила маршрутизации
    ROUTING_RULES = {
        'exact_tm_threshold': 99.0,         # >= 99% TM → EXACT_TM
        'fuzzy_tm_threshold': 85.0,         # >= 85% TM → could optimize
        'glossary_heavy_threshold': 3,      # >= 3 glossary matches → GLOSSARY_REQUIRED
        'low_risk_no_anatomy': True,        # LOW risk + no anatomy → GOOGLE_SAFE
    }

    def __init__(self):
        """Инициализировать engine с default правилами."""
        pass

    def calculate_risk_level(self, risk_score):
        """
        Преобразовать risk_score (0-100) в категорию.

        Args:
            risk_score: float — скор от 0 до 100

        Returns:
            str: 'CRITICAL'|'HIGH'|'MEDIUM'|'LOW'
        """
        for level, (min_score, max_score) in self.RISK_THRESHOLDS.items():
            if min_score <= risk_score <= max_score:
                return level
        return 'MEDIUM'  # Default

    def select_qa_policy(self, risk_level):
        """
        Выбрать QA политику основано на уровне риска.

        Args:
            risk_level: str — 'CRITICAL'|'HIGH'|'MEDIUM'|'LOW'

        Returns:
            str: 'auto_pass'|'manual'|'strict'
        """
        if risk_level == 'CRITICAL':
            return 'strict'  # Полная проверка + human review
        elif risk_level == 'HIGH':
            return 'strict'  # Полная проверка
        elif risk_level == 'MEDIUM':
            return 'manual'  # Стандартная проверка
        else:  # LOW
            return 'auto_pass'  # Автоматическая проверка (lenient)

    def select_approval_policy(self, risk_level):
        """
        Выбрать политику одобрения основано на уровне риска.

        Args:
            risk_level: str — 'CRITICAL'|'HIGH'|'MEDIUM'|'LOW'

        Returns:
            str: 'single_human'|'dual_human'|'automated'
        """
        if risk_level == 'CRITICAL':
            return 'dual_human'  # Два человека должны одобрить
        elif risk_level == 'HIGH':
            return 'single_human'  # Один человек должен одобрить
        elif risk_level == 'MEDIUM':
            return 'single_human'  # Один человек может одобрить
        else:  # LOW
            return 'automated'  # Автоматическое одобрение возможно

    def route_segment(self, segment_context):
        """
        Определить маршрут для сегмента основано на контексте с семантическим оцениванием.

        Args:
            segment_context: dict — {
                'segment_id': int,
                'source_text': str,
                'tm_match_score': float (0-100),
                'duplicate_group_id': int|None,
                'is_representative': bool,
                'glossary_match_count': int,
                'risk_level': str,
                'detected_features': dict,
                'google_safe_confidence': float (0.0-1.0, опционально),
            }

        Returns:
            str: Маршрут (см. ниже)
        """
        tm_score = segment_context.get('tm_match_score', 0)
        risk_level = segment_context.get('risk_level', 'MEDIUM')
        glossary_count = segment_context.get('glossary_match_count', 0)
        features = segment_context.get('detected_features', {})
        duplicate_group = segment_context.get('duplicate_group_id')
        is_representative = segment_context.get('is_representative', True)
        google_safe_confidence = segment_context.get('google_safe_confidence', 0.0)

        # Rule 1: Проверить точное совпадение в TM (99%+)
        if tm_score >= self.ROUTING_RULES['exact_tm_threshold']:
            return 'EXACT_TM'

        # Rule 2: Проверить дубликаты
        if duplicate_group is not None:
            if is_representative:
                # Первый в группе → Translate
                return 'DUPLICATE_REPRESENTATIVE'
            else:
                # Остальные → Propagate (copy from representative)
                return 'DUPLICATE_PROPAGATION_PENDING'

        # Rule 3: Проверить критичный риск
        if risk_level == 'CRITICAL':
            return 'HUMAN_REVIEW_REQUIRED'

        # Rule 4: Высокий риск → требует glossary context
        if risk_level == 'HIGH':
            if glossary_count > 0:
                return 'GPT_WITH_GLOSSARY_REQUIRED'
            else:
                return 'HUMAN_REVIEW_REQUIRED'

        # Rule 5: Проверить glossary требования
        if glossary_count >= self.ROUTING_RULES['glossary_heavy_threshold']:
            return 'GPT_WITH_GLOSSARY_REQUIRED'

        # Rule 6: Google Safe — ТОЛЬКО если google_safe_confidence >= 0.98
        # ПОЗИТИВНАЯ ЛОГИКА: высокий скор = БЕЗОПАСНО для Google
        if risk_level == 'LOW' and not features.get('anatomy', False):
            # Семантическое оценивание доступно?
            if google_safe_confidence >= 0.98:
                # Высокая уверенность → Google SAFE
                return 'GOOGLE_SAFE'
            elif google_safe_confidence > 0.85:
                # Неопределённость (0.85-0.98) → маршрут вверх к GPT
                return 'GPT_REQUIRED'
            # Если < 0.85, тоже маршрут вверх

        # Default: GPT required
        return 'GPT_REQUIRED'

    def get_routing_explanation(self, route):
        """Получить человеко-понятное объяснение маршрута."""
        explanations = {
            'EXACT_TM': 'Точное совпадение в Translation Memory (99%+) — использовать существующий перевод',
            'DUPLICATE_REPRESENTATIVE': 'Первый сегмент в группе дубликатов — перевести один раз',
            'DUPLICATE_PROPAGATION_PENDING': 'Дубликат другого сегмента — скопировать перевод от representative',
            'GOOGLE_SAFE': 'Низкий риск, нет анатомии — использовать Google Translate (бесплатно)',
            'GPT_REQUIRED': 'Требуется OpenAI GPT для перевода и QA',
            'GPT_WITH_GLOSSARY_REQUIRED': 'Требуется OpenAI GPT с инъекцией глоссария (много медицинских терминов или HIGH риск)',
            'HUMAN_REVIEW_REQUIRED': 'Критичный или высокий риск без глоссария — требует человеческий review',
        }
        return explanations.get(route, 'Неизвестный маршрут')

    def estimate_workflow_steps(self, route, risk_level):
        """
        Определить required workflow шаги для маршрута.

        Returns:
            list[str]: Шаги ('translate', 'qa', 'backcheck', 'safety', 'human_review')
        """
        steps = []

        if route in ['EXACT_TM', 'DUPLICATE_PROPAGATION_PENDING']:
            # No steps needed for source-level TM or propagation
            return []

        if route == 'GOOGLE_SAFE':
            steps = ['translate']  # Just translate, no QA
            return steps

        if route == 'DUPLICATE_REPRESENTATIVE':
            steps = ['translate']
            if risk_level in ['HIGH', 'CRITICAL']:
                steps.append('qa')
            return steps

        # GPT routes
        steps = ['translate', 'qa']

        if risk_level in ['CRITICAL', 'HIGH']:
            steps.append('backcheck')
            steps.append('safety')

        if route == 'HUMAN_REVIEW_REQUIRED':
            steps.append('human_review')

        return steps

    def get_default_batch_order(self, segments_with_routes):
        """
        Рекомендовать порядок обработки для оптимизации затрат.

        Стратегия:
        1. EXACT_TM (cost: $0)
        2. DUPLICATE_REPRESENTATIVE (translate once)
        3. GOOGLE_SAFE (cost: $0, fast)
        4. GPT_REQUIRED (cost: moderate)
        5. GPT_WITH_GLOSSARY_REQUIRED (cost: moderate, longer)
        6. HUMAN_REVIEW_REQUIRED (cost: $0 API, но требует человека)

        Args:
            segments_with_routes: list[dict] — с полем 'route'

        Returns:
            list[int]: segment IDs в рекомендуемом порядке
        """
        route_priority = {
            'EXACT_TM': 0,
            'DUPLICATE_PROPAGATION_PENDING': 1,
            'GOOGLE_SAFE': 2,
            'DUPLICATE_REPRESENTATIVE': 3,  # After easy wins
            'GPT_REQUIRED': 4,
            'GPT_WITH_GLOSSARY_REQUIRED': 5,
            'HUMAN_REVIEW_REQUIRED': 6,
        }

        def sort_key(seg):
            route = seg.get('route', 'GPT_REQUIRED')
            priority = route_priority.get(route, 99)
            seg_id = seg.get('id', 0)
            return (priority, seg_id)  # Primary: priority, secondary: id

        sorted_segments = sorted(segments_with_routes, key=sort_key)
        return [seg['id'] for seg in sorted_segments]

    def get_route_counts(self, segments_with_routes):
        """
        Подсчитать сегменты по маршрутам.

        Returns:
            dict: {route: count}
        """
        counts = {}
        for seg in segments_with_routes:
            route = seg.get('route', 'unknown')
            counts[route] = counts.get(route, 0) + 1
        return counts


def create_safety_engine():
    """Быстрая функция для создания engine."""
    return SafetyPolicyEngine()
