"""Local email/password accounts: signup, login, sessions, isolation.

These use the real auth flow (Authorization: Bearer <token>). The existing dev
stub (X-User-Id / default dev user) still works and the other test files rely on
it — this file only exercises the new account path.
"""
from sqlalchemy import select

from app import models
from app.db import SessionLocal


def _signup(client, email, password="secret123", display_name=None):
    body = {"email": email, "password": password}
    if display_name:
        body["display_name"] = display_name
    return client.post("/auth/signup", json=body)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_returns_token_and_provisions_account(client):
    r = _signup(client, "alice@example.com", display_name="Alice")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"]
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["display_name"] == "Alice"

    # The token authenticates, and the account comes with its core lists.
    me = client.get("/me", headers=_auth(body["token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"
    lists = client.get("/lists", headers=_auth(body["token"])).json()
    assert {l["type"] for l in lists} == {"want_to_try", "visited"}


def test_signup_duplicate_email_conflicts_case_insensitively(client):
    _signup(client, "dupe@example.com")
    again = _signup(client, "DUPE@example.com")
    assert again.status_code == 409


def test_signup_rejects_short_password_and_bad_email(client):
    short = client.post("/auth/signup", json={"email": "x@y.com", "password": "short"})
    assert short.status_code == 422
    bad = client.post("/auth/signup", json={"email": "notanemail", "password": "longenough"})
    assert bad.status_code == 422


def test_login_roundtrip_and_bad_credentials(client):
    _signup(client, "bob@example.com", password="hunter2pass")
    ok = client.post("/auth/login", json={"email": "bob@example.com", "password": "hunter2pass"})
    assert ok.status_code == 200
    assert ok.json()["token"]

    wrong = client.post("/auth/login", json={"email": "bob@example.com", "password": "nope"})
    assert wrong.status_code == 401
    unknown = client.post("/auth/login", json={"email": "ghost@example.com", "password": "whatever"})
    assert unknown.status_code == 401


def test_accounts_have_isolated_lists(client):
    t1 = _signup(client, "carol@example.com").json()["token"]
    t2 = _signup(client, "dave@example.com").json()["token"]

    want1 = next(l for l in client.get("/lists", headers=_auth(t1)).json() if l["type"] == "want_to_try")
    client.post(f"/lists/{want1['id']}/items", headers=_auth(t1), json={"restaurant_id": "r1"})

    # Dave sees none of Carol's saves.
    want2 = next(l for l in client.get("/lists", headers=_auth(t2)).json() if l["type"] == "want_to_try")
    assert client.get(f"/lists/{want2['id']}/items", headers=_auth(t2)).json() == []
    mine = client.get(f"/lists/{want1['id']}/items", headers=_auth(t1)).json()
    assert [i["restaurant_id"] for i in mine] == ["r1"]


def test_logout_invalidates_the_token(client):
    token = _signup(client, "erin@example.com").json()["token"]
    assert client.get("/me", headers=_auth(token)).status_code == 200
    assert client.post("/auth/logout", headers=_auth(token)).status_code == 204
    assert client.get("/me", headers=_auth(token)).status_code == 401


def test_invalid_token_is_rejected(client):
    assert client.get("/me", headers=_auth("not-a-real-token")).status_code == 401


def test_password_is_hashed_not_stored_plaintext(client):
    _signup(client, "frank@example.com", password="plaintextcheck")
    db = SessionLocal()
    user = db.scalar(select(models.User).where(models.User.email == "frank@example.com"))
    db.close()
    assert user.password_hash
    assert "plaintextcheck" not in user.password_hash
    assert user.password_hash.startswith("pbkdf2_sha256$")


def test_dev_stub_still_works_without_a_token(client):
    # No Authorization header -> the X-User-Id dev stub is unaffected.
    isolated = client.get("/me", headers={"X-User-Id": "some-dev-user"})
    assert isolated.status_code == 200
    assert isolated.json()["id"] == "some-dev-user"
