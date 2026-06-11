"""
db.py — Управление проектами, сегментами, глоссарием, TM (из v5.5)
SQLite база для CAT-рабочего процесса.
"""
import sqlite3
import hashlib
import re
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
