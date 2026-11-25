"""Shared test helpers: build an app with a known admin, log clients in, make doctors."""
from fastapi.testclient import TestClient

from gesture_attendance.app.auth import ensure_admin
from gesture_attendance.app.main import create_app
from gesture_attendance.app.store import Store
from gesture_attendance.config import load_config

ADMIN = ("admin@test.com", "admin-pass-1")


def make_app(tmp_path, verifier=None, hosted=False, **cfg_overrides):
    cfg = load_config()
    cfg["app"]["db_path"] = str(tmp_path / "db.sqlite")
    cfg["app"]["collect_dir"] = str(tmp_path / "collect")
    for k, v in cfg_overrides.items():
        cfg["app"][k] = v
    store = Store(tmp_path / "db.sqlite")
    ensure_admin(store, *ADMIN)
    return create_app(cfg, verifier=verifier, store=store, hosted=hosted)


def login(client: TestClient, email: str, pw: str):
    r = client.post("/login", data={"email": email, "password": pw}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


def admin_client(app, **kw) -> TestClient:
    return login(TestClient(app, **kw), *ADMIN)


def new_doctor(app, email="dr@test.com", name="Dr Test") -> TestClient:
    """Admin creates a doctor account; returns a client logged in as that doctor."""
    pw = admin_client(app).post("/api/admin/users", data={"name": name, "email": email}).json()["password"]
    return login(TestClient(app), email, pw)
