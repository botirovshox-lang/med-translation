"""
zero_token_optimizer.py — Zero-token optimization через exact TM и duplicate propagation.
Снижает API вызовы перед переводом, используя уже переведенные сегменты.
"""
import hashlib
import re
from typing import Dict, List, Tuple
from db import connect, update_segment


def normalize_text(text):
    """Нормализация текста: пробелы, нижний регистр."""
    return re.sub(r'\s+', ' ', (text or '').strip().lower())


def text_hash(text):
    """SHA256 хеш нормализованного текста."""
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


class ZeroTokenOptimizer:
    """
    Оптимизация переводческого проекта через:
    1. Exact TM prefill — заполнение из проверенной памяти переводов
    2. Duplicate propagation — копирование переводов дубликатов
    """

    def __init__(self, project_id):
        self.project_id = project_id
        self.segments = []
        self.tm_cache = {}

    def load_segments(self):
        """Загрузить все сегменты проекта."""
        c = connect()
        rows = c.execute(
            "SELECT * FROM segments WHERE project_id = ?",
            (self.project_id,)
        ).fetchall()
        c.close()

        self.segments = [dict(row) for row in rows]
        return len(self.segments)

    def load_tm(self):
        """Загрузить Translation Memory (trusted entries only)."""
        c = connect()
        rows = c.execute("SELECT * FROM translation_memory WHERE approved = 1").fetchall()
        c.close()

        self.tm_cache = {}
        for row in rows:
            r = dict(row)
            source_hash = text_hash(r['source_ru'])
            if source_hash not in self.tm_cache:
                self.tm_cache[source_hash] = []
            self.tm_cache[source_hash].append(r)

    def apply_exact_tm_prefill(self, auto_confirm=False):
        """
        Part 1: Exact TM prefill
        Заполнить target_text из trusted TM для exact matches.

        Args:
            auto_confirm: bool — auto-confirm если risk=LOW + no forbidden + ...

        Returns:
            dict with:
                - prefilled_count: int
                - auto_confirmed_count: int
                - tm_savings_usd: float
        """
        self.load_segments()
        self.load_tm()

        prefilled_count = 0
        auto_confirmed_count = 0
        tm_savings_usd = 0.0

        for seg in self.segments:
            # Skip если уже переведен
            if seg.get('target_text'):
                continue

            # Skip если нет route info (preflight not run)
            if seg.get('route') != 'EXACT_TM':
                continue

            source_hash = text_hash(seg.get('source_text', ''))

            # Ищем exact TM match
            if source_hash not in self.tm_cache:
                continue

            tm_entries = self.tm_cache[source_hash]
            if not tm_entries:
                continue

            # Берем first entry (trusted)
            tm_entry = tm_entries[0]

            # Заполнить segment
            update_data = {
                'target_text': tm_entry['target_en'],
                'provider': 'TM',
                'status': 'tm_prefilled',
                'estimated_total_usd': 0,
                'tm_match_score': 100,
            }

            # Проверить условия для auto-confirm
            should_auto_confirm = False
            if auto_confirm:
                risk_level = seg.get('risk_level', 'MEDIUM')
                forbidden_count = len(seg.get('forbidden_warnings', []) or [])
                has_numeric = seg.get('detected_features', {}).get('numeric', False)

                if (
                    risk_level == 'LOW' and
                    forbidden_count == 0 and
                    not has_numeric
                ):
                    should_auto_confirm = True
                    update_data['status'] = 'confirmed'
                    auto_confirmed_count += 1

            update_segment(seg['id'], update_data)
            prefilled_count += 1

            # Estimate cost saved (translate + QA)
            # Approximate: translate ~$0.005, QA ~$0.003
            tm_savings_usd += 0.008

        return {
            'prefilled_count': prefilled_count,
            'auto_confirmed_count': auto_confirmed_count,
            'tm_savings_usd': round(tm_savings_usd, 2),
        }

    def prepare_duplicate_representatives(self):
        """
        Part 3: Prepare duplicate representatives
        Для каждой группы дубликатов выбрать representative.

        Стратегия выбора:
        - Первый non-empty в группе
        - Preferably lowest risk
        - Preferably not table_cell

        Marks:
        - representative: status = DUPLICATE_REPRESENTATIVE
        - others: status = DUPLICATE_PROPAGATION_PENDING
        """
        self.load_segments()

        # Группировать по duplicate_group_id
        groups = {}
        for seg in self.segments:
            gid = seg.get('duplicate_group_id')
            if not gid:
                continue

            if gid not in groups:
                groups[gid] = []
            groups[gid].append(seg)

        representative_count = 0
        pending_count = 0

        for gid, group_segments in groups.items():
            if len(group_segments) < 2:
                continue  # Not a duplicate group

            # Выбрать representative
            # Стратегия: non-empty, lowest risk, not table_cell
            candidates = [s for s in group_segments if s.get('source_text', '').strip()]
            if not candidates:
                candidates = group_segments

            # Sort by risk level (LOW > MEDIUM > HIGH > CRITICAL)
            risk_order = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2, 'CRITICAL': 3}
            candidates.sort(key=lambda s: (
                risk_order.get(s.get('risk_level', 'MEDIUM'), 999),
                1 if s.get('segment_intent') == 'table_or_numeric' else 0,
            ))

            representative = candidates[0]

            # Отметить representative
            update_segment(representative['id'], {
                'route': 'DUPLICATE_REPRESENTATIVE',
                'duplicate_representative': True,
            })
            representative_count += 1

            # Отметить остальные как pending
            for seg in group_segments:
                if seg['id'] != representative['id']:
                    update_segment(seg['id'], {
                        'route': 'DUPLICATE_PROPAGATION_PENDING',
                        'duplicate_representative_id': representative['id'],
                    })
                    pending_count += 1

        return {
            'representative_count': representative_count,
            'pending_count': pending_count,
        }

    def propagate_approved_duplicates(self):
        """
        Part 4: Propagate approved duplicates
        После того как representative подтвержден, распространить перевод на дубликаты.

        Conditions:
        - normalized source identical
        - block_type compatible OR risk = LOW
        - representative target exists
        - representative status = confirmed

        After propagation:
        - provider = duplicate_propagation
        - status = propagated_pending_review
        """
        self.load_segments()

        propagated_count = 0
        skipped_count = 0
        propagation_savings_usd = 0.0

        # Группировать по duplicate_group_id
        groups = {}
        for seg in self.segments:
            gid = seg.get('duplicate_group_id')
            if not gid:
                continue

            if gid not in groups:
                groups[gid] = []
            groups[gid].append(seg)

        for gid, group_segments in groups.items():
            if len(group_segments) < 2:
                continue

            # Найти representative в группе
            rep = next(
                (s for s in group_segments if s.get('duplicate_representative')),
                None
            )

            if not rep:
                continue

            # Проверить условия propagation
            if rep.get('status') != 'confirmed':
                skipped_count += len(group_segments) - 1
                continue

            if not rep.get('target_text'):
                skipped_count += len(group_segments) - 1
                continue

            # Propagate to all others
            rep_block_type = rep.get('block_type')
            for seg in group_segments:
                if seg['id'] == rep['id']:
                    continue

                # Check block_type compatibility
                seg_block_type = seg.get('block_type')
                seg_risk = seg.get('risk_level', 'MEDIUM')

                if seg_block_type != rep_block_type and seg_risk != 'LOW':
                    skipped_count += 1
                    continue

                # Propagate
                update_segment(seg['id'], {
                    'target_text': rep['target_text'],
                    'provider': 'duplicate_propagation',
                    'status': 'propagated_pending_review',
                    'estimated_total_usd': 0,
                    'duplicate_representative_id': rep['id'],
                })
                propagated_count += 1

                # Estimate cost saved (translate + QA)
                propagation_savings_usd += 0.008

        return {
            'propagated_count': propagated_count,
            'skipped_count': skipped_count,
            'propagation_savings_usd': round(propagation_savings_usd, 2),
        }

    def get_optimization_summary(self):
        """
        Получить summary текущего состояния zero-token optimization.
        """
        self.load_segments()

        summary = {
            'total_segments': len(self.segments),
            'tm_prefilled': len([s for s in self.segments if s.get('status') == 'tm_prefilled']),
            'tm_confirmed': len([s for s in self.segments if s.get('status') == 'confirmed' and s.get('provider') == 'TM']),
            'duplicate_groups': 0,
            'duplicate_segments': 0,
            'representatives_ready': len([s for s in self.segments if s.get('route') == 'DUPLICATE_REPRESENTATIVE']),
            'propagated': len([s for s in self.segments if s.get('status') == 'propagated_pending_review']),
        }

        # Count duplicate groups
        group_ids = set()
        for seg in self.segments:
            gid = seg.get('duplicate_group_id')
            if gid:
                group_ids.add(gid)

        summary['duplicate_groups'] = len(group_ids)
        summary['duplicate_segments'] = len([s for s in self.segments if s.get('duplicate_group_id')])

        return summary


def optimize_project(project_id, apply_tm=False, prepare_reps=False, propagate=False, auto_confirm=False):
    """
    Quick entry point для запуска zero-token optimization.

    Args:
        project_id: int
        apply_tm: bool — apply exact TM prefill
        prepare_reps: bool — prepare duplicate representatives
        propagate: bool — propagate approved duplicates
        auto_confirm: bool — auto-confirm when safe
    """
    optimizer = ZeroTokenOptimizer(project_id)
    results = {}

    if apply_tm:
        results['tm_prefill'] = optimizer.apply_exact_tm_prefill(auto_confirm=auto_confirm)

    if prepare_reps:
        results['prepare_reps'] = optimizer.prepare_duplicate_representatives()

    if propagate:
        results['propagation'] = optimizer.propagate_approved_duplicates()

    results['summary'] = optimizer.get_optimization_summary()

    return results
