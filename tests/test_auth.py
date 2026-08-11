from datetime import timedelta

from models import UserSession
from utils import utc_now, hash_token, LOGIN_MAX_ATTEMPTS
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

    session = db_session.query(UserSession).filter(UserSession.token == session_cookie).first()
    assert session is not None
    assert session.user_id == user.id
    assert session.expires_at is not None


def test_second_login_does_not_invalidate_first_session(client, db_session):
    """Регрессия на баг: вход с одного устройства не должен разлогинивать другое —
    раньше session_token жил одной колонкой на User и второй вход её перезаписывал."""
    user = make_user(db_session, role="Менеджер", token="permanent-secret")

    first_token = login_session(db_session, client, user)

    resp = client.post("/login", data={"username": user.username, "token": "permanent-secret"},
                        follow_redirects=False)
    second_token = resp.cookies.get("access_token")
    assert second_token != first_token

    client.cookies.set("access_token", first_token)
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 200


def test_login_wrong_token_rejected(client, db_session):
    user = make_user(db_session, role="Менеджер", token="correct-token")

    resp = client.post("/login", data={"username": user.username, "token": "wrong-token"})

    assert resp.status_code == 200
    assert "Неверный логин" in resp.text
    assert "access_token" not in resp.cookies


def test_legacy_plaintext_token_upgraded_to_hash_on_login(client, db_session):
    """Сотрудники, заведённые до перехода на хэширование, хранят token открытым
    текстом — при первом же успешном входе он должен смениться на token_hash,
    а поле token обнулиться."""
    user = make_user(db_session, role="Менеджер", token="legacy-plain-token")

    resp = client.post("/login", data={"username": user.username, "token": "legacy-plain-token"},
                        follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(user)
    assert user.token is None
    assert user.token_hash is not None

    # И повторный вход тем же токеном по-прежнему работает — уже через хэш.
    resp2 = client.post("/login", data={"username": user.username, "token": "legacy-plain-token"},
                         follow_redirects=False)
    assert resp2.status_code == 303


def test_login_hashed_token_accepted(client, db_session):
    user = make_user(db_session, role="Менеджер", token=None)
    user.token_hash = hash_token("my-secret-token")
    db_session.commit()

    resp = client.post("/login", data={"username": user.username, "token": "my-secret-token"},
                        follow_redirects=False)
    assert resp.status_code == 303


def test_login_locks_account_after_max_failed_attempts(client, db_session):
    user = make_user(db_session, role="Менеджер", token="correct-token")

    for _ in range(LOGIN_MAX_ATTEMPTS):
        resp = client.post("/login", data={"username": user.username, "token": "wrong"})
        assert resp.status_code == 200

    db_session.refresh(user)
    assert user.locked_until is not None
    assert user.locked_until > utc_now()

    # Даже правильный токен не пускает, пока аккаунт заблокирован
    resp = client.post("/login", data={"username": user.username, "token": "correct-token"})
    assert resp.status_code == 200
    assert "Слишком много" in resp.text
    assert "access_token" not in resp.cookies


def test_login_lockout_clears_after_successful_login(client, db_session):
    user = make_user(db_session, role="Менеджер", token="correct-token")

    for _ in range(LOGIN_MAX_ATTEMPTS - 1):
        client.post("/login", data={"username": user.username, "token": "wrong"})

    resp = client.post("/login", data={"username": user.username, "token": "correct-token"},
                        follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


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
    token = login_session(db_session, client, user)

    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303

    assert db_session.query(UserSession).filter(UserSession.token == token).first() is None

    # Cookie, даже если сохранить его вручную, больше не должен работать
    client.cookies.set("access_token", "not-a-real-session")
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
