import io

from openpyxl import Workbook, load_workbook

from gesture_attendance.app.report import course_report, session_report
from gesture_attendance.app.roster import parse_roster
from gesture_attendance.app.store import Store


def test_parse_csv_variants():
    assert parse_roster(b"Student ID,Full Name\n2021001,Ali A\n2021002,Sara B\n", "r.csv") == \
        [("2021001", "Ali A"), ("2021002", "Sara B")]
    assert parse_roster("name;id\nX;1\n".encode(), "r.csv") == [("1", "X")]


def test_parse_xlsx_numeric_ids():
    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "Student_ID"])
    ws.append(["Ali", 202100123])
    buf = io.BytesIO()
    wb.save(buf)
    assert parse_roster(buf.getvalue(), "r.xlsx") == [("202100123", "Ali")]


def test_reports():
    st = Store()
    cid = st.create_course(st.create_user("d@x.com", "Dr", "doctor", "h"), "CV")
    st.upsert_students(cid, [("1", "Ali"), ("2", "Sara"), ("3", "Omar")])
    sid = st.start_session(cid, "L1")
    st.mark_present(sid, "3")
    st.remove_student(cid, "3")
    st.mark_present(sid, "1", face_sim=0.7)
    st.flag(sid, "2", "max_attempts", "x")
    wb = load_workbook(io.BytesIO(session_report(st, sid)))
    rows = list(wb["Attendance"].iter_rows(values_only=True))
    assert rows[0][:4] == ("No.", "Student ID", "Name", "Status")
    status = {r[1]: r[3] for r in rows[1:]}
    assert status == {"1": "Present", "2": "Not present", "3": "Present"}
    names = {r[1]: r[2] for r in rows[1:]}
    assert names["3"] == "Omar (removed)"
    assert "Used all tries" in {r[1]: r[7] for r in rows[1:]}["2"]
    wb2 = load_workbook(io.BytesIO(course_report(st, cid)))
    rows2 = {r[0]: r for r in list(wb2.active.iter_rows(values_only=True))[1:]}
    assert rows2["1"][2] == "P" and rows2["3"][1] == "Omar (removed)"


def test_parse_last_first_username_csv():
    data = b"Last Name,First Name,Username\nHassan,Ali,202100001\n Khalid , Sara , 00123 \n"
    assert parse_roster(data, "r.csv") == [("202100001", "Ali Hassan"), ("00123", "Sara Khalid")]


def test_parse_last_first_username_xlsx_numeric_ids():
    wb = Workbook()
    ws = wb.active
    ws.append(["Last Name", "First Name", "Username"])
    ws.append(["Yousef", "Omar", 202100003])
    ws.append(["Saeed", None, 202100004])          # missing first name: keep what's there
    buf = io.BytesIO()
    wb.save(buf)
    assert parse_roster(buf.getvalue(), "r.xlsx") == [("202100003", "Omar Yousef"), ("202100004", "Saeed")]


def test_old_layout_still_works():
    assert parse_roster(b"Student ID,Name\n1,Ali Hassan\n", "r.csv") == [("1", "Ali Hassan")]


def test_unknown_header_names_the_expected_columns():
    import pytest
    with pytest.raises(ValueError, match="Last Name, First Name, Username"):
        parse_roster(b"Surname only,Foo\nx,y\n", "r.csv")


def test_example_roster_uses_new_layout():
    from pathlib import Path
    data = (Path(__file__).resolve().parents[1] / "examples/roster_example.csv").read_bytes()
    assert data.decode("utf-8-sig").splitlines()[0] == "Last Name,First Name,Username"
    assert parse_roster(data, "roster_example.csv")[0] == ("202100001", "Ali Hassan")
