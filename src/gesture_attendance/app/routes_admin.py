"""Admin page: create doctor accounts, reset their passwords, switch accounts off and on."""
from __future__ import annotations

from fastapi import Depends, FastAPI, Form, HTTPException, Request

from .auth import hash_password, new_password
from .context import AppContext, require_admin


def register(app: FastAPI, ctx: AppContext) -> None:
    admin_page, admin_api = require_admin(ctx, page=True), require_admin(ctx)

    @app.get("/admin")
    def admin(request: Request, user: dict = Depends(admin_page)):
        return ctx.render(request, "admin.html", users=ctx.store.users())

    @app.get("/api/admin/users")
    def users(user: dict = Depends(admin_api)):
        return ctx.store.users()

    @app.post("/api/admin/users")
    def create(name: str = Form(...), email: str = Form(...), password: str = Form(""),
               user: dict = Depends(admin_api)):
        if not name.strip() or "@" not in email:
            raise HTTPException(400, "Enter a name and an email address.")
        password = password.strip() or new_password()
        try:
            uid = ctx.store.create_user(email, name, "doctor", hash_password(password))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": uid, "password": password}

    def target(uid: int) -> dict:
        u = ctx.store.user(uid)
        if u is None:
            raise HTTPException(404, "Account not found.")
        return u

    @app.post("/api/admin/users/{uid}/password")
    def reset_password(uid: int, password: str = Form(""), user: dict = Depends(admin_api)):
        target(uid)
        password = password.strip() or new_password()
        try:
            ctx.store.set_password(uid, hash_password(password))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"password": password}

    @app.post("/api/admin/users/{uid}/active")
    def set_active(uid: int, active: bool = Form(...), user: dict = Depends(admin_api)):
        target(uid)
        if uid == user["id"] and not active:
            raise HTTPException(400, "You can't turn off your own account.")
        ctx.store.set_active(uid, active)
        return {"id": uid, "active": active}
