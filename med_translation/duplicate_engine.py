"""
duplicate_engine.py — Обнаружение дубликатов сегментов
Поддерживает exact и fuzzy matching без API вызовов.
"""
import re
import hashlib
from difflib import SequenceMatcher


def normalize(text):
    """Нормализация текста для сравнения (lowercase, whitespace)."""
    return re.sub(r'\s+', ' ', (text or '').strip().lower())


def text_hash(text):
    """SHA256 хеш нормализованного текста."""
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def fuzzy_similarity(text_a, text_b):
    """Вычислить процент сходства двух текстов (0-100)."""
    ratio = SequenceMatcher(None, normalize(text_a), normalize(text_b)).ratio()
    return round(ratio * 100, 1)


class DuplicateAnalysis:
    """
    Анализ дубликатов в сегментах.

    Attributes:
        exact_duplicates: dict[str, list[int]] — hash → [segment_ids]
        fuzzy_groups: list[list[int]] — [[id1, id2, ...], ...]
        representative_ids: set[int] — Первый в каждой группе
        duplicate_count_map: dict — {segment_id: count_of_duplicates}
    """

    def __init__(self, segments, fuzzy_threshold=0.95):
        """
        Args:
            segments: list[dict] — сегменты с 'id', 'source_text'
            fuzzy_threshold: float — порог для fuzzy matching (0.0-1.0)
        """
        self.segments = segments
        self.fuzzy_threshold = fuzzy_threshold

        self.exact_duplicates = {}  # hash → [ids]
        self.fuzzy_groups = []      # [[ids], ...]
        self.representative_ids = set()
        self.duplicate_count_map = {}
        self.group_map = {}         # segment_id → group_id

    def detect_exact(self):
        """Обнаружить точные дубликаты по хешу."""
        hash_map = {}

        for seg in self.segments:
            h = text_hash(seg.get('source_text', ''))
            if h not in hash_map:
                hash_map[h] = []
            hash_map[h].append(seg['id'])

        # Сохранить только группы с дубликатами (len >= 2)
        for h, ids in hash_map.items():
            if len(ids) >= 2:
                self.exact_duplicates[h] = ids
                # Первый — representative
                self.representative_ids.add(ids[0])

    def detect_fuzzy(self):
        """
        Обнаружить нечеткие дубликаты используя fuzzy matching.
        Использует transitive closure для группирования.

        ⚠️ DISABLED for large projects (>500 segments) due to O(n²) complexity.
        """
        n = len(self.segments)
        if n == 0:
            return

        # Skip fuzzy matching for large projects (O(n²) = too slow)
        if n > 500:
            return  # Only exact matching for large projects

        # Матрица сходства (upper triangle)
        similarity_matrix = {}

        for i in range(n):
            for j in range(i + 1, n):
                seg_i = self.segments[i]
                seg_j = self.segments[j]

                similarity = fuzzy_similarity(
                    seg_i.get('source_text', ''),
                    seg_j.get('source_text', '')
                )

                if similarity / 100 >= self.fuzzy_threshold:
                    pair = (seg_i['id'], seg_j['id'])
                    similarity_matrix[pair] = similarity

        # Использовать Union-Find для transitive closure
        parent = {}

        def find(x):
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Union все похожие пары
        for (id_i, id_j), sim in similarity_matrix.items():
            union(id_i, id_j)

        # Группировать по root
        groups_dict = {}
        for seg in self.segments:
            root = find(seg['id'])
            if root not in groups_dict:
                groups_dict[root] = []
            groups_dict[root].append(seg['id'])

        # Сохранить только группы с дубликатами (len >= 2)
        for root, ids in groups_dict.items():
            if len(ids) >= 2:
                sorted_ids = sorted(ids)  # Для консистентности
                self.fuzzy_groups.append(sorted_ids)
                # Первый — representative
                self.representative_ids.add(sorted_ids[0])

    def assign_group_ids(self):
        """
        Присвоить group_id каждому сегменту.

        Returns:
            dict: {segment_id: {
                'group_id': int,
                'is_representative': bool,
                'group_members': [ids],
                'duplicate_count': int
            }}
        """
        result = {}
        group_counter = 0

        # Присвоить группы из exact дубликатов
        assigned = set()
        for hash_val, ids in self.exact_duplicates.items():
            group_id = group_counter
            group_counter += 1

            for seg_id in ids:
                result[seg_id] = {
                    'group_id': group_id,
                    'is_representative': seg_id == ids[0],
                    'group_members': ids,
                    'duplicate_count': len(ids) - 1,  # Сколько других есть
                }
                assigned.add(seg_id)

        # Присвоить группы из fuzzy дубликатов (не включённые в exact)
        for ids in self.fuzzy_groups:
            # Пропустить если уже assigned в exact
            if any(seg_id in assigned for seg_id in ids):
                continue

            group_id = group_counter
            group_counter += 1

            for seg_id in ids:
                result[seg_id] = {
                    'group_id': group_id,
                    'is_representative': seg_id == ids[0],
                    'group_members': ids,
                    'duplicate_count': len(ids) - 1,
                }
                assigned.add(seg_id)

        # Сегменты без дубликатов (group_id = null)
        for seg in self.segments:
            if seg['id'] not in assigned:
                result[seg['id']] = {
                    'group_id': None,
                    'is_representative': True,
                    'group_members': [seg['id']],
                    'duplicate_count': 0,
                }

        return result

    def get_analysis_summary(self):
        """Получить итоговую статистику анализа."""
        total_segs = len(self.segments)

        # Count segments in groups
        in_exact_groups = sum(len(ids) for ids in self.exact_duplicates.values())
        in_fuzzy_groups = sum(len(ids) for ids in self.fuzzy_groups)
        unique_segs = total_segs - in_exact_groups - in_fuzzy_groups

        # Count groups
        total_groups = len(self.exact_duplicates) + len(self.fuzzy_groups)
        representatives = len(self.representative_ids)

        return {
            'total_segments': total_segs,
            'unique_segments': unique_segs,
            'segments_in_exact_groups': in_exact_groups,
            'segments_in_fuzzy_groups': in_fuzzy_groups,
            'total_duplicate_groups': total_groups,
            'representative_segments': representatives,
            'exact_duplicate_groups': len(self.exact_duplicates),
            'fuzzy_duplicate_groups': len(self.fuzzy_groups),
            'potential_cost_savings': in_exact_groups + in_fuzzy_groups,  # Можно пропустить
        }


def run_duplicate_analysis(segments, fuzzy_threshold=0.95):
    """
    Быстрая функция для запуска анализа дубликатов.

    Args:
        segments: list[dict] — сегменты с 'id', 'source_text'
        fuzzy_threshold: float — порог для fuzzy matching

    Returns:
        dict: {
            'summary': dict,
            'group_assignments': dict,
            'exact_duplicates': dict,
            'fuzzy_groups': list,
        }
    """
    analyzer = DuplicateAnalysis(segments, fuzzy_threshold=fuzzy_threshold)
    analyzer.detect_exact()
    analyzer.detect_fuzzy()
    assignments = analyzer.assign_group_ids()

    return {
        'summary': analyzer.get_analysis_summary(),
        'group_assignments': assignments,
        'exact_duplicates': analyzer.exact_duplicates,
        'fuzzy_groups': analyzer.fuzzy_groups,
        'representative_ids': list(analyzer.representative_ids),
    }
