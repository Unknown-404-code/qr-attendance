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
    return re.search(r'<a[^>]*href="/"[^>]*>\s*Courses\s*</a>', html) is not None


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
