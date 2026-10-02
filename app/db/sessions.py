"""Opaque browser sessions and owner-scoped, successful conversation turns."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from uuid import uuid4


class SessionError(RuntimeError):
    pass


class SessionStore:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS browsers (token_hash TEXT PRIMARY KEY, expires REAL);
            CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                busy_request TEXT, busy_until REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL,
                question TEXT NOT NULL, answer TEXT NOT NULL, sources TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation_id,id);
            ''')

    def connect(self):
        return closing_connection(self.path)

    def browser(self, token, ttl):
        now = time.time()
        with self.connect() as db:
            db.execute('DELETE FROM browsers WHERE expires < ?', (now,))
            if token and len(token) <= 128:
                hashed = hashlib.sha256(token.encode()).hexdigest()
                if db.execute('SELECT 1 FROM browsers WHERE token_hash=? AND expires>?', (hashed, now)).fetchone():
                    return 'browser:' + hashed, None
            token = secrets.token_urlsafe(32)
            hashed = hashlib.sha256(token.encode()).hexdigest()
            db.execute('INSERT INTO browsers VALUES (?,?)', (hashed, now + ttl))
            return 'browser:' + hashed, token

    def create(self, owner):
        cid = str(uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO conversations(id,owner) VALUES (?,?)', (cid, owner))
        return cid

    def check(self, db, cid, owner):
        if not db.execute('SELECT 1 FROM conversations WHERE id=? AND owner=?', (cid, owner)).fetchone():
            raise SessionError('会话不存在或无权访问')

    def history(self, cid, owner, limit=6):
        with self.connect() as db:
            self.check(db, cid, owner)
            rows = db.execute('SELECT question,answer,sources FROM turns WHERE conversation_id=? ORDER BY id DESC LIMIT ?',
                              (cid, limit)).fetchall()
            return [dict(question=q, answer=a, sources=json.loads(s)) for q, a, s in reversed(rows)]

    def acquire(self, cid, owner, request_id, timeout, deadline=None, cancelled=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.check(db, cid, owner)
            result = db.execute('UPDATE conversations SET busy_request=?,busy_until=? WHERE id=? AND busy_until<?',
                                (request_id, time.time()+timeout+10, cid, time.time()))
            if not result.rowcount:
                raise SessionError('此会话正在回答，请稍后重试')
            ensure_active(deadline, cancelled)

    def save(self, cid, owner, request_id, question, answer, sources, deadline=None, cancelled=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.check(db, cid, owner)
            if not db.execute('SELECT 1 FROM conversations WHERE id=? AND busy_request=? AND busy_until>?',
                              (cid, request_id, time.time())).fetchone():
                raise SessionError('会话请求已过期')
            db.execute('INSERT INTO turns(conversation_id,question,answer,sources) VALUES (?,?,?,?)',
                       (cid, question, answer, json.dumps(sources, ensure_ascii=False)))
            db.execute('UPDATE conversations SET busy_request=NULL,busy_until=0 WHERE id=?', (cid,))
            # to_thread survives task cancellation: check immediately before transaction commit.
            ensure_active(deadline, cancelled)

    def release(self, cid, request_id):
        with self.connect() as db:
            db.execute('UPDATE conversations SET busy_request=NULL,busy_until=0 WHERE id=? AND busy_request=?', (cid, request_id))



@contextmanager
def closing_connection(path):
    with closing(sqlite3.connect(path, timeout=5)) as db:
        with db:
            yield db


def ensure_active(deadline, cancelled):
    if (cancelled is not None and cancelled.is_set()) or (deadline is not None and time.monotonic() >= deadline):
        raise TimeoutError('Cancelled or expired request; roll back transaction')
