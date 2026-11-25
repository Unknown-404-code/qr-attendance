"""Doctor pages and APIs: courses, student lists, classes, live stats, QR board, Excel reports."""
from __future__ import annotations

from fastapi import Depends, FastAPI, Request

from .context import AppContext, require_user


def register(app: FastAPI, ctx: AppContext) -> None:
    page_user, api_user = require_user(ctx, page=True), require_user(ctx)

    def my_courses(user: dict) -> list[dict]:
        return ctx.store.courses(None if user["role"] == "admin" else user["id"])

    @app.get("/")
    def home(request: Request, user: dict = Depends(page_user)):
        return ctx.render(request, "home.html", courses=my_courses(user))

    @app.get("/api/courses")
    def list_courses(user: dict = Depends(api_user)):
        return my_courses(user)
