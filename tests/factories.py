import secrets
from datetime import timedelta

from models import Branch, User, Client, Order
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
    user.session_token = secrets.token_hex(16)
    user.session_expires_at = utc_now() + lifetime
    db.commit()
    http_client.cookies.set("access_token", user.session_token)
    return user.session_token
