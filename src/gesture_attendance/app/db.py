"""One small database interface over SQLite (laptop, tests) and Postgres (Supabase, hosted).

SQL is written once with `?` placeholders; the Postgres side rewrites them to `%s`.
Table definitions use `{id}`, `{blob}` and `{real}`, which `ddl()` fills in per dialect.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

DDL = {
    "sqlite": {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "blob": "BLOB", "real": "REAL"},
    "postgres": {"id": "BIGSERIAL PRIMARY KEY", "blob": "BYTEA", "real": "DOUBLE PRECISION"},
}


def ddl(sql: str, dialect: str) -> str:
    t = DDL[dialect]
    return sql.replace("{id}", t["id"]).replace("{blob}", t["blob"]).replace("{real}", t["real"])


def is_postgres_url(target) -> bool:
    return str(target).startswith(("postgres://", "postgresql://"))


class Database:
    dialect = "sqlite"

    def __init__(self):
        self.lock = threading.RLock()

    def q(self, sql: str, args=()) -> list[dict]:
        raise NotImplementedError

    def one(self, sql: str, args=()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args=()) -> None:
        self.q(sql, args)

    def insert(self, sql: str, args=()) -> int:
        """`sql` must end with RETURNING id."""
        return int(self.q(sql, args)[0]["id"])

    def script(self, sql: str) -> None:
        raise NotImplementedError


class SQLiteDatabase(Database):
    dialect = "sqlite"

    def __init__(self, path):
        super().__init__()
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = lambda cur, row: {d[0]: v for d, v in zip(cur.description, row)}
        self.conn.execute("PRAGMA foreign_keys=ON")

    def q(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, tuple(args))
            rows = cur.fetchall() if cur.description else []
            self.conn.commit()
            return rows

    def script(self, sql):
        with self.lock:
            self.conn.executescript(sql)


class PostgresDatabase(Database):
    dialect = "postgres"

    def __init__(self, url: str, schema: str | None = None):
        super().__init__()
        self.url, self.schema = url, schema
        self.conn = self._connect()

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        # prepare_threshold=None: Supabase's transaction pooler cannot keep prepared statements
        conn = psycopg.connect(self.url, autocommit=True, prepare_threshold=None, row_factory=dict_row)
        if self.schema:
            conn.execute(f'SET search_path TO "{self.schema}"')
        return conn

    @staticmethod
    def _fix(row: dict) -> dict:
        return {k: bytes(v) if isinstance(v, memoryview) else v for k, v in row.items()}

    def _run(self, fn):
        import psycopg
        with self.lock:
            try:
                return fn()
            except psycopg.OperationalError:
                # the pooler drops idle connections; reconnect once and retry
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = self._connect()
                return fn()

    def q(self, sql, args=()):
        def run():
            if self.conn.closed:
                self.conn = self._connect()
            cur = self.conn.execute(sql.replace("?", "%s"), tuple(args))
            return [self._fix(r) for r in cur.fetchall()] if cur.description else []
        return self._run(run)

    def script(self, sql):
        def run():
            if self.conn.closed:
                self.conn = self._connect()
            for stmt in (s.strip() for s in sql.split(";")):
                if stmt:
                    self.conn.execute(stmt)
        self._run(run)


def connect(target: str | Path, schema: str | None = None) -> Database:
    if is_postgres_url(target):
        return PostgresDatabase(str(target), schema)
    return SQLiteDatabase(target)
