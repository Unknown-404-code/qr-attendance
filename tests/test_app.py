import io
from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from helpers import make_app, new_doctor
from openpyxl import load_workbook
from PIL import Image

from gesture_attendance.verify import Verifier
from gesture_attendance.vision.pipelines import GestureResult
from gesture_attendance.vision.types import Box, Face


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


FACES = {"ali": unit([1, 0, 0, 0]), "sara": unit([0, 1, 0, 0]), "ali_twin": unit([1, 0.05, 0, 0])}


class Scripted:
    """The 'camera' decides what the fake CV sees: set .gesture ('auto' = do what was asked) and .face."""
    def __init__(self):
        self.gesture, self.face, self.challenge = "auto", "ali", None

    def predict(self, img):
        if self.gesture == "auto":
            g = self.challenge
        elif self.gesture == "wrong":
            g = "fist" if self.challenge != "fist" else "palm"
        else:
            g = self.gesture
        return GestureResult(g, 0.9, [], face_box=Box(0, 0, 10, 10))

    def embed_main(self, img, hint=None):
        return (FACES[self.face], Face(Box(0, 0, 10, 10), 1.0)) if self.face else (None, None)


class ScriptedVerifier(Verifier):
    def verify(self, img, challenge, enrolled):
        self.pipeline.challenge = challenge
        return super().verify(img, challenge, enrolled)


def jpeg(exif_time=None):
    buf = io.BytesIO()
    im = Image.fromarray(np.zeros((64, 48, 3), np.uint8))
    if exif_time:
        ex = Image.Exif()
        ex[306] = exif_time.strftime("%Y:%m:%d %H:%M:%S")
        im.save(buf, format="JPEG", exif=ex)
    else:
        im.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def env(tmp_path):
    cam = Scripted()
    app = make_app(tmp_path, verifier=ScriptedVerifier(cam, cam, 0.35))
    dr = new_doctor(app)
    cid = dr.post("/api/courses", data={"name": "Computer Vision"}).json()["id"]
    return app, Course(dr, cid), cam


class Course:
    """A doctor's client with the course prefix filled in: c.get("/stats") -> /api/courses/<id>/stats."""
    def __init__(self, client, cid):
        self.client, self.cid = client, cid

    def get(self, path, **kw):
        return self.client.get(f"/api/courses/{self.cid}{path}", **kw)

    def post(self, path, **kw):
        return self.client.post(f"/api/courses/{self.cid}{path}", **kw)

    def session_id(self):
        return self.get("/stats").json()["session"]["id"]


def phone(app, sess_id):
    c = TestClient(app)
    r = c.get(f"/q/{sess_id}/{app.state.rot.token(sess_id)}", follow_redirects=False)
    assert r.status_code == 303
    return c


def checkin(c, sid, img=None):
    ch = c.post("/api/challenge", data={"student_id": sid})
    assert ch.status_code == 200, ch.text
    j = ch.json()
    if j.get("already_present"):
        return j
    r = c.post("/api/verify", data={"challenge_id": j["challenge_id"]}, files={"image": ("s.jpg", img or jpeg(), "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


def test_other_doctor_gets_404(env):
    app, instr, _ = env
    instr.post("/session/start", data={})
    other = Course(new_doctor(app, "other@test.com"), instr.cid)
    for path in ("/stats", "/board/state", "/board/qr.png", "/report.xlsx", "/course_report.xlsx", "/students"):
        assert other.get(path).status_code == 404, path
    assert other.post("/session/end").status_code == 404
    assert TestClient(app).get(f"/api/courses/{instr.cid}/stats").status_code == 401


def test_full_flow(env):
    app, instr, cam = env
    roster = b"Student ID,Name\n1,Ali\n2,Sara\n3,Omar\n"
    assert instr.post("/roster", files={"file": ("r.csv", roster)}).json()["roster"] == 3

    # session 1 with enrollment open: Ali enrolls on first check-in
    instr.post("/session/start", data={"title": "L1", "enroll_open": "true"})
    p = phone(app, instr.session_id())
    assert p.get("/checkin").status_code == 200
    r = checkin(p, "1")
    assert r["accepted"] and r["reason"] == "enroll"
    st = instr.get("/stats").json()
    assert st["present"] == 1 and st["pending_enrollments"][0]["student_id"] == "1"
    instr.post("/enrollment/1/confirm")
    assert checkin(p, "1").get("already_present")

    # a friend tries to enroll Sara with Ali's face -> accepted as enrollment but flagged as duplicate face
    cam.face = "ali_twin"
    assert checkin(p, "2")["reason"] == "enroll"   # same phone as Ali
    kinds = {f["kind"] for f in instr.get("/stats").json()["flags"]}
    assert "duplicate_face" in kinds and "shared_device" in kinds
    instr.post("/enrollment/2/reject")
    assert instr.get("/stats").json()["present"] == 1

    # session 2, enrollment closed
    instr.post("/session/start", data={"title": "L2"})
    p2 = phone(app, instr.session_id())
    cam.face = "sara"
    r = checkin(p2, "1")                     # Sara's face claiming Ali
    assert not r["accepted"] and r["reason"] == "face_mismatch"
    cam.face, cam.gesture = "ali", "wrong"
    r = checkin(p2, "1")
    assert r["reason"] == "wrong_gesture" and r["attempts_left"] == 1
    cam.gesture = "auto"
    r = checkin(p2, "1")
    assert r["accepted"] and r["reason"] == "ok"
    # Omar is not enrolled and enrollment is closed
    assert p2.post("/api/challenge", data={"student_id": "3"}).status_code == 403
    assert p2.post("/api/challenge", data={"student_id": "999"}).status_code == 404
    flags = {f["kind"] for f in instr.get("/stats").json()["flags"]}
    assert "face_mismatch" in flags

    # manual override + Excel
    instr.post("/attendance/3", data={"present": "true"})
    wb = load_workbook(io.BytesIO(instr.get("/report.xlsx").content))
    status = {r[1]: r[3] for r in list(wb["Attendance"].iter_rows(values_only=True))[1:]}
    assert status["3"] == "Present" and status["2"] == "Not present"
    assert instr.get("/course_report.xlsx").status_code == 200


def test_attempt_limit(env):
    app, instr, cam = env
    instr.post("/roster", files={"file": ("r.csv", b"id,name\n1,Ali\n")})
    instr.post("/session/start", data={"enroll_open": "true"})
    p = phone(app, instr.session_id())
    cam.gesture = "none"
    for _ in range(3):
        r = checkin(p, "1")
        assert not r["accepted"]
    assert r["attempts_left"] == 0
    assert p.post("/api/challenge", data={"student_id": "1"}).status_code == 429


def test_expired_qr_and_ticket(env):
    app, instr, _ = env
    instr.post("/session/start", data={})
    c = TestClient(app)
    sess = instr.session_id()
    assert c.get(f"/q/{sess}/notavalidtoken", follow_redirects=False).status_code == 410
    assert c.get("/q/notavalidtoken", follow_redirects=False).status_code == 404
    assert c.get("/checkin").status_code == 410
    assert c.post("/api/challenge", data={"student_id": "1"}).status_code == 401


def test_challenge_single_use_and_stale_photo(env):
    app, instr, cam = env
    instr.post("/roster", files={"file": ("r.csv", b"id,name\n1,Ali\n")})
    instr.post("/session/start", data={"enroll_open": "true"})
    p = phone(app, instr.session_id())
    j = p.post("/api/challenge", data={"student_id": "1"}).json()
    old = jpeg(datetime.now() - timedelta(days=2))
    r = p.post("/api/verify", data={"challenge_id": j["challenge_id"]}, files={"image": ("s.jpg", old, "image/jpeg")})
    assert r.json()["reason"] == "stale_photo"
    r = p.post("/api/verify", data={"challenge_id": j["challenge_id"]}, files={"image": ("s.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 400  # challenge already used
    # another phone cannot use this phone's challenge
    j = p.post("/api/challenge", data={"student_id": "1"}).json()
    other = phone(app, instr.session_id())
    r = other.post("/api/verify", data={"challenge_id": j["challenge_id"]}, files={"image": ("s.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 400


def test_board_qr_and_collect(env, tmp_path):
    app, instr, _ = env
    assert instr.get("/board/state").json()["active"] is False
    instr.post("/session/start", data={})
    s = instr.get("/board/state").json()
    assert s["active"] and s["token"]
    png = instr.get("/board/qr.png")
    assert png.headers["content-type"] == "image/png"
    img = cv2.imdecode(np.frombuffer(png.content, np.uint8), cv2.IMREAD_COLOR)
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    assert data.endswith(f"/q/{instr.session_id()}/" + s["token"])
    r = instr.client.post("/api/collect", data={"subject_id": "s01", "gesture": "like", "condition": "normal", "consent": "true"},
                   files={"image": ("x.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 200
    assert (tmp_path / "collect" / "labels.csv").read_text().count("\n") == 2
