# Chalkboard Look Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-color every page in the Chalkboard look and add a visible way back to the courses from every page.

**Architecture:** All pages extend `templates/_base.html`, whose `:root` CSS variables set every color. Task 1 swaps
the variables and the top bar; Tasks 2-3 give individual pages their board panels. Server code doesn't change.

**Tech Stack:** Jinja2 templates, plain CSS, pytest with FastAPI's TestClient.

**Spec:** `docs/superpowers/specs/2026-11-26-chalkboard-theme-design.md`

## Global Constraints

- Colors (exact): board `#1F3B2D`, board hover `#173026`, chalk white `#F5F1E6`, chalk yellow `#F2C14E`,
  paper `#F7F3EA`, card `#FFFDF8`, ink `#1F2A24`, muted `#5E6B62`, lines `#E4DCCB`.
- Body text contrast at least 4.5:1 (WCAG AA) for every text/background pair in the theme.
- QR code stays black on white with its white margin.
- No gradients, glows, web fonts or new packages. No layout or flow changes beyond the navigation links.
- Any new or changed text follows the no-ai-slop rules (no em dashes, no internal codes, plain words).
- Work on branch `chalkboard-theme`; commit per task; never push.

## Review Focus

1. **Projected board in a bright room:** chalk text on green must stay readable. Pinned by `test_theme_contrast` (Task 1).
2. **Pending-approval box and flag text** still read on the new paper background: covered by the same contrast test
   (warn text on warn background).
3. **Long course names** in the top bar and board title wrap instead of overflowing at 375 px: checked in the
   Task 4 browser pass (`scrollWidth == innerWidth`).
4. **Signed-out pages** (login, student check-in, expired link) show no Courses link: `test_nav_links` asserts it.
5. **Hidden elements** stay hidden after restyling (`[hidden]` rule kept): `test_hidden_rule_kept` (Task 1).

---

### Task 1: Colors, top bar and the way back

**Files:**
- Modify: `src/gesture_attendance/app/templates/_base.html`, `templates/account.html`, `templates/admin.html`
- Test: `tests/test_theme.py` (new)

**Interfaces:**
- Produces CSS variables used by later tasks: `--board`, `--board-hover`, `--chalk`, `--chalk-yellow`, `--paper`,
  `--card`, `--ink`, `--muted`, `--line`, and the existing role names (`--ok`, `--okbg`, `--bad`, `--badbg`,
  `--warn`, `--warnbg`, `--accent`) re-pointed to Chalkboard values.
- Produces CSS classes: `.board` (green panel, chalk text), `.chalk-num` (yellow circle with green text, used for
  step numbers), `.back` (back link).

- [ ] **Step 1: Branch.** `git switch -c chalkboard-theme` and commit the spec and this plan.
- [ ] **Step 2: Write failing tests** in `tests/test_theme.py`:
  - `test_theme_colors`: parse `:root{...}` from `_base.html`; assert `--board: #1F3B2D`, `--chalk-yellow: #F2C14E`,
    `--paper: #F7F3EA` are present.
  - `test_theme_contrast`: for pairs (ink on paper), (ink on card), (muted on card), (chalk on board),
    (chalk-yellow on board), (board on chalk-yellow), (ok on okbg), (bad on badbg), (warn on warnbg), compute the
    WCAG contrast ratio from the parsed hex values and assert each is at least 4.5.
  - `test_hidden_rule_kept`: `[hidden] { display:none !important; }` is still in `_base.html`.
  - `test_nav_links`: for a signed-in doctor, `/`, `/account` and a course page each contain `href="/"` with the
    text "Courses"; `/account` and admin `/admin` contain "All courses". `/login` and `/checkin` (expired) contain
    no "Courses" link.
- [ ] **Step 3: Run** `.venv/Scripts/python -m pytest tests/test_theme.py -q`. Expected: FAIL (variables and links missing).
- [ ] **Step 4: Implement** the new `:root` variables and role values, a board-green top bar with chalk text and a
  "Courses" link first in the nav, yellow primary buttons with board-green text, white secondary buttons with a
  green outline, `.board`, `.chalk-num`, `.back`, and "← All courses" links at the top of `account.html` and
  `admin.html`.
- [ ] **Step 5: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit.** `git commit -m "style: chalkboard colors, top bar and Courses link"`

### Task 2: Sign-in, home and course page

**Files:**
- Modify: `templates/login.html`, `templates/home.html`, `templates/course.html`
- Test: `tests/test_theme.py`

**Interfaces:**
- Consumes: `.board`, `.chalk-num` and the variables from Task 1.

- [ ] **Step 1: Write failing tests:**
  - `test_course_live_panel_is_board`: the course page HTML has `id="live-box"` with class `board`, and step numbers
    use class `chalk-num`.
  - `test_home_running_tag`: with a class running, `/` contains `class="live-tag"` and the text "Class running".
  - `test_login_board_hero`: `/login` contains `class="board login-hero"`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Login: a board panel with the app name and its one-line description above the form.
  Home: cards with a 4 px board-green top edge; running class shows a yellow `live-tag` "Class running: N checked
  in". Course page: step numbers use `.chalk-num`; the during-class section becomes a `.board` panel holding the
  title, the big chalk-yellow count and the yellow "Show QR code" button; the student table inside stays on a card
  so rows read as before.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "style: chalkboard sign-in, home and course page"`

### Task 3: QR board and student phone page

**Files:**
- Modify: `templates/board.html`, `templates/checkin.html`, `templates/message.html`
- Test: `tests/test_theme.py`

- [ ] **Step 1: Write failing tests:**
  - `test_qr_board_chalk`: the board page contains `class="chalk-page"` on the wrapper and `id="qr-card"` around
    the QR image.
  - `test_checkin_board_header`: the student page contains `class="board checkin-head"` with the course name.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Board: full board-green page, course and title in chalk, "Scan to check in" in chalk
  yellow, the QR inside a white `#qr-card` with 16 px white padding, chalk count, yellow countdown bar. Check-in: a
  board header with course and class, step bar in chalk yellow, the hand-sign emoji on a small board panel.
  Message page: a board panel around the title and message.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "style: chalkboard QR board and student page"`

### Task 4: Look at it

- [ ] **Step 1:** With the demo server running, screenshot sign-in, home, course page (class running), QR board,
  accounts, password and the student page at desktop width and at 375 px. On each, run
  `document.documentElement.scrollWidth === innerWidth` (Review Focus 3).
- [ ] **Step 2:** Fix anything that overflows, reads badly or looks broken; rerun `pytest -q`.
- [ ] **Step 3: Commit** any fixes: `git commit -m "style: chalkboard fixes from browser check"`
