"""Shared app state and the login checks every route module uses."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from .auth import LoginLimiter
from .store import Store
from .tokens import RotatingToken, Signer

USER_COOKIE = "ga_user"
USER_TTL_S = 14 * 86400


class LoginRedirect(Exception):
    """Raised by page routes; turned into a redirect by the app's exception handler."""

    def __init__(self, to: str = "/login"):
        self.to = to


@dataclass
class AppContext:
    cfg: dict
    store: Store
    signer: Signer
    rot: RotatingToken
    templates: Jinja2Templates
    gestures: list[str]
    limiter: LoginLimiter
    get_verifier: Callable[[], Any]
    vlock: threading.Lock = field(default_factory=threading.Lock)
    hosted: bool = False

    def render(self, request: Request, name: str, status_code: int = 200, **ctx):
        user = current_user(self, request)
        return self.templates.TemplateResponse(request, name, {"user": user, "hosted": self.hosted, **ctx},
                                               status_code=status_code)


def current_user(ctx: AppContext, request: Request) -> dict | None:
    data = ctx.signer.unsign(request.cookies.get(USER_COOKIE))
    if not data or "uid" not in data:
        return None
    u = ctx.store.user(int(data["uid"]))
    if not u or not u["active"]:
        return None
    return u


def require_user(ctx: AppContext, page: bool = False):
    def dep(request: Request) -> dict:
        u = current_user(ctx, request)
        if u is None:
            if page:
                raise LoginRedirect("/login")
            raise HTTPException(401, "Please sign in again.")
        return u
    return dep


def require_admin(ctx: AppContext, page: bool = False):
    inner = require_user(ctx, page)

    def dep(request: Request) -> dict:
        u = inner(request)
        if u["role"] != "admin":
            if page:
                raise LoginRedirect("/")
            raise HTTPException(403, "Only admins can do this.")
        return u
    return dep


def owned_course(ctx: AppContext, user: dict, cid: int) -> dict:
    c = ctx.store.course(cid)
    if c is None or (c["owner_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "Course not found.")
    return c


def set_login_cookie(ctx: AppContext, request: Request, response, uid: int):
    response.set_cookie(USER_COOKIE, ctx.signer.sign({"uid": uid}, USER_TTL_S), httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", max_age=USER_TTL_S)
