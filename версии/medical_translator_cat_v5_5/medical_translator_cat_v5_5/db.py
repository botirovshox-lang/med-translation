import sqlite3, hashlib, re
from pathlib import Path
from datetime import datetime
DB_PATH=Path('data/cat_translator.db')
def now(): return datetime.utcnow().isoformat()
def connect():
    DB_PATH.parent.mkdir(exist_ok=True); c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c
def norm(t): return re.sub(r'\s+',' ',(t or '').strip().lower())
def text_hash(t): return hashlib.sha256(norm(t).encode()).hexdigest()
def init_db():
    c=connect(); cur=c.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,source_docx_path TEXT,source_language TEXT,target_language TEXT,created_at TEXT,updated_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS segments(id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER,segment_order INTEGER,block_type TEXT,block_index INTEGER,source_text TEXT,source_hash TEXT,target_text TEXT,qa_report TEXT,qa_score REAL,back_translation TEXT,back_translation_report TEXT,back_translation_score REAL,status TEXT DEFAULT 'new',tm_match_score REAL,tm_suggestion TEXT,created_at TEXT,updated_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS glossary(id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER,source_term TEXT,target_term TEXT,category TEXT,status TEXT DEFAULT 'approved',notes TEXT,created_at TEXT,updated_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS translation_memory(id INTEGER PRIMARY KEY AUTOINCREMENT,source_hash TEXT UNIQUE,source_text TEXT,target_text TEXT,domain TEXT,created_at TEXT,updated_at TEXT)")
    c.commit(); c.close()
def create_project(title,path,source_language='Russian',target_language='English'):
    c=connect(); cur=c.cursor(); cur.execute('INSERT INTO projects(title,source_docx_path,source_language,target_language,created_at,updated_at) VALUES(?,?,?,?,?,?)',(title,path,source_language,target_language,now(),now())); c.commit(); x=cur.lastrowid; c.close(); return x
def get_projects():
    c=connect(); rows=c.execute('SELECT * FROM projects ORDER BY id DESC').fetchall(); c.close(); return [dict(r) for r in rows]
def get_project(pid):
    c=connect(); r=c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone(); c.close(); return dict(r) if r else None
def add_segment(pid,order,bt,bi,source):
    c=connect(); c.execute('INSERT INTO segments(project_id,segment_order,block_type,block_index,source_text,source_hash,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?, ?, ?)',(pid,order,bt,bi,source,text_hash(source),'new',now(),now())); c.commit(); c.close()
def get_segments(pid,status=None):
    c=connect(); rows=c.execute('SELECT * FROM segments WHERE project_id=? ORDER BY segment_order',(pid,)).fetchall() if not status or status=='all' else c.execute('SELECT * FROM segments WHERE project_id=? AND status=? ORDER BY segment_order',(pid,status)).fetchall(); c.close(); return [dict(r) for r in rows]
def get_segment(sid):
    c=connect(); r=c.execute('SELECT * FROM segments WHERE id=?',(sid,)).fetchone(); c.close(); return dict(r) if r else None
def update_segment(sid,**fields):
    fields['updated_at']=now(); keys=list(fields); vals=[fields[k] for k in keys]+[sid]; c=connect(); c.execute('UPDATE segments SET '+', '.join(k+'=?' for k in keys)+' WHERE id=?',vals); c.commit(); c.close()
def confirm_segment(sid):
    seg=get_segment(sid)
    if not seg or not seg.get('target_text'): return
    c=connect(); c.execute("UPDATE segments SET status='confirmed',updated_at=? WHERE id=?",(now(),sid)); c.execute("INSERT OR REPLACE INTO translation_memory(source_hash,source_text,target_text,domain,created_at,updated_at) VALUES(?,?,?,?,?,?)",(seg['source_hash'],seg['source_text'],seg['target_text'],'medical',now(),now())); c.commit(); c.close()
def add_glossary_term(pid,source,target,cat='',notes='',status='approved'):
    c=connect(); c.execute('INSERT INTO glossary(project_id,source_term,target_term,category,status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(pid,source,target,cat,status,notes,now(),now())); c.commit(); c.close()
def get_glossary(pid):
    c=connect(); rows=c.execute('SELECT * FROM glossary WHERE project_id=? OR project_id IS NULL ORDER BY source_term',(pid,)).fetchall(); c.close(); return [dict(r) for r in rows]
def glossary_prompt(pid): return '\n'.join(f'- "{t["source_term"]}" → "{t["target_term"]}" ({t.get("category") or ""})' for t in get_glossary(pid) if t.get('status')=='approved')
def import_tm_rows(rows):
    c=connect()
    for s,t in rows: c.execute('INSERT OR REPLACE INTO translation_memory(source_hash,source_text,target_text,domain,created_at,updated_at) VALUES(?,?,?,?,?,?)',(text_hash(s),s,t,'medical',now(),now()))
    c.commit(); c.close()
def get_all_tm():
    c=connect(); rows=c.execute('SELECT * FROM translation_memory').fetchall(); c.close(); return [dict(r) for r in rows]
def exact_tm_match(source):
    c=connect(); r=c.execute('SELECT * FROM translation_memory WHERE source_hash=?',(text_hash(source),)).fetchone(); c.close(); return dict(r) if r else None
