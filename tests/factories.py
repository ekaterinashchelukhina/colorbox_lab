import secrets
from datetime import timedelta
from urllib.parse import unquote

from models import Branch, User, Client, Order, UserSession
from utils import utc_now


def make_branch(db, name=None):
    branch = Branch(name=name or f"Филиал {secrets.token_hex(3)}")
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


def make_user(db, role="Менеджер", branch=None, username=None, token=None):
    if branch is None and role.lower() != "директор":
        branch = make_branch(db)
    user = User(
        username=username or f"user_{secrets.token_hex(4)}",
        role=role,
        branch_id=branch.id if branch else None,
        token=token or secrets.token_hex(8),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_client(db, branch, name=None):
    client_obj = Client(name=name or f"Клиент {secrets.token_hex(3)}", branch_id=branch.id)
    db.add(client_obj)
    db.commit()
    db.refresh(client_obj)
    return client_obj


def make_order(db, branch, client_obj, manager=None, **overrides):
    defaults = dict(
        branch_id=branch.id, client_id=client_obj.id, manager_id=manager.id if manager else None,
        car="Kia Rio", detail="Крыло", paint_code="RAL 123", category="Не указана",
        service_type="Слив по коду", target_volume=100.0, status="В очереди",
        price=0.0, created_at=utc_now(),
    )
    defaults.update(overrides)
    order = Order(**defaults)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def login_session(db, http_client, user, lifetime=timedelta(days=30)):
    """Выдаёт пользователю рабочую сессию в обход формы входа — быстрее для тестов,
    сама форма входа отдельно проверяется в test_auth.py."""
    token = secrets.token_hex(16)
    db.add(UserSession(user_id=user.id, token=token, expires_at=utc_now() + lifetime))
    db.commit()
    http_client.cookies.set("access_token", token)
    return token


def error_text(resp) -> str:
    """Текст ошибки теперь приходит не в теле ответа, а в ?error=... у редиректа
    (utils.error_redirect — всплывающая подсказка вместо отдельной страницы, см.
    static/js/toast.js). С TestClient по умолчанию редирект уже проследован, так
    что resp.url — это финальный адрес с этим же query-параметром; unquote()
    возвращает читаемый текст вместо %D0%9E%D1%88..."""
    return unquote(str(resp.url))
