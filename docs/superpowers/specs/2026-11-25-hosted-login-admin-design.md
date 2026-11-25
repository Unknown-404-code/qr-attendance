# Hosted version with login and admin page

Date: 2026-11-25. Status: draft, waiting for approval.

## Why

The app runs on a laptop today, and the instructor opens the dashboard with a shared key in the URL. Our doctor
needs to take attendance in class from a normal web address, sign in with their own account, and not depend on
our laptops. One doctor uses it now. More may join later, so each doctor's data must stay separate from the start.

## Goals

- One public HTTPS address that works on any phone, with a live camera preview.
- A login page. Accounts are email + password.
- An admin page where the admin creates doctor accounts, resets their passwords and disables them.
- Each doctor sees only their own courses, rosters, sessions and reports.
- Clearer pages for the doctor, the projected QR board and the student, with plain-language text.
- Costs $0 a month.
- Easy to keep running: one service to deploy, one database.

## Non-goals

- Student accounts. Students still scan, type their ID and take a selfie.
- Changing the face or gesture models, thresholds, or the research scripts.
- Email (password-reset emails, invitations). The admin resets passwords from the admin page.
- Arabic interface. Can come later.

## Anti-goals

- Moving face or gesture checking onto the student's phone. A student could fake the result.
- Storing selfies. Only face embeddings are stored, as today.
- Breaking the laptop setup. `start.bat` and the tests keep working without any cloud account.

## Constraints

- **Vercel and Supabase can't run the checking code.** It needs about 380 MB of Python packages (OpenCV,
  MediaPipe, onnxruntime). Vercel's Python functions allow about 250 MB and reject uploads over 4.5 MB.
  Supabase functions only run JavaScript and TypeScript.
- **Free hosts with enough memory are few.** Render's free plan has 512 MB of RAM, which is too little for the
  models. Hugging Face Spaces' free plan has 2 CPUs and 16 GB of RAM.
- **Hugging Face Spaces loses its disk on every restart**, so the database must live elsewhere.
- **Supabase's free database is reachable from Hugging Face only through its connection pooler.** The direct
  connection is IPv6-only.

## Approaches considered

1. **Pages on Vercel, data on Supabase, checking on a Python server.** Three services to deploy and keep in sync,
   with a proxy between Vercel and the Python server.
2. **One Python server for everything on Hugging Face Spaces, database on Supabase.** Chosen. One deploy, $0,
   and the existing FastAPI app already serves the pages. The address is `https://<name>.hf.space` instead of a
   Vercel address.
3. **Everything on Vercel and Supabase, checking on the phone.** Ruled out: a student could fake the check.

The admin asked for the option that is easiest to build and maintain and costs $0, so approach 2 is my call.

## Design

### Hosting

- A `Dockerfile` at the repo root builds the app with `requirements-app.txt` (no torch). It downloads the three
  model files at build time, so the first check-in after a restart doesn't wait on downloads. It listens on port
  7860, as Hugging Face expects.
- The Space must be public so students can open it without a Hugging Face login. The code is already public on
  GitHub. Secrets go in the Space's secret settings, not in the code.
- Secrets: `DATABASE_URL` (Supabase pooler string), `GA_SECRET` (signs cookies and QR tokens),
  `ADMIN_EMAIL` and `ADMIN_PASSWORD` (the first admin account, created on first start if no admin exists).
- **Sleep:** a free Space sleeps after 48 hours without visitors and takes 1–2 minutes to wake. The doctor opens
  the site a few minutes before class. Supabase's free database pauses after 7 days without use; during long
  breaks someone restores it from the Supabase dashboard (one click). The README says both plainly.

### Database

- `Store` gets two backends behind the same methods: SQLite when `DATABASE_URL` is unset (laptop, tests), and
  Postgres when it is set. The SQL differences (placeholders, auto-increment ids, upserts, blob type) live in a
  thin adapter, not spread across the app.
- New tables:
  - `users(id, email unique, name, role 'admin'|'doctor', password_hash, active, created_at)`
  - `courses(id, owner_id → users, name, created_at)`
- Changed tables: `students` keys on `(course_id, student_id)`, the face embedding stays on that row, and a new
  `removed_at` column hides removed students without deleting their history. A
  student in two courses enrolls once per course. `sessions` gets `course_id`. `challenges`, `attempts`,
  `attendance` and `flags` already key on `session_id`, so they inherit the course.
- Each course can have one active session. Several doctors can run sessions at the same time.
- Existing laptop data in SQLite is not migrated. The current database holds only test data.

### Login and accounts

- The app keeps its own accounts table rather than Supabase Auth. Supabase Auth would add a second login system
  and its email settings for no gain here. Supabase is used only as the database.
- Passwords are hashed with `hashlib.scrypt` from the Python standard library, so no new package is needed.
- After login the server sets a signed, httponly session cookie (the existing `Signer`), valid 14 days.
- Login attempts are limited to 10 per email per 15 minutes.
- The `?key=` instructor key goes away. Every doctor page and API requires a logged-in user, and each request
  checks that the course or session belongs to that user. Admins can open any course.
- Users change their own password from an account menu.

### Pages

Shared look: one header with the app name, the signed-in user's name and a sign-out link. Large tap targets.
Works on a phone as well as a laptop.

- **`/login`**: email, password, Sign in. Wrong details give one message: "Email or password is wrong."
- **`/admin`** (admins only): a list of accounts with name, email, role and status. A form to add a doctor:
  name, email and a temporary password, which the app can generate. Buttons to reset a password and to
  disable or enable an account.
- **`/` (doctor home)**: the doctor's courses as cards, each showing today's session if one is running. A
  "New course" button.
- **Course page**, laid out as the steps the doctor follows in class:
  1. *Students*: the doctor uploads the roster (CSV or Excel) once per course, and it stays for the whole
     semester. With no roster yet, this is the only step shown. Once a roster exists, this step folds into a
     "Students (42)" section, so a normal class day starts at step 2. In that section the doctor can:
     - add one student by hand (ID and name);
     - edit a student's name or ID (an ID change carries over that student's attendance and face enrollment);
     - remove a student, after confirming. A removed student no longer appears in new classes or on the student
       list, but stays in the Excel reports for classes they already attended;
     - re-upload a file, which adds new students and updates names without touching anyone else.
     Every change applies to all later classes in the course.
  2. *Start class*: title (optional), "Let new students register their face" (replaces "open enrollment"),
     Start.
  3. *During class*: a big "Show QR code" button that opens the board full-screen, the count of checked-in
     students, the student list with present/absent, and Mark present / Mark absent buttons.
  4. *After class*: End class and Download Excel.
  - Flags show as plain sentences, for example "Same phone used for 202100002" instead of `shared_device`.
  - The attempts log and timing go under a collapsed "Details" section.
  - Pending face enrollments show a small badge with Approve / Reject.
- **Board**: QR code as large as the screen allows, "Scan to check in" above it, the count below, and a thin bar
  showing when the code changes.
- **Student check-in**: a step indicator (1 ID, 2 gesture, 3 done). The gesture shows as a large picture and
  its name. Bigger buttons, and clearer failures that say what to do next. The browser shrinks the selfie to at
  most 1280 px before upload.
- All user-facing text follows the no-ai-slop rules: short, concrete, no internal codes.

### What stays the same

- Rotating QR, tickets, challenges, attempt limits, EXIF age check, face threshold, Excel reports.
- `start.bat` and `python scripts/run_app.py`. Locally, the app creates the admin from `ADMIN_EMAIL` and
  `ADMIN_PASSWORD` if set. Otherwise it prints a one-time admin password to the console on first start.
- `/collect` (research data collection) keeps working on the laptop. It is hidden when `DATABASE_URL` is set,
  because Hugging Face's disk is wiped on restart.

### Testing

- Existing tests keep passing, adapted to log in instead of using the key.
- New tests: login and logout, wrong password, rate limit, admin creates a doctor, a doctor can't open another
  doctor's course or session, adding, editing (including an ID change) and removing a student keeps past
  attendance correct, two courses with active sessions at once, scanning a QR code from course A doesn't
  check a student into course B.
- The Postgres backend is tested against a real Supabase project before deploy (manual, with the admin).

### Deployment help

A `DEPLOY.md` with numbered steps, written for someone who hasn't used either service:

1. Create the Supabase project and copy the pooler connection string.
2. Create the Hugging Face Space (Docker type) and add the four secrets.
3. Push the code to the Space.
4. Sign in as admin and create the doctor's account.

I'll walk through each step with the admin in a session.

## Calls made during review (my calls, easy to change)

- Doctors and admins can create courses. A course can be deleted only after typing its name to confirm.
- Re-uploading a roster adds new students and updates names. It never deletes students or their attendance.
- Both Excel reports ("this class" and "all classes") are per course.

## Left to the builder

- Exact Postgres adapter shape, and whether to use `psycopg` directly (preferred, small) or SQLAlchemy.
- How the QR token carries the session id, now that several sessions can be active at once.
- Visual details: colors, spacing, icons and gesture pictures (inline SVG or emoji), within the layout above.
