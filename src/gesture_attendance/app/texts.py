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
