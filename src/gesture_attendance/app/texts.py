"""Every sentence a doctor or student reads, in one place."""
from __future__ import annotations

FLAG_TEXT = {
    "shared_device": "Same phone used for another student",
    "duplicate_face": "Face looks like another student's",
    "face_mismatch": "Face didn't match the saved photo",
    "max_attempts": "Used all tries",
    "repeat_attempts": "Failed more than once",
    "stale_photo": "Sent an old photo",
}


def flag_text(kind: str, detail: str = "") -> str:
    text = FLAG_TEXT.get(kind, kind.replace("_", " "))
    if kind == "shared_device" and detail:
        ids = detail.rsplit(" for ", 1)[-1]
        text += f" ({ids})"
    return text

LOGIN_WRONG = "Email or password is wrong."
LOGIN_BLOCKED = "Too many tries. Wait 15 minutes and try again."
CURRENT_PASSWORD_WRONG = "Your current password is wrong."

# check-in results shown to the student
MESSAGES = {
    "ok": "You're checked in.",
    "enroll": "You're checked in. Your instructor will approve your face photo for next time.",
    "no_gesture": "We couldn't see a hand sign. Hold your hand up next to your face and try again.",
    "wrong_gesture": "That wasn't the sign we asked for. Try again with the new one.",
    "no_face": "We couldn't see your face. Face the camera in good light and try again.",
    "face_mismatch": "This face doesn't match the student saved for this ID. Talk to your instructor if this is wrong.",
    "challenge_expired": "Time ran out. Try again.",
    "stale_photo": "That photo is too old. Take a new one with the camera.",
    "bad_image": "We couldn't open that photo. Take a new one with the camera.",
}

EXPIRED_TITLE = "Scan the code again"
EXPIRED_TEXT = "This link has expired. Scan the QR code on the board."
NOT_ON_LIST = "This ID isn't on the class list. Check the number, or ask your instructor to add you."
NO_TRIES_LEFT = "You've used all your tries. Ask your instructor to mark you present."
NOT_ENROLLED = "Your face isn't registered yet. Ask your instructor to let new students register."
CHALLENGE_USED = "This sign was already used. Ask for a new one."
PHOTO_TOO_BIG = "That photo is too large. Take a new one with the camera."
