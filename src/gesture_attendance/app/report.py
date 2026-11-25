"""Excel attendance reports (openpyxl)."""
from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .store import Store
from .texts import flag_text

GREEN = PatternFill("solid", fgColor="C6EFCE")
RED = PatternFill("solid", fgColor="FFC7CE")
HEAD = PatternFill("solid", fgColor="1F3864")
WHITE_BOLD = Font(bold=True, color="FFFFFF")


def _ts(t) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t else ""


def _name(s: dict) -> str:
    return s["name"] + (" (removed)" if s.get("removed") else "")


def _header(ws, cols: list[str], widths: list[int]):
    ws.append(cols)
    for i, w in enumerate(widths, 1):
        c = ws.cell(row=1, column=i)
        c.fill, c.font, c.alignment = HEAD, WHITE_BOLD, Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def session_report(store: Store, session_id: int) -> bytes:
    sess = store.session(session_id)
    if sess is None:
        raise KeyError(session_id)
    students = store.report_students(sess["course_id"], [session_id])
    present = store.attendance(session_id)
    flags = store.flags(session_id)
    notes: dict[str, list[str]] = {}
    for f in flags:
        notes.setdefault(f["student_id"], []).append(flag_text(f["kind"], f["detail"]))

    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    _header(ws, ["No.", "Student ID", "Name", "Status", "Check-in time", "Method", "Face similarity", "Notes"],
            [6, 16, 32, 14, 21, 14, 15, 40])
    for i, s in enumerate(students, 1):
        p = present.get(s["student_id"])
        note = sorted(set(notes.get(s["student_id"], [])))
        if s["enroll_status"] == "pending":
            note.insert(0, "Face photo waiting for approval")
        ws.append([i, s["student_id"], _name(s), "Present" if p else "Not present", _ts(p and p["ts"]),
                   p["method"] if p else "", round(p["face_sim"], 3) if p and p["face_sim"] is not None else "",
                   "; ".join(note)])
        ws.cell(row=i + 1, column=4).fill = GREEN if p else RED
    ws.auto_filter.ref = f"A1:H{len(students) + 1}"

    n_present = sum(1 for s in students if s["student_id"] in present)
    sm = wb.create_sheet("Summary")
    for row in [("Session", sess["title"] or f"Session {session_id}"), ("Started", _ts(sess["started_at"])),
                ("Ended", _ts(sess["ended_at"]) or "(open)"), ("Roster size", len(students)),
                ("Present", n_present), ("Not present", len(students) - n_present),
                ("Attendance rate", f"{100 * n_present / len(students):.1f}%" if students else "-"),
                ("Flags", len(flags)), ("Generated", _ts(datetime.now().timestamp()))]:
        sm.append(row)
        sm.cell(row=sm.max_row, column=1).font = Font(bold=True)
    sm.column_dimensions["A"].width, sm.column_dimensions["B"].width = 18, 34

    fl = wb.create_sheet("Flags")
    _header(fl, ["Time", "Student ID", "Problem", "Detail"], [21, 16, 22, 60])
    for f in flags:
        fl.append([_ts(f["ts"]), f["student_id"], flag_text(f["kind"], f["detail"]), f["detail"]])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def course_report(store: Store, course_id: int) -> bytes:
    """All sessions of a course: one row per student, one column per session (P / blank) + totals."""
    sessions = list(reversed(store.sessions(course_id)))
    students = store.report_students(course_id, [s["id"] for s in sessions])
    att = {s["id"]: store.attendance(s["id"]) for s in sessions}
    wb = Workbook()
    ws = wb.active
    ws.title = "Course attendance"
    cols = ["Student ID", "Name"] + [f"{_ts(s['started_at'])[:10]} {s['title'] or ''}".strip() for s in sessions] + ["Attended", "Rate"]
    _header(ws, cols, [16, 32] + [14] * len(sessions) + [10, 8])
    for r, s in enumerate(students, 2):
        marks = ["P" if s["student_id"] in att[x["id"]] else "" for x in sessions]
        n = marks.count("P")
        ws.append([s["student_id"], _name(s), *marks, n, f"{100 * n / len(sessions):.0f}%" if sessions else ""])
        for c, m in enumerate(marks, 3):
            ws.cell(row=r, column=c).fill = GREEN if m else RED
            ws.cell(row=r, column=c).alignment = Alignment(horizontal="center")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
