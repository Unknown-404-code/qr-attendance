"""The Chalkboard look: exact colors, readable contrast, and a visible way back to the courses."""
import re
from pathlib import Path

from fastapi.testclient import TestClient
from helpers import admin_client, make_app, new_doctor
from test_app import Course

BASE = Path(__file__).resolve().parents[1] / "src/gesture_attendance/app/templates/_base.html"


def root_vars() -> dict[str, str]:
    css = BASE.read_text(encoding="utf-8")
    block = re.search(r":root\s*\{(.*?)\}", css, re.S).group(1)
    return {k: v.strip() for k, v in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block)}


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_theme_colors():
    v = root_vars()
    assert v["board"].upper() == "#1F3B2D"
    assert v["chalk-yellow"].upper() == "#F2C14E"
    assert v["paper"].upper() == "#F7F3EA"


def test_theme_contrast():
    v = root_vars()
    pairs = [("ink", "paper"), ("ink", "card"), ("muted", "card"), ("muted", "paper"), ("chalk", "board"),
             ("chalk-yellow", "board"), ("board", "chalk-yellow"), ("ok", "okbg"), ("bad", "badbg"),
             ("warn", "warnbg"), ("accent", "card")]
    for fg, bg in pairs:
        ratio = contrast(v[fg], v[bg])
        assert ratio >= 4.5, f"--{fg} on --{bg} is only {ratio:.2f}:1"


def test_hidden_rule_kept():
    assert "[hidden] { display:none !important; }" in BASE.read_text(encoding="utf-8")


def courses_link(html: str) -> bool:
    return re.search(r'<a[^>]*href="/"[^>]*>(?:\s*<svg.*?</svg>)?\s*(?:<span[^>]*>)?Courses(?:</span>)?\s*</a>',
                     html, re.S) is not None


def test_nav_links(tmp_path):
    app = make_app(tmp_path)
    dr = new_doctor(app)
    cid = dr.post("/api/courses", data={"name": "CV"}).json()["id"]
    for page in ("/", "/account", f"/courses/{cid}"):
        assert courses_link(dr.get(page).text), page
    assert "All courses" in dr.get("/account").text
    assert "All courses" in admin_client(app).get("/admin").text
    anon = TestClient(app)
    assert not courses_link(anon.get("/login").text)
    assert not courses_link(anon.get("/checkin").text)
    assert Course  # shared helper import kept for later theme tests


def doctor_course(tmp_path):
    app = make_app(tmp_path)
    dr = new_doctor(app)
    c = Course(dr, dr.post("/api/courses", data={"name": "CV"}).json()["id"])
    c.post("/roster", files={"file": ("r.csv", b"id,name\n1,Ali\n")})
    return app, dr, c


def test_course_live_panel_is_board(tmp_path):
    app, dr, c = doctor_course(tmp_path)
    html = dr.get(f"/courses/{c.cid}").text
    assert re.search(r'<section class="[^"]*\bboard\b[^"]*" id="live-box"', html)
    assert 'class="chalk-num"' in html


def test_home_running_tag(tmp_path):
    app, dr, c = doctor_course(tmp_path)
    c.post("/session/start", data={})
    html = dr.get("/").text
    assert 'class="live-tag"' in html and "Class running" in html


def test_login_board_hero(tmp_path):
    assert 'class="board login-hero"' in TestClient(make_app(tmp_path)).get("/login").text


def test_qr_board_chalk(tmp_path):
    app, dr, c = doctor_course(tmp_path)
    html = dr.get(f"/courses/{c.cid}/board").text
    assert 'class="chalk-page"' in html and 'id="qr-card"' in html


def test_checkin_board_header(tmp_path):
    from test_app import phone
    app, dr, c = doctor_course(tmp_path)
    c.post("/session/start", data={"title": "Week 2"})
    html = phone(app, c.session_id()).get("/checkin").text
    assert re.search(r'class="board checkin-head"[^>]*>.*?CV', html, re.S)


def test_course_summary_numbers(tmp_path):
    from test_app import Scripted, ScriptedVerifier, checkin, phone
    cam = Scripted()
    app = make_app(tmp_path, verifier=ScriptedVerifier(cam, cam, 0.35))
    dr = new_doctor(app)
    c = Course(dr, dr.post("/api/courses", data={"name": "CV"}).json()["id"])
    c.post("/roster", files={"file": ("r.csv", b"id,name\n1,Ali\n2,Sara\n3,Omar\n4,Mariam\n")})
    [course] = dr.get("/api/courses").json()
    assert course["classes"] == 0 and course["avg_rate"] is None and course["last_class_at"] is None
    for present in (["1", "2"], ["1"]):           # 50% then 25%
        c.post("/session/start", data={"enroll_open": "true"})
        for sid in present:
            assert checkin(phone(app, c.session_id()), sid)["accepted"]
        c.post("/session/end")
    c.post("/session/start", data={})              # a running class doesn't count yet
    [course] = dr.get("/api/courses").json()
    assert course["classes"] == 2 and round(course["avg_rate"], 3) == 0.375 and course["last_class_at"]
    html = dr.get(f"/courses/{c.cid}").text
    assert "38%" in html and "2 classes" in html
    home = dr.get("/").text
    assert "4 students" in home and "38%" in home
