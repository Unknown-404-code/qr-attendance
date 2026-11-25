"""Regression tests for the findings of the final branch review."""
import asyncio
import io
import time
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from helpers import ADMIN, admin_client, login, make_app, new_doctor
from PIL import Image
from test_app import Course, Scripted, ScriptedVerifier, checkin, phone

from gesture_attendance.app.db import connect, is_postgres_url


def jpeg_with_exif(taken: datetime, offset: str | None = None) -> bytes:
    """A JPEG whose EXIF says it was taken at `taken` (naive local time), optionally with OffsetTimeOriginal."""
    ex = Image.Exif()
    sub = ex.get_ifd(0x8769)
    sub[36867] = taken.strftime("%Y:%m:%d %H:%M:%S")
    if offset:
        sub[36881] = offset  # OffsetTimeOriginal, e.g. "+04:00"
    buf = io.BytesIO()
    Image.fromarray(np.zeros((64, 48, 3), np.uint8)).save(buf, format="JPEG", exif=ex)
    return buf.getvalue()


def course_with_class(tmp_path, verifier=None):
    cam = Scripted()
    app = make_app(tmp_path, verifier=verifier or ScriptedVerifier(cam, cam, 0.35))
    c = Course(new_doctor(app), None)
    c.cid = c.client.post("/api/courses", data={"name": "CV"}).json()["id"]
    c.post("/roster", files={"file": ("r.csv", b"id,name\n1,Ali\n2,Sara\n")})
    c.post("/session/start", data={"enroll_open": "true"})
    return app, c, cam


def send_photo(app, c, img):
    p = phone(app, c.session_id())
    j = p.post("/api/challenge", data={"student_id": "1"}).json()
    return p.post("/api/verify", data={"challenge_id": j["challenge_id"]},
                  files={"image": ("s.jpg", img, "image/jpeg")}).json()


# 1. phone EXIF times are the phone's local time; the server may run in UTC
def test_fresh_photo_from_other_timezone_is_accepted(tmp_path):
    app, c, _ = course_with_class(tmp_path)
    phone_now = datetime.now(timezone(timedelta(hours=-10))).replace(tzinfo=None)
    assert send_photo(app, c, jpeg_with_exif(phone_now, "-10:00"))["accepted"]


def test_fresh_photo_without_offset_is_accepted_across_zones(tmp_path):
    app, c, _ = course_with_class(tmp_path)
    phone_now = datetime.now(timezone(timedelta(hours=-7))).replace(tzinfo=None)
    assert send_photo(app, c, jpeg_with_exif(phone_now))["accepted"]


def test_old_photo_is_still_rejected(tmp_path):
    app, c, _ = course_with_class(tmp_path)
    old = datetime.now(timezone(timedelta(hours=4))) - timedelta(hours=3)
    assert send_photo(app, c, jpeg_with_exif(old.replace(tzinfo=None), "+04:00"))["reason"] == "stale_photo"
    two_days = datetime.now() - timedelta(days=2)
    assert send_photo(app, c, jpeg_with_exif(two_days))["reason"] == "stale_photo"


# 3. a silently dropped connection must time out instead of hanging
def test_postgres_connection_has_timeouts(db_url):
    if not is_postgres_url(db_url[0]):
        pytest.skip("postgres only")
    params = connect(*db_url).conn.info.get_parameters()
    assert params.get("connect_timeout") == "10"
    assert params.get("keepalives") == "1" and params.get("keepalives_idle") == "60"


# 4. checking a selfie must not freeze the rest of the server
class SlowVerifier(ScriptedVerifier):
    def verify(self, img, challenge, enrolled):
        time.sleep(1.5)
        return super().verify(img, challenge, enrolled)


def test_verify_does_not_block_other_requests(tmp_path):
    cam = Scripted()
    app, c, _ = course_with_class(tmp_path, verifier=SlowVerifier(cam, cam, 0.35))
    p = phone(app, c.session_id())
    ch = p.post("/api/challenge", data={"student_id": "1"}).json()
    cookies = dict(p.cookies)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t", cookies=cookies) as a, \
                httpx.AsyncClient(transport=transport, base_url="http://t") as b:
            buf = io.BytesIO()
            Image.fromarray(np.zeros((64, 48, 3), np.uint8)).save(buf, format="JPEG")
            t0 = time.perf_counter()
            slow = asyncio.create_task(a.post("/api/verify", data={"challenge_id": ch["challenge_id"]},
                                              files={"image": ("s.jpg", buf.getvalue(), "image/jpeg")}))
            await asyncio.sleep(0.2)
            r = await b.get("/login")
            fast_s = time.perf_counter() - t0
            await slow
            return r.status_code, fast_s

    status, fast_s = asyncio.run(run())
    assert status == 200 and fast_s < 0.8, f"/login waited {fast_s:.2f}s behind a selfie check"


# 5. a password change signs out every other browser
def test_password_change_signs_out_other_browsers(tmp_path):
    app = make_app(tmp_path)
    laptop = admin_client(app)
    phone_browser = admin_client(app)
    assert phone_browser.get("/api/courses").status_code == 200
    laptop.post("/api/account/password", data={"current": ADMIN[1], "new": "a-new-password"})
    assert phone_browser.get("/api/courses").status_code == 401
    assert laptop.get("/api/courses").status_code == 200  # the browser that changed it stays signed in


def test_admin_reset_signs_out_the_doctor(tmp_path):
    app = make_app(tmp_path)
    dr = new_doctor(app)
    adm = admin_client(app)
    uid = next(u["id"] for u in adm.get("/api/admin/users").json() if u["role"] == "doctor")
    pw = adm.post(f"/api/admin/users/{uid}/password").json()["password"]
    assert dr.get("/api/courses").status_code == 401
    login(TestClient(app), "dr@test.com", pw)


# 6. a removed student can be added back by hand
def test_removed_student_can_be_added_back(tmp_path):
    app, c, _ = course_with_class(tmp_path)
    assert checkin(phone(app, c.session_id()), "2")["accepted"]
    c.post("/students/2/remove")
    r = c.post("/students", data={"student_id": "2", "name": "Sara Khalid"})
    assert r.status_code == 200, r.text
    st = {s["student_id"]: s for s in c.get("/stats").json()["students"]}
    assert st["2"]["name"] == "Sara Khalid" and st["2"]["present"]
    assert c.post("/students", data={"student_id": "2", "name": "Again"}).status_code == 400
