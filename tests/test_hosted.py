import pytest
from fastapi.testclient import TestClient
from helpers import ADMIN, make_app

from gesture_attendance.app.__main__ import main


def test_hosted_requires_secrets(monkeypatch):
    for k in ("DATABASE_URL", "GA_SECRET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit) as e:
        main(["--hosted"])
    assert "DATABASE_URL" in str(e.value) and "GA_SECRET" in str(e.value)


def test_collect_hidden_when_hosted(tmp_path):
    app = make_app(tmp_path, hosted=True)
    c = TestClient(app)
    c.post("/login", data={"email": ADMIN[0], "password": ADMIN[1]})
    assert c.get("/collect").status_code == 404
    assert c.post("/api/collect").status_code in (404, 405)


def test_collect_available_on_laptop(tmp_path):
    c = TestClient(make_app(tmp_path))
    c.post("/login", data={"email": ADMIN[0], "password": ADMIN[1]})
    assert c.get("/collect").status_code == 200


def test_secure_cookie_over_https(tmp_path):
    c = TestClient(make_app(tmp_path), base_url="https://testserver")
    r = c.post("/login", data={"email": ADMIN[0], "password": ADMIN[1]}, follow_redirects=False)
    cookie = r.headers["set-cookie"]
    assert "ga_user=" in cookie and "Secure" in cookie and "HttpOnly" in cookie


def test_plain_cookie_over_http(tmp_path):
    c = TestClient(make_app(tmp_path))
    r = c.post("/login", data={"email": ADMIN[0], "password": ADMIN[1]}, follow_redirects=False)
    assert "Secure" not in r.headers["set-cookie"]
