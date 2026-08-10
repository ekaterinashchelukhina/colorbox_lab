"""Регрессионные тесты на изоляцию данных между филиалами (scope_query_to_branch)."""
from models import Client as ClientModel
from tests.factories import make_branch, make_user, make_client, make_order, login_session, error_text


def test_manager_sees_only_own_branch_clients(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    branch_b = make_branch(db_session, "Филиал Б")
    client_a = make_client(db_session, branch_a, "Клиент филиала А")
    client_b = make_client(db_session, branch_b, "Клиент филиала Б")

    manager_a = make_user(db_session, role="Менеджер", branch=branch_a)
    login_session(db_session, client, manager_a)

    resp = client.get("/clients")
    assert resp.status_code == 200
    assert client_a.name in resp.text
    assert client_b.name not in resp.text


def test_manager_sees_only_own_branch_archive(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    branch_b = make_branch(db_session, "Филиал Б")
    client_a = make_client(db_session, branch_a)
    client_b = make_client(db_session, branch_b)
    order_a = make_order(db_session, branch_a, client_a, status="Выдано", paint_code="ORDER-A")
    order_b = make_order(db_session, branch_b, client_b, status="Выдано", paint_code="ORDER-B")

    manager_a = make_user(db_session, role="Менеджер", branch=branch_a)
    login_session(db_session, client, manager_a)

    resp = client.get("/archive")
    assert resp.status_code == 200
    assert order_a.paint_code in resp.text
    assert order_b.paint_code not in resp.text


def test_director_sees_all_branches_and_can_filter(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    branch_b = make_branch(db_session, "Филиал Б")
    client_a = make_client(db_session, branch_a, "Клиент филиала А")
    client_b = make_client(db_session, branch_b, "Клиент филиала Б")

    director = make_user(db_session, role="Директор", branch=None)
    login_session(db_session, client, director)

    resp = client.get("/clients")
    assert resp.status_code == 200
    assert client_a.name in resp.text
    assert client_b.name in resp.text

    resp_filtered = client.get(f"/clients?branch_id={branch_a.id}")
    assert client_a.name in resp_filtered.text
    assert client_b.name not in resp_filtered.text


def test_manager_cannot_view_another_branchs_order(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    branch_b = make_branch(db_session, "Филиал Б")
    client_b = make_client(db_session, branch_b)
    order_b = make_order(db_session, branch_b, client_b, paint_code="ORDER-B")

    manager_a = make_user(db_session, role="Менеджер", branch=branch_a)
    login_session(db_session, client, manager_a)

    resp = client.get(f"/order/{order_b.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"


def test_manager_cannot_update_status_of_another_branchs_order(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    branch_b = make_branch(db_session, "Филиал Б")
    client_b = make_client(db_session, branch_b)
    order_b = make_order(db_session, branch_b, client_b, status="В очереди")

    manager_a = make_user(db_session, role="Менеджер", branch=branch_a)
    login_session(db_session, client, manager_a)

    client.post(f"/order/{order_b.id}/status", data={"new_status": "Выдано"})

    db_session.refresh(order_b)
    assert order_b.status == "В очереди"


def test_manager_cannot_view_another_branchs_client(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    branch_b = make_branch(db_session, "Филиал Б")
    client_b = make_client(db_session, branch_b)

    manager_a = make_user(db_session, role="Менеджер", branch=branch_a)
    login_session(db_session, client, manager_a)

    resp = client.get(f"/client/{client_b.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"


def test_colorist_cannot_edit_order_finance(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    client_a = make_client(db_session, branch_a)
    order_a = make_order(db_session, branch_a, client_a, price=0.0, is_paid=False)

    colorist_a = make_user(db_session, role="Колорист", branch=branch_a)
    login_session(db_session, client, colorist_a)

    client.post(f"/order/{order_a.id}/finance", data={"price": "500", "is_paid": "on"})

    db_session.refresh(order_a)
    assert order_a.price == 0.0
    assert order_a.is_paid is False


def test_colorist_cannot_write_manager_comment(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    client_a = make_client(db_session, branch_a)
    order_a = make_order(db_session, branch_a, client_a)

    colorist_a = make_user(db_session, role="Колорист", branch=branch_a)
    login_session(db_session, client, colorist_a)

    resp = client.post(f"/order/{order_a.id}/comment",
                       data={"comment_type": "manager", "comment_text": "чужой комментарий"})

    assert "Недостаточно прав" in error_text(resp)
    db_session.refresh(order_a)
    assert order_a.manager_comment is None


def test_manager_cannot_create_client_for_another_branch(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    branch_b = make_branch(db_session, "Филиал Б")
    manager_a = make_user(db_session, role="Менеджер", branch=branch_a)
    login_session(db_session, client, manager_a)

    resp = client.post("/new-client", data={"client_name": "Чужой клиент", "branch_id": branch_b.id})

    assert "чужой филиал" in error_text(resp)
    assert db_session.query(ClientModel).filter(ClientModel.name == "Чужой клиент").first() is None


def test_colorist_cannot_view_archive(client, db_session):
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    login_session(db_session, client, colorist)

    resp = client.get("/archive", follow_redirects=False)

    assert resp.status_code == 303


def test_colorist_cannot_view_clients_list(client, db_session):
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    login_session(db_session, client, colorist)

    resp = client.get("/clients", follow_redirects=False)

    assert resp.status_code == 303


def test_colorist_cannot_view_client_detail(client, db_session):
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    login_session(db_session, client, colorist)

    resp = client.get(f"/client/{client_obj.id}", follow_redirects=False)

    assert resp.status_code == 303
