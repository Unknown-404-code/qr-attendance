import numpy as np
import pytest

from gesture_attendance.app.store import Store


@pytest.fixture
def st(db_url):
    url, schema = db_url
    return Store(url, schema=schema)


def course(st, name="CV"):
    uid = st.create_user(f"{name.lower()}@x.com", name, "doctor", "h")
    return st.create_course(uid, name)


def test_courses_are_separate(st):
    a, b = course(st, "A"), course(st, "B")
    st.upsert_students(a, [("1", "Ali")])
    st.upsert_students(b, [("1", "Ali B")])
    sa, sb = st.start_session(a, "L1"), st.start_session(b, "L1")
    st.mark_present(sa, "1")
    assert "1" in st.attendance(sa) and st.attendance(sb) == {}
    assert st.student(b, "1")["name"] == "Ali B"
    assert [c["name"] for c in st.courses(None)] == ["A", "B"]
    assert [c["id"] for c in st.courses(st.course(a)["owner_id"])] == [a]


def test_starting_session_ends_only_same_course(st):
    a, b = course(st, "A"), course(st, "B")
    s1, sb = st.start_session(a, "L1"), st.start_session(b, "L1")
    s2 = st.start_session(a, "L2")
    assert st.session(s1)["ended_at"] is not None
    assert st.active_session(a)["id"] == s2 and st.active_session(b)["id"] == sb
    assert st.session(s2)["course_id"] == a
    assert [s["id"] for s in st.sessions(a)] == [s2, s1]


def test_add_edit_remove_student(st):
    c = course(st)
    st.add_student(c, " 00123 ", "Ali")
    assert st.student(c, "00123")["name"] == "Ali"
    with pytest.raises(ValueError):
        st.add_student(c, "00123", "Other")
    sess = st.start_session(c, "L1")
    st.mark_present(sess, "00123")
    st.flag(sess, "00123", "shared_device", "x")
    st.set_embedding(c, "00123", np.ones(4, np.float32), "confirmed")
    st.update_student(c, "00123", "555", "Ali B")
    assert st.student(c, "00123") is None
    assert st.student(c, "555")["name"] == "Ali B"
    assert "555" in st.attendance(sess)
    assert st.flags(sess)[0]["student_id"] == "555"
    assert st.embedding(c, "555").tolist() == [1, 1, 1, 1]
    st.remove_student(c, "555")
    assert st.students(c) == [] and st.student(c, "555") is None
    rs = st.report_students(c, [sess])
    assert [(s["student_id"], s["removed"]) for s in rs] == [("555", True)]
    assert st.report_students(c, []) == []


def test_reupload_restores_removed(st):
    c = course(st)
    st.upsert_students(c, [("1", "Ali"), ("2", "Sara")])
    sess = st.start_session(c, "L1")
    st.mark_present(sess, "2")
    st.remove_student(c, "2")
    assert [s["student_id"] for s in st.students(c)] == ["1"]
    st.upsert_students(c, [("2", "Sara")])
    assert [s["student_id"] for s in st.students(c)] == ["1", "2"]
    assert "2" in st.attendance(sess)


def test_update_to_taken_id_fails(st):
    c = course(st)
    st.upsert_students(c, [("1", "Ali"), ("2", "Sara")])
    with pytest.raises(ValueError):
        st.update_student(c, "1", "2", "Ali")
    assert st.student(c, "1")["name"] == "Ali"
    with pytest.raises(ValueError):
        st.update_student(c, "404", "5", "Nobody")


def test_rename_only(st):
    c = course(st)
    st.upsert_students(c, [("1", "Ali")])
    st.update_student(c, "1", "1", "Ali Hassan")
    assert st.student(c, "1")["name"] == "Ali Hassan"


def test_delete_course_cascades(st):
    c, other = course(st, "A"), course(st, "B")
    st.upsert_students(c, [("1", "Ali")])
    st.upsert_students(other, [("1", "Ali")])
    sess, keep = st.start_session(c, "L1"), st.start_session(other, "L1")
    st.add_challenge("ch1", sess, "1", "like", "dev")
    st.add_attempt(session_id=sess, student_id="1", ts=1.0, challenge="like", pred="like", conf=0.9,
                   face_sim=None, accepted=1, reason="enroll", device_id="d", source="camera", latency_ms=5.0)
    st.mark_present(sess, "1")
    st.mark_present(keep, "1")
    st.flag(sess, "1", "x", "y")
    st.delete_course(c)
    assert st.course(c) is None and st.sessions(c) == [] and st.students(c, include_removed=True) == []
    assert st.attempts(sess) == [] and st.flags(sess) == [] and st.attendance(sess) == {}
    assert "1" in st.attendance(keep)


def test_users(st):
    uid = st.create_user("A@X.com ", "Admin", "admin", "h1")
    assert st.user_by_email("a@x.com")["id"] == uid
    assert st.user(uid)["active"] == 1
    with pytest.raises(ValueError):
        st.create_user("a@x.com", "Dup", "doctor", "h")
    st.set_password(uid, "h2")
    st.set_active(uid, False)
    u = st.user(uid)
    assert u["password_hash"] == "h2" and u["active"] == 0
    assert st.count_admins() == 0  # inactive admins do not count
    st.set_active(uid, True)
    assert st.count_admins() == 1 and len(st.users()) == 1


def test_take_challenge_once(st):
    c = course(st)
    sess = st.start_session(c, "L1")
    st.add_challenge("c1", sess, "1", "like", "dev")
    assert st.take_challenge("c1")["gesture"] == "like"
    assert st.take_challenge("c1") is None
