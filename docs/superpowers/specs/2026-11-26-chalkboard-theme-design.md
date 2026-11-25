# Chalkboard look

Date: 2026-11-26. Status: waiting for approval.

## Why

The admin finds the site plain and wants more color and character. They picked the "Chalkboard" direction from three
mockups: dark green board, chalk yellow, paper background.

## Goals

- Every page uses the Chalkboard colors: sign-in, accounts, password, courses, course page, QR board, student check-in.
- The things a doctor needs in class stand out: the live count and the "Show QR code" button sit on a green board
  panel, in chalk yellow.
- A "Courses" link in the top bar on every page, plus "← All courses" on the Password and Accounts pages, so there is
  always a visible way back (the problem the admin hit on the Password page).
- Wording stays plain and follows the no-ai-slop rules. Any text that changes gets checked against them.

## Non-goals

- No layout or flow changes beyond the navigation links. Same steps, same buttons, same tests.
- No dark mode, no custom fonts loaded from the internet (classroom Wi-Fi and phones on mobile data).

## Anti-goals

- The QR code must stay black on white with a quiet margin, or phones scan it slower.
- Text contrast must stay readable on a projector and in sunlight on a phone (WCAG AA, 4.5:1 for body text).
- No gradients, glows or decoration that hides the information.

## Approach

One sensible way: change the color tokens in `_base.html` (every page reads them), then give a few elements their own
board style. The other options, such as a CSS framework or a theme switcher, add weight for no gain here.

- **Colors:** board green `#1F3B2D` (darker `#173026` for hover), chalk white `#F5F1E6`, chalk yellow `#F2C14E`,
  paper `#F7F3EA`, card white `#FFFDF8`, ink `#1F2A24`, muted `#5E6B62`, lines `#E4DCCB`. Status pills keep green for
  "Here" and coral for "Not here", in softer chalk tones.
- **Top bar:** board green with chalk text. Links: Courses, Accounts (admins), Password, Sign out.
- **Buttons:** main buttons chalk yellow with green text; secondary buttons white with a green outline.
- **Course page:** step numbers become yellow chalk circles on green. The "during class" panel becomes a green board
  with the big yellow count and the yellow "Show QR code" button.
- **Home:** course cards get a thin board-green top edge; a running class shows a yellow "Class running" tag.
- **Sign-in:** a green board panel above the form with the app name.
- **QR board (projector):** full green board background, title and count in chalk, the QR code on a white card.
- **Student phone page:** green header with the course and class, the hand-sign emoji on a small board panel.

## Left to the builder

Exact spacing, hover states and the small chalk-line details, within the colors above. A browser check at laptop and
phone width before committing.
