from fastapi.testclient import TestClient
from helpers import ADMIN, admin_client, login, make_app, new_doctor


def test_pages_need_login(tmp_path):
    c = TestClient(make_app(tmp_path))
    for page in ("/", "/admin", "/account"):
        r = c.get(page, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login", page
    assert c.get("/api/courses").status_code == 401
    assert c.get("/api/admin/users").status_code == 401
    assert c.get("/login").status_code == 200


def test_login_logout(tmp_path):
    c = TestClient(make_app(tmp_path))
    r = c.post("/login", data={"email": ADMIN[0], "password": "nope-nope"})
    assert "Email or password is wrong." in r.text
    login(c, " ADMIN@test.com ", ADMIN[1])
    assert "ga_user" in c.cookies
    assert c.get("/", follow_redirects=False).status_code == 200
    c.post("/logout")
    assert c.get("/", follow_redirects=False).status_code == 303


def test_rate_limit(tmp_path):
    c = TestClient(make_app(tmp_path))
    for _ in range(10):
        c.post("/login", data={"email": ADMIN[0], "password": "wrong-pass"})
    r = c.post("/login", data={"email": ADMIN[0], "password": ADMIN[1]}, follow_redirects=False)
    assert r.status_code != 303 and "Too many tries" in r.text


def test_admin_creates_doctor(tmp_path):
    app = make_app(tmp_path)
    adm = admin_client(app)
    r = adm.post("/api/admin/users", data={"name": "Dr Ali", "email": "ali@uni.edu"})
    assert r.status_code == 200 and len(r.json()["password"]) == 12
    assert adm.post("/api/admin/users", data={"name": "X", "email": "ali@uni.edu"}).status_code == 400
    r = adm.post("/api/admin/users", data={"name": "Dr Sara", "email": "sara@uni.edu", "password": "chosen-pass"})
    assert r.json()["password"] == "chosen-pass"
    users = {u["email"]: u for u in adm.get("/api/admin/users").json()}
    assert users["ali@uni.edu"]["role"] == "doctor" and "password_hash" not in users["ali@uni.edu"]
    dr = login(TestClient(app), "sara@uni.edu", "chosen-pass")
    assert dr.get("/api/admin/users").status_code == 403
    r = dr.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert adm.get("/admin").status_code == 200 and "Dr Ali" in adm.get("/admin").text


def test_admin_resets_password(tmp_path):
    app = make_app(tmp_path)
    adm = admin_client(app)
    uid = adm.post("/api/admin/users", data={"name": "Dr A", "email": "a@uni.edu"}).json()["id"]
    pw = adm.post(f"/api/admin/users/{uid}/password").json()["password"]
    login(TestClient(app), "a@uni.edu", pw)


def test_disabled_doctor_is_signed_out(tmp_path):
    app = make_app(tmp_path)
    dr = new_doctor(app)
    assert dr.get("/api/courses").status_code == 200
    adm = admin_client(app)
    uid = next(u["id"] for u in adm.get("/api/admin/users").json() if u["email"] == "dr@test.com")
    adm.post(f"/api/admin/users/{uid}/active", data={"active": "false"})
    assert dr.get("/api/courses").status_code == 401
    assert dr.get("/", follow_redirects=False).headers["location"] == "/login"
    r = TestClient(app).post("/login", data={"email": "dr@test.com", "password": "whatever-1"})
    assert "Email or password is wrong." in r.text


def test_admin_cannot_disable_self(tmp_path):
    app = make_app(tmp_path)
    adm = admin_client(app)
    me = next(u["id"] for u in adm.get("/api/admin/users").json() if u["email"] == ADMIN[0])
    assert adm.post(f"/api/admin/users/{me}/active", data={"active": "false"}).status_code == 400


def test_change_password(tmp_path):
    app = make_app(tmp_path)
    adm = admin_client(app)
    r = adm.post("/api/account/password", data={"current": "bad-current", "new": "brand-new-pass"})
    assert r.status_code == 400
    assert adm.post("/api/account/password", data={"current": ADMIN[1], "new": "short"}).status_code == 400
    assert adm.post("/api/account/password", data={"current": ADMIN[1], "new": "brand-new-pass"}).status_code == 200
    login(TestClient(app), ADMIN[0], "brand-new-pass")
