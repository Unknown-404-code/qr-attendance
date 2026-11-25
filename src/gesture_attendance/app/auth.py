"""Accounts: password hashing (stdlib scrypt), a login rate limiter, and creating the first admin."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from typing import Callable

N, R, P = 2 ** 14, 8, 1
MIN_LENGTH = 8


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(pw: str) -> str:
    if len(pw) < MIN_LENGTH:
        raise ValueError(f"Use at least {MIN_LENGTH} characters.")
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=N, r=R, p=P)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(h)}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(got, base64.b64decode(h))
    except Exception:
        return False


def new_password() -> str:
    return secrets.token_urlsafe(9)  # 12 characters


class LoginLimiter:
    """At most `max_failures` failed logins per email within `window_s` seconds (kept in memory)."""

    def __init__(self, max_failures: int = 10, window_s: float = 900, clock: Callable[[], float] = time.time):
        self.max_failures, self.window_s, self.clock = max_failures, window_s, clock
        self.failures: dict[str, list[float]] = defaultdict(list)

    def _recent(self, email: str) -> list[float]:
        key = email.strip().lower()
        cutoff = self.clock() - self.window_s
        self.failures[key] = [t for t in self.failures[key] if t > cutoff]
        return self.failures[key]

    def blocked(self, email: str) -> bool:
        return len(self._recent(email)) >= self.max_failures

    def fail(self, email: str):
        self._recent(email).append(self.clock())

    def reset(self, email: str):
        self.failures.pop(email.strip().lower(), None)


def ensure_admin(store, email: str | None, password: str | None, reset: bool = False) -> str | None:
    """Create the first admin if none is active. Returns a generated password when it had to make one up."""
    if reset and email and password:
        u = store.user_by_email(email)
        if u and u["role"] == "admin":
            store.set_password(u["id"], hash_password(password))
            store.set_active(u["id"], True)
            return None
    if store.count_admins() > 0:
        return None
    generated = None
    if not (email and password):
        email, password = email or "admin@localhost", new_password()
        generated = password
    existing = store.user_by_email(email)
    if existing:  # an inactive admin with this email: switch it back on with the new password
        store.set_password(existing["id"], hash_password(password))
        store.set_active(existing["id"], True)
    else:
        store.create_user(email, "Admin", "admin", hash_password(password))
    return generated
