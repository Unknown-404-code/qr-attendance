import pytest

from gesture_attendance.app.auth import LoginLimiter, ensure_admin, hash_password, new_password, verify_password
from gesture_attendance.app.store import Store


def test_hash_roundtrip():
    h = hash_password("correct horse")
    assert h.startswith("scrypt$16384$8$1$")
    assert verify_password("correct horse", h)
    assert not verify_password("wrong horse", h)
    assert not verify_password("correct horse", "garbage")
    assert hash_password("correct horse") != h  # random salt


def test_short_password_rejected():
    with pytest.raises(ValueError):
        hash_password("1234567")


def test_new_password():
    p = new_password()
    assert len(p) == 12 and p != new_password()


def test_limiter():
    now = [1000.0]
    lim = LoginLimiter(clock=lambda: now[0])
    for _ in range(9):
        lim.fail("A@x.com")
    assert not lim.blocked("a@x.com")
    lim.fail("a@x.com")
    assert lim.blocked("a@x.com") and not lim.blocked("b@x.com")
    now[0] += 901
    assert not lim.blocked("a@x.com")
    for _ in range(10):
        lim.fail("a@x.com")
    lim.reset("a@x.com")
    assert not lim.blocked("a@x.com")


def test_ensure_admin_env():
    st = Store()
    assert ensure_admin(st, "Boss@x.com", "first-pass") is None
    u = st.user_by_email("boss@x.com")
    assert u["role"] == "admin" and verify_password("first-pass", u["password_hash"])
    assert ensure_admin(st, "boss@x.com", "second-pass") is None
    assert verify_password("first-pass", st.user_by_email("boss@x.com")["password_hash"])
    ensure_admin(st, "boss@x.com", "second-pass", reset=True)
    assert verify_password("second-pass", st.user_by_email("boss@x.com")["password_hash"])
    assert len(st.users()) == 1


def test_ensure_admin_generated():
    st = Store()
    pw = ensure_admin(st, None, None)
    assert len(pw) == 12
    assert verify_password(pw, st.user_by_email("admin@localhost")["password_hash"])
    assert ensure_admin(st, None, None) is None
