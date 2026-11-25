import pytest

from gesture_attendance.app.db import connect, ddl, is_postgres_url


def make(db_url):
    url, schema = db_url
    db = connect(url, schema=schema)
    db.script(ddl("CREATE TABLE t(id {id}, v TEXT, b {blob}, r {real})", db.dialect))
    return db


def test_roundtrip(db_url):
    db = make(db_url)
    assert db.insert("INSERT INTO t(v, b, r) VALUES(?, ?, ?) RETURNING id", ("a", b"\x01", 0.5)) == 1
    assert db.one("SELECT id, v, b, r FROM t WHERE id=?", (1,)) == {"id": 1, "v": "a", "b": b"\x01", "r": 0.5}
    assert db.one("SELECT * FROM t WHERE id=?", (99,)) is None


def test_update_returning_is_atomic(db_url):
    db = make(db_url)
    db.insert("INSERT INTO t(v) VALUES(?) RETURNING id", ("a",))
    assert len(db.q("UPDATE t SET v='used' WHERE id=? AND v='a' RETURNING *", (1,))) == 1
    assert db.q("UPDATE t SET v='used' WHERE id=? AND v='a' RETURNING *", (1,)) == []


def test_x_writes(db_url):
    db = make(db_url)
    db.insert("INSERT INTO t(v) VALUES(?) RETURNING id", ("a",))
    db.x("UPDATE t SET v=? WHERE id=?", ("b", 1))
    assert db.one("SELECT v FROM t")["v"] == "b"


def test_reconnects_after_drop(db_url):
    if not is_postgres_url(db_url[0]):
        pytest.skip("postgres only")
    db = make(db_url)
    db.conn.close()
    assert db.q("SELECT 1 AS n") == [{"n": 1}]
