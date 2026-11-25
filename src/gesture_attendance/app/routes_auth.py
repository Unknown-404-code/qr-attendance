"""Sign in, sign out, change your own password."""
from __future__ import annotations

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import texts
from .auth import hash_password, verify_password
from .context import USER_COOKIE, AppContext, current_user, require_user, set_login_cookie


def register(app: FastAPI, ctx: AppContext) -> None:
    @app.get("/login")
    def login_page(request: Request):
        if current_user(ctx, request):
            return RedirectResponse("/", status_code=303)
        return ctx.render(request, "login.html", error=None, email="")

    @app.post("/login")
    def login(request: Request, email: str = Form(""), password: str = Form("")):
        email = email.strip().lower()
        if ctx.limiter.blocked(email):
            return ctx.render(request, "login.html", status_code=429, error=texts.LOGIN_BLOCKED, email=email)
        u = ctx.store.user_by_email(email) if email else None
        if not u or not u["active"] or not verify_password(password, u["password_hash"]):
            ctx.limiter.fail(email)
            return ctx.render(request, "login.html", status_code=401, error=texts.LOGIN_WRONG, email=email)
        ctx.limiter.reset(email)
        resp = RedirectResponse("/", status_code=303)
        set_login_cookie(ctx, request, resp, u["id"])
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(USER_COOKIE)
        return resp

    @app.get("/account")
    def account(request: Request, user: dict = Depends(require_user(ctx, page=True))):
        return ctx.render(request, "account.html")

    @app.post("/api/account/password")
    def change_password(current: str = Form(...), new: str = Form(...), user: dict = Depends(require_user(ctx))):
        if not verify_password(current, user["password_hash"]):
            raise HTTPException(400, texts.CURRENT_PASSWORD_WRONG)
        try:
            ctx.store.set_password(user["id"], hash_password(new))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}
