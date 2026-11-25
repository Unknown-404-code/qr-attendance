# Hosted Login and Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the laptop attendance app into a hosted, multi-doctor web app with login, an admin page, per-course
student lists the doctor can edit, and clearer pages. It runs free on Hugging Face Spaces with a Supabase database.

**Architecture:** The existing FastAPI app keeps serving pages and running the face and gesture checks. A thin
database adapter lets `Store` run on SQLite (laptop, tests) or Postgres (Supabase, when `DATABASE_URL` is set).
Accounts live in our own `users` table with scrypt-hashed passwords and a signed session cookie. Every course,
student, session and report hangs off a course owned by one user.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLite / Postgres via `psycopg[binary]` 3, openpyxl, vanilla JS,
Docker on Hugging Face Spaces.

**Spec:** `docs/superpowers/specs/2026-11-25-hosted-login-admin-design.md`

## Global Constraints

- Monthly cost $0: Hugging Face Spaces free CPU plan plus Supabase free plan. No paid services.
- `requirements-app.txt` stays torch-free. The only new runtime package is `psycopg[binary]`.
- With `DATABASE_URL` unset, the app uses SQLite at `app.db_path`, and `start.bat` and `pytest` need no cloud account.
- Selfies are never written to disk or the database. Only 512-d embeddings are stored.
- Passwords: `hashlib.scrypt`, n=2**14, r=8, p=1, 16-byte random salt. Minimum length 8.
- Login cookie `ga_user`: signed with the existing `Signer`, httponly, samesite=lax, `secure` when served over
  HTTPS, valid 14 days.
- Login rate limit: 10 failed attempts per email per 15 minutes.
- Selfies are shrunk in the browser to at most 1280 px on the long side, JPEG quality 0.85, before upload.
- Container: Python 3.11, listens on port 7860, runs as uid 1000 (Hugging Face requirements).
- Secrets read from the environment: `DATABASE_URL`, `GA_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
  `ADMIN_RESET_PASSWORD`.
- All user-facing text follows the no-ai-slop rules: short and concrete, no internal codes like
  `shared_device`, no em dashes, no emoji in headings. Gesture emoji are content and stay.
- Work on local branch `hosted-login-admin`. Commit per task. Never push.

## Review Focus

1. **The Supabase pooler drops idle connections between classes.** The first request after hours of quiet should
   still work: the adapter reconnects once and retries. Test in Task 1.
2. **An admin disables a doctor who is signed in.** Their next page load goes to `/login`, and the API returns 401.
   Test in Task 4.
3. **A re-uploaded file contains a student the doctor removed earlier.** The student comes back, with past
   attendance intact. Test in Task 2.
4. **A student picks a HEIC or broken file in the camera fallback.** They get the "couldn't open that photo"
   message and keep their attempt count, not a 500 error. Test in Task 5.
5. **IDs with spaces or leading zeros**, typed by hand (" 00123 ") or from Excel (123.0). They are stored trimmed,
   as text, with leading zeros kept. Test in Task 2.

---

### Task 1: Database adapter (SQLite and Postgres)

**Files:**
- Create: `src/gesture_attendance/app/db.py`
- Modify: `requirements-app.txt`, `requirements.txt`, `pyproject.toml` (add `psycopg[binary]`)
- Test: `tests/test_db.py`, `tests/conftest.py` (add `db_url` fixture)

**Interfaces:**
- Produces:
  - `connect(target: str | Path, schema: str | None = None) -> Database`. A `postgres://` or `postgresql://`
    target gives Postgres, anything else a SQLite path (or `":memory:"`). `schema` sets Postgres `search_path`
    (used by tests).
  - `class Database`: `dialect: str` (`"sqlite"` | `"postgres"`), `q(sql, args=()) -> list[dict]`,
    `one(sql, args=()) -> dict | None`, `x(sql, args=()) -> None`, `insert(sql, args=()) -> int` (SQL must end
    with `RETURNING id`), `script(sql: str) -> None`, `lock: threading.RLock`.
  - SQL is written once with `?` placeholders. The Postgres side rewrites `?` to `%s`.
  - `ddl(sql: str, dialect: str) -> str` replaces `{id}`, `{blob}`, `{real}` with
    `INTEGER PRIMARY KEY AUTOINCREMENT` / `BLOB` / `REAL` (SQLite) or `BIGSERIAL PRIMARY KEY` / `BYTEA` /
    `DOUBLE PRECISION` (Postgres).

- [ ] **Step 1: Create the branch.** `git switch -c hosted-login-admin`
- [ ] **Step 2: Write failing tests** in `tests/test_db.py`, parametrized over a `db_url` fixture: `"sqlite"`
  always, and `"postgres"` only when `GA_TEST_DATABASE_URL` is set (skip otherwise). The Postgres fixture
  creates a throwaway schema `t_<random hex>` and drops it after the test.
  - `test_roundtrip`: `script(ddl("CREATE TABLE t(id {id}, v TEXT, b {blob})", d))`, `insert("INSERT INTO t(v,b) VALUES(?,?) RETURNING id", ("a", b"\x01"))` returns 1, `one("SELECT * FROM t WHERE id=?", (1,))` gives `{"id":1,"v":"a","b":b"\x01"}` (bytes on both backends).
  - `test_update_returning_is_atomic`: `q("UPDATE t SET v='used' WHERE id=? AND v='a' RETURNING *", (1,))` returns one row, and running it again returns `[]`.
  - `test_reconnects_after_drop` (Postgres only): close the underlying connection, then `q("SELECT 1 AS n")` returns `[{"n": 1}]`.
- [ ] **Step 3: Run** `.venv/Scripts/python -m pytest tests/test_db.py -v`. Expected: FAIL (`db` module missing).
- [ ] **Step 4: Implement `db.py`.**
  - SQLite: `check_same_thread=False`, `row_factory` giving dicts, commit after each `x`/`insert`.
  - Postgres: `psycopg.connect(url, autocommit=True, prepare_threshold=None, row_factory=dict_row)`.
    `prepare_threshold=None` is required by Supabase's transaction pooler. Cast `memoryview` results to `bytes`.
  - On `psycopg.OperationalError`, reconnect once and retry. Hold `lock` around every call.
- [ ] **Step 5: Run the tests.** Expected: sqlite PASS, postgres SKIPPED. If you can, start a throwaway local
  Postgres (for example `pip install pgserver` in a scratch venv) and rerun with `GA_TEST_DATABASE_URL` set.
  Expected: all PASS.
- [ ] **Step 6: Commit.** `git commit -m "feat: database adapter for SQLite and Postgres"`

### Task 2: Course-scoped store with users and editable student lists

**Files:**
- Modify: `src/gesture_attendance/app/store.py` (rewrite on top of `db.py`), `src/gesture_attendance/app/report.py`
- Test: `tests/test_store.py` (new, parametrized over `db_url`), `tests/test_roster_report.py`

**Interfaces:**
- Consumes: `connect`, `Database`, `ddl` from Task 1.
- Produces `Store(target: str | Path = ":memory:", schema: str | None = None)` with these methods (anything not
  listed keeps its current name and behavior, now reading `self.db`):
  - Users: `create_user(email, name, role, password_hash) -> int` (email stored lower-case and trimmed; raises
    `ValueError` if taken), `user(uid) -> dict | None`, `user_by_email(email) -> dict | None`,
    `users() -> list[dict]`, `set_password(uid, password_hash)`, `set_active(uid, active: bool)`,
    `count_admins() -> int`.
  - Courses: `create_course(owner_id, name) -> int`, `course(cid) -> dict | None`,
    `courses(owner_id: int | None) -> list[dict]` (`None` = all), `delete_course(cid)` (deletes its students,
    sessions and their challenges, attempts, attendance and flags).
  - Students (all take `course_id` first): `upsert_students(cid, rows) -> int` (adds new students, updates
    names, and clears `removed_at` for students in the file), `students(cid, include_removed=False)`,
    `student(cid, sid)` (`None` if removed), `add_student(cid, sid, name)` (raises `ValueError` if the ID
    exists, removed or not), `update_student(cid, old_sid, new_sid, name)` (raises `ValueError` if `new_sid` is
    taken; moves the row and rewrites `student_id` in `challenges`, `attempts`, `attendance` and `flags` for this
    course's sessions), `remove_student(cid, sid)` (sets `removed_at`), `embedding(cid, sid)`,
    `all_embeddings(cid)`, `set_embedding(cid, sid, emb, status)`, `set_enroll_status(cid, sid, status)`,
    `report_students(cid, session_ids: list[int]) -> list[dict]` (active students, plus removed ones with
    attendance in any of `session_ids`, each with a `removed` bool).
  - Sessions: `start_session(cid, title, enroll_open=False) -> int` (ends only this course's open session),
    `active_session(cid) -> dict | None`, `sessions(cid) -> list[dict]`. `session(id)` now includes `course_id`.
  - Every student ID passing through `upsert_students`, `add_student` or `update_student` is
    `str(x).strip()`. The roster parser already turns Excel's `123.0` into `"123"`.
- Schema changes: new `users(id, email UNIQUE, name, role, password_hash, active INTEGER, created_at)` and
  `courses(id, owner_id, name, created_at)`; `students` gets `course_id` and `removed_at`, primary key
  `(course_id, student_id)`; `sessions` gets `course_id`. `INSERT OR REPLACE` becomes `ON CONFLICT ... DO
  UPDATE`. `COLLATE NOCASE` becomes `ORDER BY lower(name)`. `take_challenge` becomes the single
  `UPDATE ... WHERE id=? AND used=0 RETURNING *`.
- Produces `session_report(store, session_id) -> bytes` (rows from `report_students(course, [session_id])`, with
  "(removed)" appended to removed students' names) and `course_report(store, course_id) -> bytes`.

- [ ] **Step 1: Write failing tests** in `tests/test_store.py`:
  - `test_courses_are_separate`: two courses each with student "1". Marking present in A's session doesn't show up in B's `attendance`.
  - `test_starting_session_ends_only_same_course`: sessions in A and B both stay active. A second start in A ends A's first.
  - `test_add_edit_remove_student`: `add_student(c, " 00123 ", "Ali")` stores `"00123"`. `add_student` with the same ID raises `ValueError`. After a check-in, `update_student(c, "00123", "555", "Ali B")` leaves `attendance(sess)` keyed `"555"` and the embedding readable via `embedding(c, "555")`. `remove_student` hides it from `students(c)` and `student(c, "555")` but not from `report_students(c, [sess])`.
  - `test_reupload_restores_removed`: remove "2", then `upsert_students(c, [("2","Sara")])`. "2" is back in `students(c)` with its old attendance.
  - `test_update_to_taken_id_fails`: raises `ValueError` and changes nothing.
  - `test_delete_course_cascades`: after `delete_course`, `sessions(c) == []` and the attempts and flags tables hold no rows for its sessions.
  - `test_users`: `create_user("A@X.com ", ...)` then `user_by_email("a@x.com")` finds it. A duplicate email raises `ValueError`.
  - Update `tests/test_roster_report.py::test_reports` to create a course first and call `course_report(st, cid)`.
- [ ] **Step 2: Run** `pytest tests/test_store.py tests/test_roster_report.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement the store and report changes** to the interfaces above.
- [ ] **Step 4: Run** the same tests. Expected: PASS. `test_app.py` will fail until Task 5; that is expected here.
- [ ] **Step 5: Commit.** `git commit -m "feat: course-scoped store with users and editable student lists"`

### Task 3: Passwords, login limiter, first admin

**Files:**
- Create: `src/gesture_attendance/app/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `Store` user methods from Task 2.
- Produces:
  - `hash_password(pw: str) -> str` gives `"scrypt$16384$8$1$<salt b64>$<hash b64>"`. Raises `ValueError` if
    `len(pw) < 8`.
  - `verify_password(pw: str, stored: str) -> bool` uses `hmac.compare_digest` and returns `False` on any
    malformed `stored`.
  - `new_password() -> str` gives 12 URL-safe random characters.
  - `class LoginLimiter(max_failures=10, window_s=900, clock=time.time)` with `blocked(email) -> bool`,
    `fail(email)` and `reset(email)`.
  - `ensure_admin(store, email: str | None, password: str | None, reset: bool = False) -> str | None`:
    - If no active admin exists: create one from `email`/`password`. With both missing, use
      `admin@localhost` and a `new_password()`, and return that password so the caller can print it.
    - If `reset` is true and an admin with `email` exists: set its password to `password`.
    - Otherwise do nothing and return `None`.

- [ ] **Step 1: Write failing tests:**
  - `test_hash_roundtrip`: verify succeeds with the right password, fails with a wrong one and with `"garbage"`.
  - `test_short_password_rejected`.
  - `test_limiter`: 10 `fail()` calls make `blocked()` true. Advancing a fake clock 901 s makes it false.
  - `test_ensure_admin_env`: creates the admin once. A second call returns `None` and leaves the password unchanged. With `reset=True` the new password verifies.
  - `test_ensure_admin_generated`: with no env, returns a 12-char password that verifies for `admin@localhost`.
- [ ] **Step 2: Run** `pytest tests/test_auth.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `auth.py`.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: password hashing, login limiter and first admin"`

### Task 4: Login, account and admin pages

**Files:**
- Create: `src/gesture_attendance/app/context.py`, `routes_auth.py`, `routes_admin.py`,
  `templates/login.html`, `templates/admin.html`, `templates/account.html`
- Modify: `src/gesture_attendance/app/main.py` (build the context, include routers, remove the instructor key),
  `templates/_base.html` (header with the user's name, Account and Sign out links, and an Admin link for admins)
- Test: `tests/test_web_auth.py`; shared helpers `make_app(tmp_path)` and `login(client, email, pw)` in
  `tests/helpers.py`

**Interfaces:**
- Consumes: `auth.py` (Task 3), `Store` (Task 2).
- Produces:
  - `@dataclass AppContext(cfg, store, signer, rot, templates, gestures, limiter, get_verifier, vlock, hosted: bool)`.
  - In `context.py`: `current_user(ctx, request) -> dict | None` (unsigns `ga_user`; returns `None` if the user
    is missing or inactive), `require_user(ctx)` and `require_admin(ctx)` (FastAPI dependency factories: JSON
    routes get 401/403, page routes redirect to `/login`), and `owned_course(ctx, user, cid) -> dict` (404
    unless the user owns the course or is an admin).
  - Each `routes_*.py` exposes `register(app: FastAPI, ctx: AppContext) -> None`.
  - `create_app(cfg=None, verifier=None, store=None, hosted: bool | None = None)`. It reads `DATABASE_URL`
    (Postgres store when set). `hosted` defaults to `bool(DATABASE_URL)`. It calls `ensure_admin` with the env
    vars and prints any generated password.
  - Routes:
    - `GET /login`, `POST /login` (form `email`, `password`; on success sets the cookie and goes to `/`; failure
      re-renders with "Email or password is wrong."; when the limiter blocks: "Too many tries. Wait 15 minutes
      and try again.").
    - `POST /logout`, `GET /account`, `POST /api/account/password` (`current`, `new`).
    - `GET /admin`, `GET /api/admin/users`, `POST /api/admin/users` (`name`, `email`, `password` optional, so
      the server generates one; returns `{id, password}`), `POST /api/admin/users/{uid}/password` (returns
      `{password}`), `POST /api/admin/users/{uid}/active` (`active`). Admins can't disable themselves.

- [ ] **Step 1: Write failing tests:**
  - `test_pages_need_login`: `GET /` and `GET /admin` redirect (303) to `/login`. `GET /api/courses` gives 401.
  - `test_login_logout`: a wrong password shows "Email or password is wrong." The right one sets `ga_user` and `GET /` returns 200. After logout, `/` redirects again.
  - `test_rate_limit`: 10 wrong logins, then the right password still fails with the "Too many tries" text.
  - `test_admin_creates_doctor`: the admin posts `{name, email}` and gets a 12-char password. The doctor can log in with it. The doctor's `GET /admin` gives 403 for the API and redirects for the page.
  - `test_disabled_doctor_is_signed_out` (Review Focus 2): the doctor is logged in, the admin disables them, the doctor's `GET /api/courses` gives 401 and `GET /` redirects to `/login`.
  - `test_change_password`: a wrong current password gives 400. After a successful change the new password logs in.
- [ ] **Step 2: Run** `pytest tests/test_web_auth.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the context, the auth and admin routes, and the three templates. Set the cookie's
  `secure` flag when `request.url.scheme == "https"`. Text comes from `texts.py` (create it here with the
  login strings; Task 6 fills in the rest).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: login, account and admin pages"`

### Task 5: Courses, student editing, class sessions and check-in scoped by course

**Files:**
- Create: `src/gesture_attendance/app/routes_doctor.py`, `src/gesture_attendance/app/routes_student.py`
- Modify: `src/gesture_attendance/app/main.py` (move the remaining routes out; `/collect` registered only when
  `not ctx.hosted`), `src/gesture_attendance/app/__main__.py` (print the login URL and any generated admin
  password instead of the key)
- Test: `tests/test_app.py` (port to login and courses), `tests/test_courses.py` (new)

**Interfaces:**
- Consumes: `AppContext`, `require_user`, `owned_course` (Task 4), `Store` (Task 2).
- Produces the routes. All `/api/courses/{cid}/...` routes call `owned_course`, and any `session_id` must belong to `cid` (404 otherwise):
  - `GET/POST /api/courses` (`name`), `POST /api/courses/{cid}/delete` (`confirm_name` must equal the course name, else 400).
  - `POST /api/courses/{cid}/roster` (file), `GET /api/courses/{cid}/students`, `POST /api/courses/{cid}/students`
    (`student_id`, `name`), `POST /api/courses/{cid}/students/{sid}` (`student_id`, `name`),
    `POST /api/courses/{cid}/students/{sid}/remove`. A `ValueError` from the store becomes 400 with its message.
  - `POST /api/courses/{cid}/session/start|end|enroll`, `GET /api/courses/{cid}/stats?session_id=`,
    `GET /api/courses/{cid}/board/state`, `GET /api/courses/{cid}/board/qr.png`,
    `POST /api/courses/{cid}/enrollment/{sid}/{action}`, `POST /api/courses/{cid}/attendance/{sid}`,
    `GET /api/courses/{cid}/report.xlsx?session_id=`, `GET /api/courses/{cid}/course_report.xlsx`.
    These are the same handlers as today, with `course_id` passed to the store.
  - The QR URL becomes `{base}/q/{session_id}/{token}`, and the route `GET /q/{session_id}/{token}` checks
    `rot.verify(session_id, token)` and that the session is still open.
  - The ticket stays `{sid: session_id, dev}`. `ticket()` accepts it only while that session is open. Challenge
    and verify look up students with `store.student(session.course_id, student_id)`, so a removed or unknown ID
    gets 404 "This ID isn't on the class list."
  - Stats flags each carry a `text` field from `texts.flag_text(kind, detail)`.

- [ ] **Step 1: Port `tests/test_app.py`.** The fixture logs in a doctor and creates a course. `phone(app, sess_id)`
  scans `/q/{sess_id}/{token}`. Every existing assertion keeps its meaning with course-scoped URLs.
  `test_requires_instructor_key` becomes `test_other_doctor_gets_404` (doctor B fetching A's stats, board, report
  or student list gets 404).
- [ ] **Step 2: Write failing tests** in `tests/test_courses.py`:
  - `test_qr_is_bound_to_its_course`: courses A and B both have active sessions and student "1". Scanning A's QR and checking in marks "1" present in A only.
  - `test_edit_student_keeps_history`: check in "1", rename it to "11" through the API. Stats for that session show "11" present, and the Excel report lists "11".
  - `test_removed_student_cannot_check_in`: after remove, `/api/challenge` for that ID gives 404. The past session's report still lists them as "(removed)".
  - `test_delete_course_needs_name`: a wrong `confirm_name` gives 400. The right one deletes the course and `GET /api/courses` no longer lists it.
  - `test_bad_image_keeps_attempts` (Review Focus 4): posting `b"not an image"` as the selfie returns reason `bad_image` with `attempts_left == 2`, not a 500.
- [ ] **Step 3: Run** `pytest -q`. Expected: the new tests FAIL.
- [ ] **Step 4: Implement** the two route modules and trim `main.py` to building the context and registering routers.
- [ ] **Step 5: Run** `pytest -q`. Expected: all PASS.
- [ ] **Step 6: Commit.** `git commit -m "feat: courses, editable student lists and course-scoped check-in"`

### Task 6: Clearer pages and wording

**Files:**
- Modify: `src/gesture_attendance/app/texts.py` (all user-facing strings), `templates/_base.html`,
  `templates/board.html`, `templates/checkin.html`, `templates/message.html`, `static/camera.js`,
  `src/gesture_attendance/gestures.py`
- Create: `templates/home.html`, `templates/course.html`. Delete: `templates/instructor.html`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: the routes from Tasks 4 and 5.
- Produces:
  - `texts.MESSAGES: dict[str, str]` (check-in results), `texts.flag_text(kind: str, detail: str) -> str`, and
    `gestures.gesture_parts(name) -> tuple[str, str]` (emoji, plain name). `/api/challenge` also returns
    `emoji` and `name_text`.
  - `SelfieCamera.shrink(blob, maxSide = 1280, quality = 0.85) -> Promise<Blob>` in `camera.js`. It is used for
    both the live capture and the file picker.
  - Page routes: `GET /` (doctor home), `GET /courses/{cid}` (course page), `GET /courses/{cid}/board` (the QR
    board, which opens full-screen).
- Exact copy (`texts.MESSAGES`):
  - `ok`: "You're checked in."
  - `enroll`: "You're checked in. Your instructor will approve your face photo for next time."
  - `no_gesture`: "We couldn't see a hand sign. Hold your hand up next to your face and try again."
  - `wrong_gesture`: "That wasn't the sign we asked for. Try again with the new one."
  - `no_face`: "We couldn't see your face. Face the camera in good light and try again."
  - `face_mismatch`: "This face doesn't match the student saved for this ID. Talk to your instructor if this is wrong."
  - `challenge_expired`: "Time ran out. Try again."
  - `stale_photo`: "That photo is too old. Take a new one with the camera."
  - `bad_image`: "We couldn't open that photo. Take a new one with the camera."
  - Expired link page: title "Scan the code again", text "This link has expired. Scan the QR code on the board."
- `flag_text` returns:
  - `shared_device`: "Same phone used for another student" followed by " (IDs)" from `detail`.
  - `duplicate_face`: "Face looks like another student's".
  - `face_mismatch`: "Face didn't match the saved photo".
  - `max_attempts`: "Used all tries".
  - `repeat_attempts`: "Failed more than once".
  - `stale_photo`: "Sent an old photo".
  - Unknown kinds: the kind with underscores replaced by spaces.
- Layouts (from the spec, "Pages"):
  - Home: course cards plus a "New course" button. A card shows "Class running: N checked in" while a
    session is open, and its student count otherwise. Admins also see an "Accounts" link.
  - Course page, in this order:
    1. Students: open with an upload area when the list is empty. Otherwise a collapsed "Students (N)" section
       holding an add form, inline edit, remove with confirm, and re-upload.
    2. Start class: optional title, a "Let new students register their face" checkbox, and Start.
    3. During class: a big "Show QR code" button, the live count, the student list with Mark present / absent,
       an approvals badge, and flags as sentences.
    4. After class: End class, plus "Download this class" and "Download all classes".
    - Attempts log and timing go in a closed `<details>` "Details" element.
  - Board: "Scan to check in", the QR as large as the screen allows, the countdown bar and the count.
  - Check-in: steps 1 ID, 2 Sign, 3 Done; the gesture emoji at 5rem with its name below; full-width buttons.
  - Every page works at 375 px wide.

- [ ] **Step 1: Write failing tests** in `tests/test_pages.py`:
  - `test_home_and_course_pages_render` for a logged-in doctor: the course page with an empty list contains "Upload"; with students it contains "Students (2)".
  - `test_no_internal_codes_in_stats_text`: after a `shared_device` flag, the stats flag `text` starts with "Same phone used" and contains no underscore.
  - `test_messages_follow_copy_rules`: no `MESSAGES` value contains "—", "_" or a word from the no-ai-slop banned list.
  - `test_challenge_returns_emoji`: `/api/challenge` JSON has non-empty `emoji` and `name_text`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the texts, templates and camera shrink.
- [ ] **Step 4: Run** `pytest -q`. Expected: all PASS.
- [ ] **Step 5: Check it in the browser.** Start `scripts/run_app.py --port 8000` and use the built-in browser
  pane. Walk through: log in as admin, create a doctor, log in as the doctor, create a course, upload
  `examples/roster_example.csv`, add, edit and remove a student, start a class, open the board, and do a test
  check-in with a demo photo through the API. Take screenshots at desktop width and at 375 px. Fix anything that
  overflows or reads badly.
- [ ] **Step 6: Commit.** `git commit -m "feat: clearer doctor, board and student pages"`

### Task 7: Hosting on Hugging Face Spaces with Supabase

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `scripts/deploy_space.py`, `DEPLOY.md`
- Modify: `src/gesture_attendance/app/__main__.py` (`--hosted` flag), `README.md` (hosted section, login replaces
  key), `start.bat` (unchanged behavior; refresh the `installed.ok` check so `psycopg` gets installed)
- Test: `tests/test_hosted.py`

**Interfaces:**
- Consumes: `create_app` (Task 4).
- Produces:
  - `run_app.py --hosted`: no LAN `base_url`, no tunnel, no browser. Runs uvicorn with `proxy_headers=True`,
    `forwarded_allow_ips="*"`, on `--host 0.0.0.0 --port 7860`. Exits with a clear message if `DATABASE_URL` or
    `GA_SECRET` is missing.
  - `Dockerfile`: `python:3.11-slim`; apt `libgl1 libglib2.0-0`; a uid 1000 user; `pip install -r
    requirements-app.txt`; `ENV PYTHONPATH=/app/src GA_CACHE_DIR=/app/model-cache`. Models download at build
    time with `RUN python -c "from gesture_attendance.config import load_config; from gesture_attendance.verify
    import build_verifier; build_verifier(load_config())"`. `EXPOSE 7860`, `CMD python scripts/run_app.py
    --hosted --preload`.
  - `scripts/deploy_space.py --space <user>/<name>`: uploads `Dockerfile`, `requirements-app.txt`, `configs/`,
    `scripts/run_app.py`, `scripts/_common.py` and `src/` with `huggingface_hub.upload_folder`. It also uploads a
    Space `README.md` with front matter `sdk: docker`, `app_port: 7860`. The user runs it after
    `huggingface-cli login` (Claude never handles the token).
  - `DEPLOY.md`, numbered steps for a first-time user:
    1. Create a Supabase project and copy the **Session pooler** connection string (Connect → Session pooler).
    2. Create a Hugging Face Space (Docker, blank, public).
    3. Add the secrets `DATABASE_URL`, `GA_SECRET` (any 40 random characters), `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
    4. Run `deploy_space.py`.
    5. Open `https://<user>-<name>.hf.space` directly, not the huggingface.co page (the embedded frame breaks
       cookies and the camera), and sign in.
    6. Create the doctor's account.
    - Also: before class, open the site 2 minutes early (sleep after 48 h). Restore a paused Supabase project
      from its dashboard. To recover the admin password, set `ADMIN_RESET_PASSWORD=1`, restart, then remove it.

- [ ] **Step 1: Write failing tests** in `tests/test_hosted.py`:
  - `test_hosted_requires_secrets`: `main(["--hosted"])` with the env cleared exits non-zero and the message names `DATABASE_URL`.
  - `test_collect_hidden_when_hosted`: an app built with `hosted=True` returns 404 for `/collect`.
  - `test_secure_cookie_over_https`: logging in through a `TestClient(base_url="https://testserver")` sets `ga_user` with `Secure`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the flag, Dockerfile, deploy script, `DEPLOY.md` and README changes. `main()` takes an
  optional `argv` for the test.
- [ ] **Step 4: Run** `pytest -q`. Expected: all PASS.
- [ ] **Step 5: Smoke-test hosted mode locally** against the throwaway Postgres from Task 1 if one is available:
  `DATABASE_URL=... GA_SECRET=x ADMIN_EMAIL=a@b.c ADMIN_PASSWORD=... python scripts/run_app.py --hosted
  --port 7860`, then log in and run one check-in. Docker isn't installed on this machine, so the image is first
  built on Hugging Face during the deploy session with the user.
- [ ] **Step 6: Commit.** `git commit -m "feat: hosted mode, Dockerfile and deploy guide"`
