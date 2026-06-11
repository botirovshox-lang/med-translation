"""
db.py — Управление проектами, сегментами, глоссарием, TM (из v5.5)
SQLite база для CAT-рабочего процесса.
"""
import sqlite3
import hashlib
import re
import json
from pathlib import Path
from datetime import datetime
from config_v55 import DB_PATH

def now():
    return datetime.utcnow().isoformat()

def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def norm(t):
    """Нормализация текста для сравнения."""
    return re.sub(r'\s+', ' ', (t or '').strip().lower())

def text_hash(t):
    """SHA256-хеш нормализованного текста."""
    return hashlib.sha256(norm(t).encode()).hexdigest()

def init_db():
    """Создание таблиц (идемпотентно)."""
    c = connect()
    cur = c.cursor()

    # Projects
    cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            source_docx_path TEXT,
            source_language TEXT,
            target_language TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # Segments
    cur.execute("""
        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            segment_order INTEGER,
            block_type TEXT,
            block_index INTEGER,
            source_text TEXT,
            source_hash TEXT,
            target_text TEXT,
            qa_report TEXT,
            qa_score REAL,
            back_translation TEXT,
            back_translation_report TEXT,
            back_translation_score REAL,
            status TEXT DEFAULT 'new',
            tm_match_score REAL,
            tm_suggestion TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # Glossary
    cur.execute("""
        CREATE TABLE IF NOT EXISTS glossary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            source_term TEXT,
            target_term TEXT,
            category TEXT,
            status TEXT DEFAULT 'approved',
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # Translation Memory
    cur.execute("""
        CREATE TABLE IF NOT EXISTS translation_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_hash TEXT UNIQUE,
            source_text TEXT,
            target_text TEXT,
            domain TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    c.commit()
    c.close()

    # Run migration for preflight columns (idempotent)
    add_preflight_columns()

# ── Projects ──────────────────────────────────────────────────────────────────

def create_project(title, path, source_language='Russian', target_language='English'):
    c = connect()
    cur = c.cursor()
    cur.execute(
        'INSERT INTO projects(title,source_docx_path,source_language,target_language,created_at,updated_at) VALUES(?,?,?,?,?,?)',
        (title, path, source_language, target_language, now(), now())
    )
    c.commit()
    pid = cur.lastrowid
    c.close()
    return pid

def get_projects():
    c = connect()
    rows = c.execute('SELECT * FROM projects ORDER BY id DESC').fetchall()
    c.close()
    return [dict(r) for r in rows]

def get_project(pid):
    c = connect()
    r = c.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
    c.close()
    return dict(r) if r else None

def delete_project(pid):
    """Удаление проекта со всеми его сегментами и глоссарием."""
    c = connect()
    c.execute('DELETE FROM segments WHERE project_id=?', (pid,))
    c.execute('DELETE FROM glossary WHERE project_id=?', (pid,))
    c.execute('DELETE FROM projects WHERE id=?', (pid,))
    c.commit()
    c.close()

# ── Segments ──────────────────────────────────────────────────────────────────

def add_segment(pid, order, block_type, block_index, source):
    c = connect()
    c.execute(
        'INSERT INTO segments(project_id,segment_order,block_type,block_index,source_text,source_hash,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
        (pid, order, block_type, block_index, source, text_hash(source), 'new', now(), now())
    )
    c.commit()
    c.close()

def get_segments(pid, status=None):
    c = connect()
    if not status or status == 'all':
        rows = c.execute('SELECT * FROM segments WHERE project_id=? ORDER BY segment_order', (pid,)).fetchall()
    else:
        rows = c.execute('SELECT * FROM segments WHERE project_id=? AND status=? ORDER BY segment_order', (pid, status)).fetchall()
    c.close()
    return [dict(r) for r in rows]

def get_segment(sid):
    c = connect()
    r = c.execute('SELECT * FROM segments WHERE id=?', (sid,)).fetchone()
    c.close()
    return dict(r) if r else None

def update_segment(sid, **fields):
    fields['updated_at'] = now()
    keys = list(fields)
    vals = [fields[k] for k in keys] + [sid]
    c = connect()
    c.execute('UPDATE segments SET ' + ', '.join(k + '=?' for k in keys) + ' WHERE id=?', vals)
    c.commit()
    c.close()

def confirm_segment(sid):
    """Подтверждение сегмента → добавление в TM."""
    seg = get_segment(sid)
    if not seg or not seg.get('target_text'):
        return
    c = connect()
    c.execute("UPDATE segments SET status='confirmed',updated_at=? WHERE id=?", (now(), sid))
    c.execute(
        "INSERT OR REPLACE INTO translation_memory(source_hash,source_text,target_text,domain,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (seg['source_hash'], seg['source_text'], seg['target_text'], 'medical', now(), now())
    )
    c.commit()
    c.close()

# ── Glossary ──────────────────────────────────────────────────────────────────

def add_glossary_term(pid, source, target, cat='', notes='', status='approved'):
    c = connect()
    c.execute(
        'INSERT INTO glossary(project_id,source_term,target_term,category,status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
        (pid, source, target, cat, status, notes, now(), now())
    )
    c.commit()
    c.close()

def get_glossary(pid):
    """Получить глоссарий проекта (только утверждённые термины)."""
    c = connect()
    rows = c.execute('SELECT * FROM glossary WHERE (project_id=? OR project_id IS NULL) AND status=? ORDER BY source_term', (pid, 'approved')).fetchall()
    c.close()
    return [dict(r) for r in rows]

def glossary_prompt(pid):
    """
    Форматирует глоссарий для промпта OpenAI.
    Объединяет:
    1. Project-specific термины (из SQLite)
    2. Approved glossary (из assets/glossary/)
    """
    lines = []

    # 1. Project-specific термины
    terms = get_glossary(pid)
    if terms:
        lines.append("# Project-Specific Terms:")
        for t in terms:
            if t.get('status') == 'approved':
                lines.append(f'- "{t["source_term"]}" → "{t["target_term"]}" ({t.get("category") or ""})')

    # 2. Approved glossary из файла (если существует)
    try:
        from config_v55 import APPROVED_TSV
        if APPROVED_TSV.exists():
            lines.append("\n# Reference Glossary (Approved Medical Terms):")
            with open(APPROVED_TSV, 'r', encoding='utf-8-sig') as f:
                reader = __import__('csv').DictReader(f, delimiter='\t')
                count = 0
                for row in reader:
                    if count >= 500:  # Лимит: 500 верхних терминов (экономия токенов)
                        break
                    ru = row.get('Russian', '').strip()
                    en = row.get('English', '').strip()
                    if ru and en:
                        lines.append(f'- "{ru}" → "{en}"')
                        count += 1
    except Exception as e:
        pass  # Graceful fallback если файл не найден

    return '\n'.join(lines)

# ── Translation Memory ────────────────────────────────────────────────────────

def import_tm_rows(rows):
    """Импорт списка (source, target) пар в TM."""
    c = connect()
    for s, t in rows:
        c.execute(
            'INSERT OR REPLACE INTO translation_memory(source_hash,source_text,target_text,domain,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            (text_hash(s), s, t, 'medical', now(), now())
        )
    c.commit()
    c.close()

def get_all_tm():
    """Получить всё TM."""
    c = connect()
    rows = c.execute('SELECT * FROM translation_memory').fetchall()
    c.close()
    return [dict(r) for r in rows]

def exact_tm_match(source):
    """Точный поиск в TM по хешу."""
    c = connect()
    r = c.execute('SELECT * FROM translation_memory WHERE source_hash=?', (text_hash(source),)).fetchone()
    c.close()
    return dict(r) if r else None

def check_forbidden_translations(target_text):
    """
    Проверяет есть ли в переводе запрещённые термины.
    Возвращает список запрещённых совпадений или пустой список.
    """
    forbidden_list = []
    try:
        from config_v55 import FORBIDDEN_TSV
        if FORBIDDEN_TSV.exists():
            with open(FORBIDDEN_TSV, 'r', encoding='utf-8-sig') as f:
                reader = __import__('csv').DictReader(f, delimiter='\t')
                for row in reader:
                    forbidden_en = row.get('Forbidden_English', '').strip().lower()
                    reason = row.get('Reason', '').strip()
                    if forbidden_en and forbidden_en in target_text.lower():
                        forbidden_list.append({
                            'term': forbidden_en,
                            'reason': reason,
                            'position': target_text.lower().find(forbidden_en)
                        })
    except Exception as e:
        pass  # Graceful fallback
    return forbidden_list

# ── Preflight Analysis (v5.5-final) ──────────────────────────────────────────────

def add_preflight_columns():
    """
    Добавить колонки для preflight анализа (идемпотентно).
    Игнорирует ошибки если колонны уже существуют.
    """
    c = connect()
    cur = c.cursor()

    preflight_columns = [
        ('normalized_source_hash', 'TEXT'),
        ('duplicate_group_id', 'INTEGER'),
        ('duplicate_count', 'INTEGER'),
        ('route', 'TEXT'),
        ('segment_intent', 'TEXT'),
        ('risk_level', 'TEXT'),
        ('risk_reasons', 'TEXT'),  # JSON
        ('detected_features', 'TEXT'),  # JSON
        ('qa_policy', 'TEXT'),
        ('approval_policy', 'TEXT'),
        ('estimated_translation_tokens', 'INTEGER'),
        ('estimated_qa_tokens', 'INTEGER'),
        ('estimated_backcheck_tokens', 'INTEGER'),
        ('estimated_safety_tokens', 'INTEGER'),
        ('estimated_total_tokens', 'INTEGER'),
        ('estimated_total_usd', 'REAL'),
        # NEW: Per-step USD costs (Phase 3B: Cost Estimation)
        ('estimated_translate_usd', 'REAL'),
        ('estimated_qa_usd', 'REAL'),
        ('estimated_backcheck_usd', 'REAL'),
        ('estimated_safety_usd', 'REAL'),
        ('estimated_google_usd', 'REAL'),
        ('preflight_status', 'TEXT DEFAULT "not_analyzed"'),
        # NEW: Zero-token optimization fields
        ('duplicate_representative', 'BOOLEAN DEFAULT 0'),
        ('duplicate_representative_id', 'INTEGER'),
        # NEW: Semantic scoring columns (Phase 3)
        ('semantic_density_score', 'REAL'),
        ('medicality_score', 'REAL'),
        ('entity_complexity_score', 'REAL'),
        ('reversibility_risk_score', 'REAL'),
        ('clinical_criticality_score', 'REAL'),
        ('google_safe_confidence', 'REAL'),
        # NEW: Google batch translation QA
        ('qa_alerts', 'TEXT'),  # JSON array of QA alerts from local_qa_engine
        ('provider', 'TEXT'),  # 'gpt', 'google', 'tm', 'duplicate_propagation'
        # NEW: QA Orchestration (Phase 4)
        ('local_qa_status', 'TEXT'),  # pass/warning/fail
        ('consistency_alerts', 'TEXT'),  # JSON array
        ('numerical_qa_issues', 'TEXT'),  # JSON array
        ('numerical_qa_passed', 'BOOLEAN DEFAULT 1'),
        ('qa_final_status', 'TEXT'),  # qa_passed/qa_warning/qa_failed/human_review_required
        ('qa_depth_used', 'TEXT'),  # local_only/local_plus_light_gpt/full_medical_qa/...
        # NEW: Auto-Approval (Phase 5)
        ('approval_source', 'TEXT'),  # auto_approval_engine|manual|workflow
        ('auto_approved', 'BOOLEAN DEFAULT 0'),
        ('forbidden_alert', 'BOOLEAN DEFAULT 0'),
        ('glossary_issues', 'BOOLEAN DEFAULT 0'),
        ('hallucination_detected', 'BOOLEAN DEFAULT 0'),
    ]

    for col_name, col_type in preflight_columns:
        try:
            cur.execute(f'ALTER TABLE segments ADD COLUMN {col_name} {col_type}')
        except sqlite3.OperationalError:
            # Column already exists, skip
            pass

    c.commit()
    c.close()

def get_segment_preflight(segment_id):
    """Получить preflight метаданные сегмента."""
    c = connect()
    r = c.execute('SELECT * FROM segments WHERE id=?', (segment_id,)).fetchone()
    c.close()

    if not r:
        return None

    seg = dict(r)
    return {
        'segment_id': seg.get('id'),
        'normalized_source_hash': seg.get('normalized_source_hash'),
        'duplicate_group_id': seg.get('duplicate_group_id'),
        'duplicate_count': seg.get('duplicate_count'),
        'route': seg.get('route'),
        'segment_intent': seg.get('segment_intent'),
        'risk_level': seg.get('risk_level'),
        'risk_reasons': seg.get('risk_reasons'),
        'detected_features': seg.get('detected_features'),
        'qa_policy': seg.get('qa_policy'),
        'approval_policy': seg.get('approval_policy'),
        'estimated_translation_tokens': seg.get('estimated_translation_tokens'),
        'estimated_qa_tokens': seg.get('estimated_qa_tokens'),
        'estimated_backcheck_tokens': seg.get('estimated_backcheck_tokens'),
        'estimated_safety_tokens': seg.get('estimated_safety_tokens'),
        'estimated_total_tokens': seg.get('estimated_total_tokens'),
        'estimated_total_usd': seg.get('estimated_total_usd'),
        # NEW: Per-step costs
        'estimated_translate_usd': seg.get('estimated_translate_usd'),
        'estimated_qa_usd': seg.get('estimated_qa_usd'),
        'estimated_backcheck_usd': seg.get('estimated_backcheck_usd'),
        'estimated_safety_usd': seg.get('estimated_safety_usd'),
        'estimated_google_usd': seg.get('estimated_google_usd'),
        'preflight_status': seg.get('preflight_status'),
        # NEW: Semantic scores
        'semantic_density_score': seg.get('semantic_density_score'),
        'medicality_score': seg.get('medicality_score'),
        'entity_complexity_score': seg.get('entity_complexity_score'),
        'reversibility_risk_score': seg.get('reversibility_risk_score'),
        'clinical_criticality_score': seg.get('clinical_criticality_score'),
        'google_safe_confidence': seg.get('google_safe_confidence'),
        # NEW: Google batch
        'qa_alerts': seg.get('qa_alerts'),
        'provider': seg.get('provider'),
    }

def update_segment_preflight(segment_id, preflight_data):
    """
    Обновить preflight метаданные сегмента.
    preflight_data — dict с preflight полями.
    """
    c = connect()

    # Фильтруем только префlight поля (включая семантические оценки)
    preflight_fields = {
        'normalized_source_hash', 'duplicate_group_id', 'duplicate_count', 'route',
        'segment_intent', 'risk_level', 'risk_reasons', 'detected_features',
        'qa_policy', 'approval_policy', 'estimated_translation_tokens',
        'estimated_qa_tokens', 'estimated_backcheck_tokens', 'estimated_safety_tokens',
        'estimated_total_tokens', 'estimated_total_usd', 'preflight_status',
        # NEW: Per-step costs
        'estimated_translate_usd', 'estimated_qa_usd', 'estimated_backcheck_usd',
        'estimated_safety_usd', 'estimated_google_usd',
        # NEW: Semantic scoring fields
        'semantic_density_score', 'medicality_score', 'entity_complexity_score',
        'reversibility_risk_score', 'clinical_criticality_score', 'google_safe_confidence',
        # NEW: Zero-token optimization fields
        'duplicate_representative', 'duplicate_representative_id',
        # NEW: Google batch translation
        'qa_alerts', 'provider',
        # NEW: QA Orchestration
        'local_qa_status', 'consistency_alerts', 'numerical_qa_issues', 'numerical_qa_passed',
        'qa_final_status', 'qa_depth_used',
        # NEW: Auto-Approval
        'approval_source', 'auto_approved', 'forbidden_alert', 'glossary_issues', 'hallucination_detected'
    }

    fields = {k: v for k, v in preflight_data.items() if k in preflight_fields}
    fields['updated_at'] = now()

    keys = list(fields.keys())
    vals = [fields[k] for k in keys] + [segment_id]

    c.execute(
        'UPDATE segments SET ' + ', '.join(k + '=?' for k in keys) + ' WHERE id=?',
        vals
    )
    c.commit()
    c.close()

def get_all_segments_preflight(project_id):
    """Получить все сегменты с preflight метаданными для проекта."""
    c = connect()
    rows = c.execute(
        'SELECT * FROM segments WHERE project_id=? ORDER BY segment_order',
        (project_id,)
    ).fetchall()
    c.close()

    return [dict(r) for r in rows]

def get_segments_by_route(project_id, route):
    """Получить все сегменты с конкретным маршрутом."""
    c = connect()
    rows = c.execute(
        'SELECT * FROM segments WHERE project_id=? AND route=? ORDER BY segment_order',
        (project_id, route)
    ).fetchall()
    c.close()

    return [dict(r) for r in rows]

def get_segments_by_risk_level(project_id, risk_level):
    """Получить все сегменты с конкретным уровнем риска."""
    c = connect()
    rows = c.execute(
        'SELECT * FROM segments WHERE project_id=? AND risk_level=? ORDER BY segment_order',
        (project_id, risk_level)
    ).fetchall()
    c.close()

    return [dict(r) for r in rows]

def get_duplicate_groups(project_id):
    """
    Получить информацию о группах дубликатов в проекте.

    Returns:
        list[dict] with:
            - group_id: int
            - count: int (кол-во сегментов в группе)
            - representative_id: int (первый сегмент)
            - status: str (representative status)
            - tokens: int (total)
            - savings_usd: float
    """
    c = connect()
    rows = c.execute(
        """
        SELECT
            duplicate_group_id as group_id,
            COUNT(*) as count,
            MIN(id) as representative_id,
            MIN(estimated_total_tokens) as tokens
        FROM segments
        WHERE project_id=? AND duplicate_group_id IS NOT NULL
        GROUP BY duplicate_group_id
        ORDER BY count DESC
        """,
        (project_id,)
    ).fetchall()
    c.close()

    result = []
    for row in rows:
        r = dict(row)
        # Estimate savings: (count-1) * translate_cost
        # Each duplicate after first saves ~$0.005
        r['savings_usd'] = round((r['count'] - 1) * 0.005, 2)
        result.append(r)

    return result

def get_duplicate_group_members(group_id):
    """Получить все сегменты в группе дубликатов."""
    c = connect()
    rows = c.execute(
        """
        SELECT id, segment_order, source_text, target_text, status, risk_level,
               duplicate_representative, duplicate_representative_id
        FROM segments
        WHERE duplicate_group_id = ?
        ORDER BY segment_order
        """,
        (group_id,)
    ).fetchall()
    c.close()

    return [dict(r) for r in rows]
