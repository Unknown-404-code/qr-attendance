import io

from fastapi.testclient import TestClient
from helpers import make_app, new_doctor
from openpyxl import load_workbook
from test_app import Course, Scripted, ScriptedVerifier, checkin, jpeg, phone

ROSTER = b"Student ID,Name\n1,Ali\n2,Sara\n"


def setup(tmp_path):
    cam = Scripted()
    app = make_app(tmp_path, verifier=ScriptedVerifier(cam, cam, 0.35))
    dr = new_doctor(app)
    a = Course(dr, dr.post("/api/courses", data={"name": "A"}).json()["id"])
    b = Course(dr, dr.post("/api/courses", data={"name": "B"}).json()["id"])
    for c in (a, b):
        c.post("/roster", files={"file": ("r.csv", ROSTER)})
        c.post("/session/start", data={"enroll_open": "true"})
    return app, dr, a, b, cam


def present_ids(course):
    return {s["student_id"] for s in course.get("/stats").json()["students"] if s["present"]}


def test_qr_is_bound_to_its_course(tmp_path):
    app, _, a, b, _ = setup(tmp_path)
    assert checkin(phone(app, a.session_id()), "1")["accepted"]
    assert present_ids(a) == {"1"} and present_ids(b) == set()


def test_ended_session_qr_stops_working(tmp_path):
    app, _, a, _, _ = setup(tmp_path)
    sess = a.session_id()
    a.post("/session/end")
    assert TestClient(app).get(f"/q/{sess}/{app.state.rot.token(sess)}", follow_redirects=False).status_code == 410


def test_edit_student_keeps_history(tmp_path):
    app, _, a, _, _ = setup(tmp_path)
    assert checkin(phone(app, a.session_id()), "1")["accepted"]
    r = a.post("/students/1", data={"student_id": "11", "name": "Ali Hassan"})
    assert r.status_code == 200, r.text
    assert present_ids(a) == {"11"}
    rows = list(load_workbook(io.BytesIO(a.get("/report.xlsx").content))["Attendance"].iter_rows(values_only=True))
    status = {r[1]: (r[2], r[3]) for r in rows[1:]}
    assert status["11"] == ("Ali Hassan", "Present")
    assert a.post("/students/11", data={"student_id": "2", "name": "X"}).status_code == 400


def test_add_student_by_hand(tmp_path):
    app, _, a, _, _ = setup(tmp_path)
    assert a.post("/students", data={"student_id": " 0042 ", "name": "Omar"}).status_code == 200
    assert a.post("/students", data={"student_id": "0042", "name": "Again"}).status_code == 400
    ids = [s["student_id"] for s in a.get("/students").json()]
    assert "0042" in ids
    assert checkin(phone(app, a.session_id()), "0042")["accepted"]


def test_removed_student_cannot_check_in(tmp_path):
    app, _, a, _, _ = setup(tmp_path)
    old = a.session_id()
    assert checkin(phone(app, old), "2")["accepted"]
    assert a.post("/students/2/remove").status_code == 200
    a.post("/session/start", data={})
    p = phone(app, a.session_id())
    r = p.post("/api/challenge", data={"student_id": "2"})
    assert r.status_code == 404 and "isn't on the class list" in r.json()["detail"]
    rows = list(load_workbook(io.BytesIO(a.get(f"/report.xlsx?session_id={old}").content))["Attendance"].iter_rows(values_only=True))
    assert {r[1]: r[2] for r in rows[1:]}["2"] == "Sara (removed)"
    assert "2" not in {s["student_id"] for s in a.get("/stats").json()["students"]}


def test_delete_course_needs_name(tmp_path):
    app, dr, a, b, _ = setup(tmp_path)
    assert a.post("/delete", data={"confirm_name": "wrong"}).status_code == 400
    assert a.post("/delete", data={"confirm_name": "A"}).status_code == 200
    assert [c["name"] for c in dr.get("/api/courses").json()] == ["B"]
    assert a.get("/stats").status_code == 404


def test_bad_image_keeps_attempts(tmp_path):
    app, _, a, _, _ = setup(tmp_path)
    p = phone(app, a.session_id())
    j = p.post("/api/challenge", data={"student_id": "1"}).json()
    r = p.post("/api/verify", data={"challenge_id": j["challenge_id"]},
               files={"image": ("s.heic", b"not an image", "image/heic")})
    assert r.status_code == 200
    assert r.json()["reason"] == "bad_image" and r.json()["attempts_left"] == 3


def test_session_id_from_other_course_is_404(tmp_path):
    app, _, a, b, _ = setup(tmp_path)
    assert a.get(f"/stats?session_id={b.session_id()}").status_code == 404
    assert a.get(f"/report.xlsx?session_id={b.session_id()}").status_code == 404
    assert jpeg()  # keep the shared helper imported
