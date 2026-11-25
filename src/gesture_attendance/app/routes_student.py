"""Student check-in (no login): scan QR -> ticket cookie -> student ID -> gesture challenge -> selfie.

Also the volunteer test-set collection page, which only runs on a laptop (hosted disks are wiped on restart).
"""
from __future__ import annotations

import csv
import secrets
import time
from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from ..config import resolve_path
from ..gestures import gesture_parts, gesture_text
from ..vision.face_recognizer import cosine
from . import texts
from .context import AppContext, require_user

TICKET_COOKIE, DEVICE_COOKIE = "ga_ticket", "ga_dev"


def register(app: FastAPI, ctx: AppContext) -> None:
    from .main import decode_image  # main imports this module; import lazily to avoid a cycle

    store, A = ctx.store, ctx.cfg["app"]

    def open_session(session_id) -> dict | None:
        s = store.session(int(session_id)) if session_id is not None else None
        return s if s and s["ended_at"] is None else None

    def ticket(request: Request) -> tuple[dict, dict] | None:
        t = ctx.signer.unsign(request.cookies.get(TICKET_COOKIE))
        sess = open_session(t.get("sid")) if t else None
        return (t, sess) if sess else None

    def expired(request: Request):
        return ctx.render(request, "message.html", status_code=410, title=texts.EXPIRED_TITLE, msg=texts.EXPIRED_TEXT)

    @app.get("/q/{session_id}/{token}")
    def scan(session_id: int, token: str, request: Request):
        sess = open_session(session_id)
        if sess is None or not ctx.rot.verify(session_id, token):
            return expired(request)
        dev = request.cookies.get(DEVICE_COOKIE) or secrets.token_urlsafe(9)
        secure = request.url.scheme == "https"
        resp = RedirectResponse("/checkin", status_code=303)
        resp.set_cookie(TICKET_COOKIE, ctx.signer.sign({"sid": sess["id"], "dev": dev}, A["ticket_ttl_s"]),
                        httponly=True, samesite="lax", secure=secure, max_age=int(A["ticket_ttl_s"]))
        resp.set_cookie(DEVICE_COOKIE, dev, httponly=True, samesite="lax", secure=secure, max_age=365 * 86400)
        return resp

    @app.get("/checkin")
    def checkin_page(request: Request):
        tk = ticket(request)
        if tk is None:
            return expired(request)
        t, sess = tk
        course = store.course(sess["course_id"])
        return ctx.render(request, "checkin.html", title=sess["title"], course=course["name"] if course else "",
                          seconds_left=int(t["exp"] - time.time()))

    @app.post("/api/challenge")
    def new_challenge(request: Request, student_id: str = Form(...)):
        tk = ticket(request)
        if tk is None:
            raise HTTPException(401, texts.EXPIRED_TEXT)
        t, sess = tk
        sid = student_id.strip()
        st = store.student(sess["course_id"], sid)
        if st is None:
            raise HTTPException(404, texts.NOT_ON_LIST)
        if store.is_present(sess["id"], sid):
            return {"already_present": True, "name": st["name"]}
        if store.n_attempts(sess["id"], sid) >= A["max_attempts"]:
            store.flag(sess["id"], sid, "max_attempts", f"limit {A['max_attempts']} reached")
            raise HTTPException(429, texts.NO_TRIES_LEFT)
        enrolling = st["enroll_status"] == "none" or store.embedding(sess["course_id"], sid) is None
        if enrolling and not sess["enroll_open"]:
            raise HTTPException(403, texts.NOT_ENROLLED)
        others = store.students_on_device(sess["id"], t["dev"]) - {sid}
        if others:
            store.flag(sess["id"], sid, "shared_device", "same phone also used for " + ", ".join(sorted(others)))
        cid = secrets.token_urlsafe(12)
        g = secrets.choice(ctx.gestures)
        emoji, name_text = gesture_parts(g)
        store.add_challenge(cid, sess["id"], sid, g, t["dev"])
        return {"challenge_id": cid, "gesture": g, "text": gesture_text(g), "emoji": emoji, "name_text": name_text,
                "name": st["name"], "expires_in": A["challenge_ttl_s"], "enrolling": enrolling,
                "attempts_left": A["max_attempts"] - store.n_attempts(sess["id"], sid)}

    @app.post("/api/verify")
    async def verify(request: Request, challenge_id: str = Form(...), image: UploadFile = File(...),
                     source: str = Form("camera")):
        tk = ticket(request)
        if tk is None:
            raise HTTPException(401, texts.EXPIRED_TEXT)
        t, _ = tk
        ch = store.take_challenge(challenge_id)
        if ch is None or ch["session_id"] != t["sid"] or ch["device_id"] != t["dev"]:
            raise HTTPException(400, texts.CHALLENGE_USED)
        data = await image.read()
        if len(data) > 12 * 2**20:
            raise HTTPException(413, texts.PHOTO_TOO_BIG)
        sid, sess_id = ch["student_id"], ch["session_id"]
        sess = store.session(sess_id)
        cid = sess["course_id"]

        def result(reason, accepted, n):
            return {"accepted": accepted, "reason": reason, "message": texts.MESSAGES.get(reason, reason),
                    "gesture_pred": "", "attempts_left": max(0, A["max_attempts"] - n)}

        def finish(reason, accepted=False, pred="", conf=None, sim=None, latency=None):
            store.add_attempt(session_id=sess_id, student_id=sid, ts=time.time(), challenge=ch["gesture"],
                              pred=pred, conf=conf, face_sim=sim, accepted=int(accepted), reason=reason,
                              device_id=t["dev"], source=source[:16], latency_ms=latency)
            n = store.n_attempts(sess_id, sid)
            if not accepted and n >= A["max_attempts"]:
                store.flag(sess_id, sid, "max_attempts", f"limit {A['max_attempts']} reached")
            elif not accepted and n >= 2:
                store.flag(sess_id, sid, "repeat_attempts", f"{n} failed attempts")
            return {**result(reason, accepted, n), "gesture_pred": pred}

        if time.time() - ch["created_at"] > A["challenge_ttl_s"]:
            return finish("challenge_expired")
        try:
            img, taken = decode_image(data)
        except Exception:
            # an unreadable file (HEIC, broken upload) is not a failed try: the student just picks another photo
            return result("bad_image", False, store.n_attempts(sess_id, sid))
        max_age = A.get("max_photo_age_s", 600)
        if taken is not None and max_age and abs((datetime.now() - taken).total_seconds()) > max_age:
            store.flag(sess_id, sid, "stale_photo", f"EXIF time {taken:%Y-%m-%d %H:%M}")
            return finish("stale_photo")

        enrolled = store.embedding(cid, sid)
        if enrolled is None and not sess["enroll_open"]:
            raise HTTPException(403, texts.NOT_ENROLLED)
        with ctx.vlock:
            d = ctx.get_verifier().verify(img, ch["gesture"], enrolled)
        del img  # the selfie is never stored

        if d.accepted and d.reason == "enroll":
            dup_thr = ctx.cfg["verification"].get("duplicate_face_threshold", 0.5)
            for other, e in store.all_embeddings(cid).items():
                if other != sid and cosine(d.embedding, e) >= dup_thr:
                    store.flag(sess_id, sid, "duplicate_face", f"face matches enrolled student {other}")
            store.set_embedding(cid, sid, d.embedding, "pending")
        if d.accepted:
            store.mark_present(sess_id, sid, t["dev"], d.face_sim,
                               "enrollment" if d.reason == "enroll" else "gesture+face")
        elif d.reason == "face_mismatch":
            store.flag(sess_id, sid, "face_mismatch", f"similarity {d.face_sim:.2f}")
        return finish(d.reason, d.accepted, d.gesture_pred, d.gesture_conf, d.face_sim, d.timings_ms.get("total"))

    # ------------------------------------------------------------------ volunteer test-set collection (laptop only)
    if ctx.hosted:
        return
    collect_dir = resolve_path(A.get("collect_dir", "data/classroom"))
    page_user, api_user = require_user(ctx, page=True), require_user(ctx)

    @app.get("/collect")
    def collect_page(request: Request, user: dict = Depends(page_user)):
        return ctx.render(request, "collect.html", gestures=ctx.gestures)

    @app.post("/api/collect")
    async def api_collect(subject_id: str = Form(...), gesture: str = Form(...), condition: str = Form(...),
                          background_gesture: str = Form(""), consent: bool = Form(False),
                          image: UploadFile = File(...), user: dict = Depends(api_user)):
        if not consent:
            raise HTTPException(400, "Consent is required.")
        safe = lambda s: "".join(ch for ch in s.strip() if ch.isalnum() or ch in "-_") or "x"  # noqa: E731
        img, _ = decode_image(await image.read(), max_side=4096)
        from PIL import Image
        (collect_dir / "images").mkdir(parents=True, exist_ok=True)
        stem = f"{safe(subject_id)}_{safe(gesture)}_{safe(condition)}"
        k = 1
        while (collect_dir / "images" / f"{stem}_{k}.jpg").exists():
            k += 1
        rel = f"images/{stem}_{k}.jpg"
        Image.fromarray(img[:, :, ::-1]).save(collect_dir / rel, quality=95)
        labels = collect_dir / "labels.csv"
        new = not labels.exists()
        with open(labels, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["file", "subject_id", "gesture", "condition", "background_gesture"])
            w.writerow([rel, subject_id.strip(), gesture, condition, background_gesture])
        return {"saved": rel}
