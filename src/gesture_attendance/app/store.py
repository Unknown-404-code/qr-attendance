"""Persistence on SQLite (laptop) or Postgres (hosted). Only face EMBEDDINGS are stored - never the selfies.

Everything a doctor sees hangs off a course: students(course_id, student_id), sessions(course_id).
Challenges, attempts, attendance and flags key on session_id and so inherit the course.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .db import connect, ddl

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id {id}, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL,
    password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at {real});
CREATE TABLE IF NOT EXISTS courses(
    id {id}, owner_id INTEGER NOT NULL, name TEXT NOT NULL, created_at {real});
CREATE TABLE IF NOT EXISTS students(
    course_id INTEGER NOT NULL, student_id TEXT NOT NULL, name TEXT NOT NULL,
    embedding {blob}, enrolled_at {real}, enroll_status TEXT NOT NULL DEFAULT 'none', removed_at {real},
    PRIMARY KEY(course_id, student_id));
CREATE TABLE IF NOT EXISTS sessions(
    id {id}, course_id INTEGER NOT NULL, title TEXT, started_at {real}, ended_at {real},
    enroll_open INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS challenges(
    id TEXT PRIMARY KEY, session_id INTEGER, student_id TEXT, gesture TEXT, created_at {real},
    used INTEGER NOT NULL DEFAULT 0, device_id TEXT);
CREATE TABLE IF NOT EXISTS attempts(
    id {id}, session_id INTEGER, student_id TEXT, ts {real}, challenge TEXT,
    pred TEXT, conf {real}, face_sim {real}, accepted INTEGER, reason TEXT, device_id TEXT, source TEXT,
    latency_ms {real});
CREATE TABLE IF NOT EXISTS attendance(
    session_id INTEGER NOT NULL, student_id TEXT NOT NULL, ts {real}, device_id TEXT, face_sim {real}, method TEXT,
    PRIMARY KEY(session_id, student_id));
CREATE TABLE IF NOT EXISTS flags(
    id {id}, session_id INTEGER, student_id TEXT, ts {real}, kind TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_sessions_course ON sessions(course_id);
CREATE INDEX IF NOT EXISTS ix_attempts_session ON attempts(session_id, student_id);
CREATE INDEX IF NOT EXISTS ix_flags_session ON flags(session_id)
"""

# tables keyed on session_id whose student_id follows a student's ID change
SESSION_TABLES = ("challenges", "attempts", "attendance", "flags")


def _sid(x) -> str:
    return str(x).strip()


class Store:
    def __init__(self, target: str | Path = ":memory:", schema: str | None = None):
        self.db = connect(target, schema=schema)
        self.db.script(ddl(SCHEMA, self.db.dialect))

    # ------------------------------------------------------------------ users
    def create_user(self, email: str, name: str, role: str, password_hash: str) -> int:
        email = email.strip().lower()
        with self.db.lock:
            if self.user_by_email(email):
                raise ValueError("An account with this email already exists.")
            return self.db.insert("INSERT INTO users(email, name, role, password_hash, active, created_at) "
                                  "VALUES(?, ?, ?, ?, 1, ?) RETURNING id",
                                  (email, name.strip(), role, password_hash, time.time()))

    def user(self, uid: int) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE id=?", (uid,))

    def user_by_email(self, email: str) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE email=?", (email.strip().lower(),))

    def users(self) -> list[dict]:
        return self.db.q("SELECT id, email, name, role, active, created_at FROM users ORDER BY lower(name)")

    def set_password(self, uid: int, password_hash: str):
        self.db.x("UPDATE users SET password_hash=? WHERE id=?", (password_hash, uid))

    def set_active(self, uid: int, active: bool):
        self.db.x("UPDATE users SET active=? WHERE id=?", (int(active), uid))

    def count_admins(self) -> int:
        return int(self.db.one("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1")["n"])

    # ------------------------------------------------------------------ courses
    def create_course(self, owner_id: int, name: str) -> int:
        return self.db.insert("INSERT INTO courses(owner_id, name, created_at) VALUES(?, ?, ?) RETURNING id",
                              (owner_id, name.strip(), time.time()))

    def course(self, cid: int) -> dict | None:
        return self.db.one("SELECT * FROM courses WHERE id=?", (cid,))

    def courses(self, owner_id: int | None) -> list[dict]:
        if owner_id is None:
            return self.db.q("SELECT * FROM courses ORDER BY id")
        return self.db.q("SELECT * FROM courses WHERE owner_id=? ORDER BY id", (owner_id,))

    def delete_course(self, cid: int):
        with self.db.lock:
            for t in SESSION_TABLES:
                self.db.x(f"DELETE FROM {t} WHERE session_id IN (SELECT id FROM sessions WHERE course_id=?)", (cid,))
            self.db.x("DELETE FROM sessions WHERE course_id=?", (cid,))
            self.db.x("DELETE FROM students WHERE course_id=?", (cid,))
            self.db.x("DELETE FROM courses WHERE id=?", (cid,))

    # ------------------------------------------------------------------ students
    def upsert_students(self, cid: int, rows: list[tuple[str, str]]) -> int:
        """Adds new students, updates names, and brings back removed students who are in the file."""
        with self.db.lock:
            for sid, name in rows:
                self.db.x("INSERT INTO students(course_id, student_id, name) VALUES(?, ?, ?) "
                          "ON CONFLICT(course_id, student_id) DO UPDATE SET name=excluded.name, removed_at=NULL",
                          (cid, _sid(sid), str(name).strip()))
        return len(rows)

    def students(self, cid: int, include_removed: bool = False) -> list[dict]:
        where = "" if include_removed else " AND removed_at IS NULL"
        return self.db.q("SELECT student_id, name, enroll_status, enrolled_at, removed_at FROM students "
                         f"WHERE course_id=?{where} ORDER BY lower(name), student_id", (cid,))

    def student(self, cid: int, sid: str) -> dict | None:
        return self.db.one("SELECT * FROM students WHERE course_id=? AND student_id=? AND removed_at IS NULL",
                           (cid, _sid(sid)))

    def _any_student(self, cid: int, sid: str) -> dict | None:
        return self.db.one("SELECT * FROM students WHERE course_id=? AND student_id=?", (cid, _sid(sid)))

    def add_student(self, cid: int, sid: str, name: str):
        sid = _sid(sid)
        if not sid:
            raise ValueError("Enter a student ID.")
        with self.db.lock:
            existing = self._any_student(cid, sid)
            if existing and existing["removed_at"] is None:
                raise ValueError(f"ID {sid} is already in this course.")
            if existing:  # removed earlier: bring them back with their history
                self.db.x("UPDATE students SET name=?, removed_at=NULL WHERE course_id=? AND student_id=?",
                          (name.strip() or existing["name"], cid, sid))
                return
            self.db.x("INSERT INTO students(course_id, student_id, name) VALUES(?, ?, ?)", (cid, sid, name.strip()))

    def update_student(self, cid: int, old_sid: str, new_sid: str, name: str):
        old, new = _sid(old_sid), _sid(new_sid)
        if not new:
            raise ValueError("Enter a student ID.")
        with self.db.lock:
            if self._any_student(cid, old) is None:
                raise ValueError(f"ID {old} is not in this course.")
            if new != old:
                if self._any_student(cid, new):
                    raise ValueError(f"ID {new} is already in this course.")
                for t in SESSION_TABLES:
                    self.db.x(f"UPDATE {t} SET student_id=? WHERE student_id=? AND session_id IN "
                              "(SELECT id FROM sessions WHERE course_id=?)", (new, old, cid))
            self.db.x("UPDATE students SET student_id=?, name=? WHERE course_id=? AND student_id=?",
                      (new, name.strip(), cid, old))

    def remove_student(self, cid: int, sid: str):
        self.db.x("UPDATE students SET removed_at=? WHERE course_id=? AND student_id=?", (time.time(), cid, _sid(sid)))

    def report_students(self, cid: int, session_ids: list[int]) -> list[dict]:
        """Current students, plus removed ones who attended any of `session_ids`."""
        rows = self.students(cid, include_removed=True)
        attended: set[str] = set()
        for s in session_ids:
            attended |= set(self.attendance(s))
        out = []
        for r in rows:
            removed = r["removed_at"] is not None
            if removed and r["student_id"] not in attended:
                continue
            out.append({**r, "removed": removed})
        return out

    def embedding(self, cid: int, sid: str) -> np.ndarray | None:
        r = self.db.one("SELECT embedding FROM students WHERE course_id=? AND student_id=?", (cid, _sid(sid)))
        return None if not r or r["embedding"] is None else np.frombuffer(r["embedding"], dtype=np.float32).copy()

    def all_embeddings(self, cid: int) -> dict[str, np.ndarray]:
        return {r["student_id"]: np.frombuffer(r["embedding"], dtype=np.float32)
                for r in self.db.q("SELECT student_id, embedding FROM students "
                                   "WHERE course_id=? AND embedding IS NOT NULL AND removed_at IS NULL", (cid,))}

    def set_embedding(self, cid: int, sid: str, emb: np.ndarray | None, status: str):
        blob = None if emb is None else np.asarray(emb, np.float32).tobytes()
        self.db.x("UPDATE students SET embedding=?, enrolled_at=?, enroll_status=? WHERE course_id=? AND student_id=?",
                  (blob, time.time() if emb is not None else None, status, cid, _sid(sid)))

    def set_enroll_status(self, cid: int, sid: str, status: str):
        self.db.x("UPDATE students SET enroll_status=? WHERE course_id=? AND student_id=?", (status, cid, _sid(sid)))

    # ------------------------------------------------------------------ sessions
    def start_session(self, cid: int, title: str, enroll_open: bool = False) -> int:
        with self.db.lock:
            self.db.x("UPDATE sessions SET ended_at=? WHERE course_id=? AND ended_at IS NULL", (time.time(), cid))
            return self.db.insert("INSERT INTO sessions(course_id, title, started_at, enroll_open) "
                                  "VALUES(?, ?, ?, ?) RETURNING id", (cid, title, time.time(), int(enroll_open)))

    def end_session(self, session_id: int):
        self.db.x("UPDATE sessions SET ended_at=? WHERE id=? AND ended_at IS NULL", (time.time(), session_id))

    def active_session(self, cid: int) -> dict | None:
        return self.db.one("SELECT * FROM sessions WHERE course_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
                           (cid,))

    def session(self, session_id: int) -> dict | None:
        return self.db.one("SELECT * FROM sessions WHERE id=?", (session_id,))

    def sessions(self, cid: int) -> list[dict]:
        return self.db.q("SELECT * FROM sessions WHERE course_id=? ORDER BY id DESC", (cid,))

    def set_enroll_open(self, session_id: int, open_: bool):
        self.db.x("UPDATE sessions SET enroll_open=? WHERE id=?", (int(open_), session_id))

    # ------------------------------------------------------------------ challenges / attempts
    def add_challenge(self, cid: str, session_id: int, sid: str, gesture: str, device_id: str):
        self.db.x("INSERT INTO challenges(id, session_id, student_id, gesture, created_at, device_id) "
                  "VALUES(?, ?, ?, ?, ?, ?)", (cid, session_id, sid, gesture, time.time(), device_id))

    def take_challenge(self, cid: str) -> dict | None:
        """Atomically mark a challenge used (one selfie per challenge) and return it."""
        return self.db.one("UPDATE challenges SET used=1 WHERE id=? AND used=0 RETURNING *", (cid,))

    def add_attempt(self, **kw) -> int:
        cols = ",".join(kw)
        return self.db.insert(f"INSERT INTO attempts({cols}) VALUES({','.join('?' * len(kw))}) RETURNING id",
                              tuple(kw.values()))

    def n_attempts(self, session_id: int, sid: str) -> int:
        return int(self.db.one("SELECT COUNT(*) AS n FROM attempts WHERE session_id=? AND student_id=?",
                               (session_id, sid))["n"])

    def attempts(self, session_id: int) -> list[dict]:
        return self.db.q("SELECT * FROM attempts WHERE session_id=? ORDER BY ts", (session_id,))

    # ------------------------------------------------------------------ attendance
    def mark_present(self, session_id: int, sid: str, device_id: str = "", face_sim: float | None = None,
                     method: str = "gesture+face"):
        self.db.x("INSERT INTO attendance(session_id, student_id, ts, device_id, face_sim, method) "
                  "VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(session_id, student_id) DO UPDATE SET "
                  "ts=excluded.ts, device_id=excluded.device_id, face_sim=excluded.face_sim, method=excluded.method",
                  (session_id, sid, time.time(), device_id, face_sim, method))

    def unmark(self, session_id: int, sid: str):
        self.db.x("DELETE FROM attendance WHERE session_id=? AND student_id=?", (session_id, sid))

    def is_present(self, session_id: int, sid: str) -> bool:
        return self.db.one("SELECT 1 AS x FROM attendance WHERE session_id=? AND student_id=?", (session_id, sid)) is not None

    def attendance(self, session_id: int) -> dict[str, dict]:
        return {r["student_id"]: r for r in self.db.q("SELECT * FROM attendance WHERE session_id=?", (session_id,))}

    def students_on_device(self, session_id: int, device_id: str) -> set[str]:
        rows = self.db.q("SELECT DISTINCT student_id FROM challenges WHERE session_id=? AND device_id=?",
                         (session_id, device_id))
        return {r["student_id"] for r in rows}

    # ------------------------------------------------------------------ flags
    def flag(self, session_id: int, sid: str, kind: str, detail: str = ""):
        with self.db.lock:
            exists = self.db.one("SELECT 1 AS x FROM flags WHERE session_id=? AND student_id=? AND kind=? AND detail=?",
                                 (session_id, sid, kind, detail))
            if not exists:
                self.db.x("INSERT INTO flags(session_id, student_id, ts, kind, detail) VALUES(?, ?, ?, ?, ?)",
                          (session_id, sid, time.time(), kind, detail))

    def flags(self, session_id: int) -> list[dict]:
        return self.db.q("SELECT * FROM flags WHERE session_id=? ORDER BY ts, id", (session_id,))
