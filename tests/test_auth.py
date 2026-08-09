from datetime import timedelta

from utils import utc_now
from tests.factories import make_user, login_session


def test_login_success_issues_session_cookie_distinct_from_login_token(client, db_session):
    user = make_user(db_session, role="Менеджер", token="permanent-secret")

    resp = client.post("/login", data={"username": user.username, "token": "permanent-secret"},
                        follow_redirects=False)

    assert resp.status_code == 303
    session_cookie = resp.cookies.get("access_token")
    assert session_cookie is not None
    # Сессионный токен в cookie не должен совпадать с постоянным логин-токеном
    assert session_cookie != "permanent-secret"

    db_session.refresh(user)
    assert user.session_token == session_cookie
    assert user.session_expires_at is not None


def test_login_wrong_token_rejected(client, db_session):
    user = make_user(db_session, role="Менеджер", token="correct-token")

    resp = client.post("/login", data={"username": user.username, "token": "wrong-token"})

    assert resp.status_code == 200
    assert "Неверный логин" in resp.text
    assert "access_token" not in resp.cookies


def test_expired_session_denies_access(client, db_session):
    user = make_user(db_session, role="Менеджер")
    login_session(db_session, client, user, lifetime=timedelta(hours=-1))  # уже истекла

    resp = client.get("/dashboard", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_valid_session_grants_access(client, db_session):
    user = make_user(db_session, role="Менеджер")
    login_session(db_session, client, user)

    resp = client.get("/dashboard", follow_redirects=False)

    assert resp.status_code == 200


def test_logout_clears_session_server_side(client, db_session):
    user = make_user(db_session, role="Менеджер")
    login_session(db_session, client, user)

    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(user)
    assert user.session_token is None
    assert user.session_expires_at is None

    # Cookie, даже если сохранить его вручную, больше не должен работать
    client.cookies.set("access_token", "not-a-real-session")
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
