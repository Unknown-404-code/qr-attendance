"""Doctor pages and APIs: courses, student lists, classes, live stats, QR board, Excel reports."""
from __future__ import annotations

import io
from datetime import datetime

import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from .context import AppContext, owned_course, require_user
from .report import course_report, session_report
from .roster import parse_roster
from .texts import flag_text

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def base_url(ctx: AppContext, request: Request) -> str:
    return (ctx.cfg["app"].get("base_url") or str(request.base_url)).rstrip("/")


def register(app: FastAPI, ctx: AppContext) -> None:
    store = ctx.store
    page_user, api_user = require_user(ctx, page=True), require_user(ctx)

    def my_courses(user: dict) -> list[dict]:
        out = []
        for c in store.courses(None if user["role"] == "admin" else user["id"]):
            sess = store.active_session(c["id"])
            out.append({**c, "students": len(store.students(c["id"])),
                        "active": bool(sess), "present": len(store.attendance(sess["id"])) if sess else 0})
        return out

    def course_of(cid: int, user: dict = Depends(api_user)) -> dict:
        return owned_course(ctx, user, cid)

    def course_session(course: dict, session_id: int | None) -> dict | None:
        """The requested session (must belong to the course), else the open one, else the latest."""
        if session_id:
            s = store.session(session_id)
            if s is None or s["course_id"] != course["id"]:
                raise HTTPException(404, "Class not found.")
            return s
        return store.active_session(course["id"]) or (store.sessions(course["id"]) or [None])[0]

    def active_or_404(course: dict) -> dict:
        s = store.active_session(course["id"])
        if s is None:
            raise HTTPException(404, "No class is running.")
        return s

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def home(request: Request, user: dict = Depends(page_user)):
        return ctx.render(request, "home.html", courses=my_courses(user))

    @app.get("/courses/{cid}")
    def course_page(cid: int, request: Request, user: dict = Depends(page_user)):
        course = owned_course(ctx, user, cid)
        students = store.students(cid)
        return ctx.render(request, "course.html", course=course, n_students=len(students),
                          anyone_unregistered=any(s["enroll_status"] == "none" for s in students),
                          max_attempts=ctx.cfg["app"]["max_attempts"])

    @app.get("/courses/{cid}/board")
    def board_page(cid: int, request: Request, user: dict = Depends(page_user)):
        return ctx.render(request, "board.html", course=owned_course(ctx, user, cid))

    # ------------------------------------------------------------------ courses
    @app.get("/api/courses")
    def list_courses(user: dict = Depends(api_user)):
        return my_courses(user)

    @app.post("/api/courses")
    def create_course(name: str = Form(...), user: dict = Depends(api_user)):
        if not name.strip():
            raise HTTPException(400, "Give the course a name.")
        return {"id": store.create_course(user["id"], name)}

    @app.post("/api/courses/{cid}/delete")
    def delete_course(confirm_name: str = Form(""), course: dict = Depends(course_of)):
        if confirm_name.strip() != course["name"]:
            raise HTTPException(400, "Type the course name exactly to delete it.")
        store.delete_course(course["id"])
        return {"deleted": course["id"]}

    # ------------------------------------------------------------------ students
    @app.post("/api/courses/{cid}/roster")
    async def upload_roster(file: UploadFile = File(...), course: dict = Depends(course_of)):
        try:
            rows = parse_roster(await file.read(), file.filename or "roster.csv")
        except ValueError as e:
            raise HTTPException(400, "The file needs a name column and a student ID column.") from e
        if not rows:
            raise HTTPException(400, "No students found in that file.")
        n = store.upsert_students(course["id"], rows)
        return {"imported": n, "roster": len(store.students(course["id"]))}

    @app.get("/api/courses/{cid}/students")
    def list_students(course: dict = Depends(course_of)):
        return store.students(course["id"])

    @app.post("/api/courses/{cid}/students")
    def add_student(student_id: str = Form(...), name: str = Form(""), course: dict = Depends(course_of)):
        try:
            store.add_student(course["id"], student_id, name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/courses/{cid}/students/{sid}")
    def edit_student(sid: str, student_id: str = Form(...), name: str = Form(""), course: dict = Depends(course_of)):
        try:
            store.update_student(course["id"], sid, student_id, name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/courses/{cid}/students/{sid}/remove")
    def remove_student(sid: str, course: dict = Depends(course_of)):
        if store.student(course["id"], sid) is None:
            raise HTTPException(404, "Student not found.")
        store.remove_student(course["id"], sid)
        return {"ok": True}

    # ------------------------------------------------------------------ classes
    @app.post("/api/courses/{cid}/session/start")
    def start(title: str = Form(""), enroll_open: bool = Form(False), course: dict = Depends(course_of)):
        title = title.strip() or datetime.now().strftime("Class %d %b %Y, %H:%M")
        return {"session_id": store.start_session(course["id"], title, enroll_open)}

    @app.post("/api/courses/{cid}/session/end")
    def end(course: dict = Depends(course_of)):
        s = store.active_session(course["id"])
        if s:
            store.end_session(s["id"])
        return {"ended": s["id"] if s else None}

    @app.post("/api/courses/{cid}/session/enroll")
    def enroll(open: bool = Form(...), course: dict = Depends(course_of)):
        store.set_enroll_open(active_or_404(course)["id"], open)
        return {"enroll_open": open}

    @app.get("/api/courses/{cid}/stats")
    def stats(session_id: int | None = None, course: dict = Depends(course_of)):
        sess = course_session(course, session_id)
        students = store.students(course["id"])
        history = [{"id": s["id"], "title": s["title"], "started_at": s["started_at"], "ended_at": s["ended_at"]}
                   for s in store.sessions(course["id"])]
        if sess is None:
            return {"session": None, "students": students, "present": 0, "roster": len(students), "flags": [],
                    "recent_attempts": [], "median_latency_ms": None, "pending_enrollments": [], "sessions": history}
        att = store.attendance(sess["id"])
        flags = [{**f, "text": flag_text(f["kind"], f["detail"])} for f in store.flags(sess["id"])]
        for s in students:
            a = att.get(s["student_id"])
            s["present"] = bool(a)
            s["checkin_ts"] = a["ts"] if a else None
            s["method"] = a["method"] if a else None
            s["flags"] = sorted({f["text"] for f in flags if f["student_id"] == s["student_id"]})
        atts = store.attempts(sess["id"])
        lat = [a["latency_ms"] for a in atts if a["latency_ms"]]
        return {"session": sess, "students": students, "present": sum(1 for s in students if s["present"]),
                "roster": len(students), "flags": flags, "recent_attempts": atts[-15:][::-1],
                "median_latency_ms": float(np.median(lat)) if lat else None,
                "pending_enrollments": [s for s in students if s["enroll_status"] == "pending"],
                "sessions": history}

    @app.post("/api/courses/{cid}/enrollment/{sid}/{action}")
    def enrollment(sid: str, action: str, course: dict = Depends(course_of)):
        if store.student(course["id"], sid) is None:
            raise HTTPException(404, "Student not found.")
        if action == "confirm":
            store.set_enroll_status(course["id"], sid, "confirmed")
        elif action in ("reject", "reset"):
            store.set_embedding(course["id"], sid, None, "none")
            sess = store.active_session(course["id"])
            if sess and action == "reject":
                store.unmark(sess["id"], sid)
        else:
            raise HTTPException(400, "Unknown action.")
        return {"student_id": sid, "action": action}

    @app.post("/api/courses/{cid}/attendance/{sid}")
    def manual(sid: str, present: bool = Form(...), session_id: int | None = Form(None),
               course: dict = Depends(course_of)):
        sess = course_session(course, session_id)
        if sess is None or store.student(course["id"], sid) is None:
            raise HTTPException(404, "Class or student not found.")
        if present:
            store.mark_present(sess["id"], sid, method="manual (instructor)")
        else:
            store.unmark(sess["id"], sid)
        return {"student_id": sid, "present": present}

    # ------------------------------------------------------------------ board
    def board_state(request: Request, course: dict) -> dict:
        sess = store.active_session(course["id"])
        roster = len(store.students(course["id"]))
        if sess is None:
            return {"active": False, "roster": roster, "course": course["name"]}
        present = store.attendance(sess["id"])
        return {"active": True, "session_id": sess["id"], "title": sess["title"], "course": course["name"],
                "roster": roster, "present": len(present), "enroll_open": bool(sess["enroll_open"]),
                "token": ctx.rot.token(sess["id"]), "seconds_left": round(ctx.rot.seconds_left(), 2),
                "period": ctx.rot.period}

    @app.get("/api/courses/{cid}/board/state")
    def api_board_state(request: Request, course: dict = Depends(course_of)):
        return board_state(request, course)

    @app.get("/api/courses/{cid}/board/qr.png")
    def api_qr(request: Request, course: dict = Depends(course_of)):
        import qrcode
        sess = active_or_404(course)
        url = f"{base_url(ctx, request)}/q/{sess['id']}/{ctx.rot.token(sess['id'])}"
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=2)
        qr.add_data(url)
        buf = io.BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
        return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ reports
    def safe(name: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in name).strip("_") or "course"

    @app.get("/api/courses/{cid}/report.xlsx")
    def report(session_id: int | None = None, course: dict = Depends(course_of)):
        sess = course_session(course, session_id)
        if sess is None:
            raise HTTPException(404, "No classes yet.")
        name = f"{safe(course['name'])}_{datetime.fromtimestamp(sess['started_at']):%Y-%m-%d}.xlsx"
        return Response(session_report(store, sess["id"]), media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/courses/{cid}/course_report.xlsx")
    def full_report(course: dict = Depends(course_of)):
        name = f"{safe(course['name'])}_all_classes.xlsx"
        return Response(course_report(store, course["id"]), media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
