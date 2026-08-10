"""Регрессионные тесты на директорские роуты: авторизация, безопасное удаление."""
from models import Branch, Shift, User
from routers.director import _apply_shift_filters
from tests.factories import make_branch, make_user, make_client, make_order, login_session
from utils import utc_now


def test_delete_user_with_orders_does_not_crash(client, db_session):
    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager)
    order.colorist_id = colorist.id
    db_session.commit()

    login_session(db_session, client, director)

    resp = client.post(f"/director/user/delete/{manager.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert "success=user_delete" in resp.headers["location"]

    db_session.refresh(order)
    assert order.manager_id is None
    assert db_session.query(User).filter(User.id == manager.id).first() is None

    resp = client.post(f"/director/user/delete/{colorist.id}", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.colorist_id is None
    # Имя удалённого колориста сохраняется отдельно — иначе такой заказ было бы не
    # отличить от заказа, который вообще ещё никто не брал в работу (colorist_id
    # тоже None в обоих случаях).
    assert order.colorist_deleted_name == colorist.username


def test_cannot_delete_branch_with_dependents(client, db_session):
    branch = make_branch(db_session)
    make_user(db_session, role="Менеджер", branch=branch)
    director = make_user(db_session, role="Директор", branch=None)
    login_session(db_session, client, director)

    resp = client.post(f"/director/branch/delete/{branch.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert "error=branch_in_use" in resp.headers["location"]
    assert db_session.query(Branch).filter(Branch.id == branch.id).first() is not None


def test_can_delete_empty_branch(client, db_session):
    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    login_session(db_session, client, director)

    resp = client.post(f"/director/branch/delete/{branch.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert "success=branch_delete" in resp.headers["location"]
    assert db_session.query(Branch).filter(Branch.id == branch.id).first() is None


def test_add_user_rejects_invalid_role(client, db_session):
    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    login_session(db_session, client, director)

    resp = client.post("/director/user/add", data={
        "username_new": "hacker", "role": "SuperAdmin", "branch_id": branch.id,
    })

    assert "Ошибка" in resp.text
    assert db_session.query(User).filter(User.username == "hacker").first() is None


def test_new_user_login_survives_stray_whitespace_in_username(client, db_session):
    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    login_session(db_session, client, director)

    resp = client.post("/director/user/add", data={
        "username_new": "ivan ", "role": "Менеджер", "branch_id": branch.id,
    }, follow_redirects=False)
    assert resp.status_code == 303

    stored = db_session.query(User).filter(User.username == "ivan").first()
    assert stored is not None
    assert stored.token is not None

    login_resp = client.post("/login", data={"username": "ivan", "token": stored.token},
                             follow_redirects=False)
    assert login_resp.status_code == 303
    assert login_resp.headers["location"] != "/"


def test_apply_shift_filters_keeps_colorist_id_zero(db_session):
    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    colorist_zero = User(id=0, username="colorist_zero", role="Колорист", branch_id=branch.id, token="t0")
    colorist_other = make_user(db_session, role="Колорист", branch=branch)
    db_session.add(colorist_zero)
    db_session.commit()

    shift_zero = Shift(user_id=0, branch_id=branch.id, start_time=utc_now(), end_time=utc_now())
    shift_other = Shift(user_id=colorist_other.id, branch_id=branch.id, start_time=utc_now(), end_time=utc_now())
    db_session.add_all([shift_zero, shift_other])
    db_session.commit()

    query = db_session.query(Shift)
    filtered = _apply_shift_filters(query, director, None, 0, None, None).all()

    assert [s.id for s in filtered] == [shift_zero.id]