"""FastAPI app: rotating QR on the board -> student phone -> random gesture challenge -> selfie -> accept/reject.

Doctors sign in (accounts made on /admin), keep one student list per course, and run classes from the course page.
Students never sign in: they scan the QR code, type their ID and take a selfie.

Storage is SQLite at app.db_path, or Postgres when DATABASE_URL is set (hosted on Hugging Face + Supabase).
"""
from __future__ import annotations

import io
import os
import secrets
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import load_config, resolve_path
from . import routes_admin, routes_auth, routes_doctor
from .auth import LoginLimiter, ensure_admin
from .context import AppContext, LoginRedirect
from .store import Store
from .tokens import RotatingToken, Signer

HERE = Path(__file__).parent


def _secret(data_dir: Path, env: str, fname: str, nbytes: int) -> str:
    if os.environ.get(env):
        return os.environ[env]
    p = data_dir / fname
    if p.exists():
        return p.read_text().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    val = secrets.token_urlsafe(nbytes)
    p.write_text(val)
    return val


def decode_image(data: bytes, max_side: int = 1920) -> tuple[np.ndarray, datetime | None]:
    """Decode an upload (applying EXIF rotation) -> BGR array and the EXIF capture time if present."""
    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(data))
    taken = None
    try:
        exif = im.getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
        if raw:
            taken = datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except Exception:
        taken = None
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    return np.asarray(im)[:, :, ::-1].copy(), taken


def create_app(cfg: dict | None = None, verifier=None, store: Store | None = None,
               hosted: bool | None = None) -> FastAPI:
    cfg = cfg or load_config()
    A = cfg["app"]
    db_url = os.environ.get("DATABASE_URL")
    hosted = bool(db_url) if hosted is None else hosted
    db_path = resolve_path(A["db_path"])
    data_dir = db_path.parent
    store = store or Store(db_url or db_path)
    secret = _secret(data_dir, "GA_SECRET", "secret.key", 32).encode()

    generated = ensure_admin(store, os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD"),
                             reset=os.environ.get("ADMIN_RESET_PASSWORD") == "1")
    app = FastAPI(title="Gesture attendance")
    app.state.generated_admin_password = generated
    if generated:
        print(f"\n[admin] Created the first admin account: admin@localhost / {generated}\n"
              "        Sign in and change this password on the Account page.\n")

    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.state.verifier = verifier

    def get_verifier():
        if app.state.verifier is None:
            from ..verify import build_verifier
            app.state.verifier = build_verifier(cfg)
        return app.state.verifier

    ctx = AppContext(cfg=cfg, store=store, signer=Signer(secret),
                     rot=RotatingToken(secret, A["qr_period_s"], A["grace_windows"]),
                     templates=Jinja2Templates(directory=str(HERE / "templates")), gestures=list(cfg["gestures"]),
                     limiter=LoginLimiter(), get_verifier=get_verifier, hosted=hosted)
    app.state.ctx, app.state.store, app.state.rot = ctx, store, ctx.rot

    @app.exception_handler(LoginRedirect)
    async def _redirect(request: Request, exc: LoginRedirect):
        return RedirectResponse(exc.to, status_code=303)

    routes_auth.register(app, ctx)
    routes_admin.register(app, ctx)
    routes_doctor.register(app, ctx)
    return app
