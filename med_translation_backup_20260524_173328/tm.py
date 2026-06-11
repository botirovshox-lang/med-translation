"""
tm.py — TM-поиск (мост между нашей системой и v5.5 app)
Возвращает найденные совпадения в формате, совместимом с v5.5.
"""
try:
    from tm_loader import get_tm
    HAS_ANTHROPIC_TM = True
except ImportError:
    HAS_ANTHROPIC_TM = False


def find_tm_suggestion(source_text, top_n=1, min_similarity=0.5):
    """
    Ищет TM-совпадение в локальной БД с fuzzy matching.
    Возвращает совпадение с оценкой схожести (0-100%).

    Формат возврата: {'source_text': ..., 'target_text': ..., 'score': ...}

    Оценка:
    - 100% = точное совпадение
    - 95%+ = очень похожий текст
    - 80%+ = похожий текст
    - 50%+ = частичное совпадение
    """
    import hashlib
    import re
    from difflib import SequenceMatcher
    from db import connect

    # Нормализуем текст для сравнения
    def normalize(text):
        return re.sub(r'\s+', ' ', (text or '').strip().lower())

    def text_hash(text):
        return hashlib.sha256(normalize(text).encode()).hexdigest()

    def similarity(a, b):
        """Вычисляет процент схожести двух текстов (0-100)"""
        return round(SequenceMatcher(None, normalize(a), normalize(b)).ratio() * 100, 1)

    source_norm = normalize(source_text)
    source_h = text_hash(source_text)

    # Ищем в локальной БД (translation_memory table)
    try:
        c = connect()
        rows = c.execute("SELECT * FROM translation_memory").fetchall()
        c.close()

        best_match = None
        best_score = 0

        for row in rows:
            r = dict(row)

            # Точное совпадение по хешу
            if r['source_hash'] == source_h:
                return {
                    'source_text': r['source_text'],
                    'target_text': r['target_text'],
                    'score': 100.0,
                }

            # Fuzzy matching - оценка схожести
            score = similarity(source_text, r['source_text'])

            if score > best_score and score >= min_similarity * 100:
                best_score = score
                best_match = {
                    'source_text': r['source_text'],
                    'target_text': r['target_text'],
                    'score': best_score,
                }

        # Возвращаем лучшее совпадение если оно достаточно хорошее
        if best_match and best_match['score'] >= 75:  # 75%+ показываем
            return best_match

        # Если нет хорошего совпадения в БД, пробуем Anthropic TM
        if not HAS_ANTHROPIC_TM:
            return None

        tm = get_tm()
        matches = tm.search(source_text, top_n=top_n)
        if matches and matches[0].score >= 99:
            return {
                'source_text': matches[0].entry.source_ru,
                'target_text': matches[0].entry.target_en,
                'score': matches[0].score,
            }
        return None

    except Exception as e:
        print(f"Error in TM search: {e}")
        return None
