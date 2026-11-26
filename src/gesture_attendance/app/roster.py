"""Import the instructor's class roster from CSV or Excel.

Expected layout: three columns, Last Name, First Name, Username. The username is the student ID, and the
name is stored as "First Last". The older two-column layout (Student ID, Name) still works as a fallback.
Header spelling is flexible ("last_name", "Surname", "User Name", ...).
"""
from __future__ import annotations

import csv
import io
import re

LAST_KEYS = ("last name", "lastname", "surname", "family name")
FIRST_KEYS = ("first name", "firstname", "given name")
USER_KEYS = ("username", "user name", "user")
NAME_KEYS = ("name", "student name", "full name", "studentname", "fullname")
ID_KEYS = ("student id", "student_id", "studentid", "id", "student number", "university id", "uid")
FORMAT_ERROR = "The file needs three columns: Last Name, First Name, Username (the student ID)."


def _norm(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower().replace("_", " "))


def _find(header: list[str], keys) -> int | None:
    norm = [_norm(h) for h in header]
    for k in keys:
        k = _norm(k)
        if k in norm:
            return norm.index(k)
    return None


def _from_table(rows: list[list]) -> list[tuple[str, str]]:
    rows = [r for r in rows if any(str(c or "").strip() for c in r)]
    if not rows:
        return []
    header = [str(c or "") for c in rows[0]]
    cell = lambda r, i: r[i] if i is not None and i < len(r) else None  # noqa: E731
    text = lambda v: str(v or "").strip()  # noqa: E731

    i_last, i_first, i_user = _find(header, LAST_KEYS), _find(header, FIRST_KEYS), _find(header, USER_KEYS)
    if None not in (i_last, i_first, i_user):          # Last Name, First Name, Username
        i_id = i_user
        name_of = lambda r: " ".join(p for p in (text(cell(r, i_first)), text(cell(r, i_last))) if p)  # noqa: E731
    else:                                              # older layout: Student ID, Name
        i_id, i_name = _find(header, ID_KEYS), _find(header, NAME_KEYS)
        if i_id is None or i_name is None:
            raise ValueError(FORMAT_ERROR)
        name_of = lambda r: text(cell(r, i_name))  # noqa: E731

    out = []
    for r in rows[1:]:
        sid = cell(r, i_id)
        if sid is None or str(sid).strip() == "":
            continue
        if isinstance(sid, float) and sid.is_integer():  # Excel stores IDs as numbers
            sid = int(sid)
        out.append((str(sid).strip(), name_of(r)))
    return out


def parse_roster(data: bytes, filename: str) -> list[tuple[str, str]]:
    """Returns [(student_id, name)]."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        return _from_table([list(r) for r in ws.iter_rows(values_only=True)])
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text.splitlines()[0]) if text.strip() else csv.excel
    return _from_table(list(csv.reader(io.StringIO(text), dialect)))
