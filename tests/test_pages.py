import re

from helpers import make_app, new_doctor
from test_app import Course, Scripted, ScriptedVerifier, phone

from gesture_attendance.app import texts

BANNED = ["delve", "foster", "leverage", "utilize", "facilitate", "empower", "streamline", "robust", "cutting-edge",
          "seamless", "elevate", "embark", "supercharge", "harness", "meticulous", "paramount", "transformative"]


def setup(tmp_path, roster=None):
    cam = Scripted()
    app = make_app(tmp_path, verifier=ScriptedVerifier(cam, cam, 0.35))
    dr = new_doctor(app)
    c = Course(dr, dr.post("/api/courses", data={"name": "Computer Vision"}).json()["id"])
    if roster:
        c.post("/roster", files={"file": ("r.csv", roster)})
    return app, dr, c


def test_home_and_course_pages_render(tmp_path):
    app, dr, c = setup(tmp_path)
    home = dr.get("/")
    assert home.status_code == 200 and "Computer Vision" in home.text and "New course" in home.text
    page = dr.get(f"/courses/{c.cid}")
    assert page.status_code == 200 and "Upload" in page.text
    c.post("/roster", files={"file": ("r.csv", b"id,name\n1,Ali\n2,Sara\n")})
    assert "Students (2)" in dr.get(f"/courses/{c.cid}").text
    assert dr.get(f"/courses/{c.cid}/board").status_code == 200


def test_home_shows_running_class(tmp_path):
    app, dr, c = setup(tmp_path, b"id,name\n1,Ali\n")
    c.post("/session/start", data={})
    assert "Class running: 0 checked in" in dr.get("/").text


def test_other_doctor_cannot_open_course_page(tmp_path):
    app, dr, c = setup(tmp_path)
    other = new_doctor(app, "o@test.com")
    assert other.get(f"/courses/{c.cid}").status_code == 404


def test_no_internal_codes_in_stats_text(tmp_path):
    app, dr, c = setup(tmp_path, b"id,name\n1,Ali\n2,Sara\n")
    c.post("/session/start", data={"enroll_open": "true"})
    p = phone(app, c.session_id())
    p.post("/api/challenge", data={"student_id": "1"})
    p.post("/api/challenge", data={"student_id": "2"})
    flags = c.get("/stats").json()["flags"]
    assert flags[0]["text"].startswith("Same phone used") and "_" not in flags[0]["text"]
    sara = next(s for s in c.get("/stats").json()["students"] if s["student_id"] == "2")
    assert sara["flags"] == ["Same phone used for another student (1)"]


def test_messages_follow_copy_rules():
    every = list(texts.MESSAGES.values()) + list(texts.FLAG_TEXT.values()) + [
        texts.LOGIN_WRONG, texts.LOGIN_BLOCKED, texts.EXPIRED_TITLE, texts.EXPIRED_TEXT, texts.NOT_ON_LIST,
        texts.NO_TRIES_LEFT, texts.NOT_ENROLLED, texts.CHALLENGE_USED, texts.PHOTO_TOO_BIG]
    for s in every:
        assert "—" not in s and "_" not in s, s
        assert not any(re.search(rf"\b{w}\b", s, re.I) for w in BANNED), s


def test_challenge_returns_emoji(tmp_path):
    app, dr, c = setup(tmp_path, b"id,name\n1,Ali\n")
    c.post("/session/start", data={"enroll_open": "true"})
    j = phone(app, c.session_id()).post("/api/challenge", data={"student_id": "1"}).json()
    assert j["emoji"] and j["name_text"] and not j["name_text"].endswith(j["emoji"])


def test_checkin_page_shows_steps(tmp_path):
    app, dr, c = setup(tmp_path, b"id,name\n1,Ali\n")
    c.post("/session/start", data={"title": "Week 3"})
    p = phone(app, c.session_id())
    html = p.get("/checkin").text
    assert "Computer Vision" in html and "Week 3" in html and "Your student ID" in html


def test_expired_page_copy(tmp_path):
    app, dr, c = setup(tmp_path)
    from fastapi.testclient import TestClient
    r = TestClient(app).get("/checkin")
    assert r.status_code == 410 and texts.EXPIRED_TEXT in r.text
