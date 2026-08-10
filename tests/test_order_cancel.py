"""Регрессионные тесты на 'мягкое удаление' заказа менеджером (перевод в архив со
статусом 'Отменен') — право есть только у менеджера."""
from tests.factories import make_branch, make_user, make_client, make_order, login_session, error_text


def test_manager_can_cancel_order(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="В очереди")
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/cancel", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/archive"
    db_session.refresh(order)
    assert order.status == "Отменен"


def test_cancelled_order_appears_in_archive(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="В очереди",
                       paint_code="CANCEL-ME")
    login_session(db_session, client, manager)

    client.post(f"/order/{order.id}/cancel")

    resp = client.get("/archive")
    assert order.paint_code in resp.text


def test_cancelled_order_disappears_from_manager_dashboard(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="В очереди",
                       paint_code="CANCEL-DASH")
    login_session(db_session, client, manager)

    client.post(f"/order/{order.id}/cancel")

    resp = client.get("/dashboard")
    assert order.paint_code not in resp.text


def test_director_cannot_cancel_order(client, db_session):
    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди")
    login_session(db_session, client, director)

    client.post(f"/order/{order.id}/cancel")

    db_session.refresh(order)
    assert order.status == "В очереди"


def test_colorist_cannot_cancel_order(client, db_session):
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди")
    login_session(db_session, client, colorist)

    client.post(f"/order/{order.id}/cancel")

    db_session.refresh(order)
    assert order.status == "В очереди"


def test_cannot_cancel_already_issued_order(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="Выдано")
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/cancel")

    assert "уже выданный" in error_text(resp)
    db_session.refresh(order)
    assert order.status == "Выдано"


def test_manager_cannot_cancel_order_already_taken_by_colorist(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="В работе",
                       colorist_id=colorist.id)
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/cancel")

    assert "колорист уже взял" in error_text(resp)
    db_session.refresh(order)
    assert order.status == "В работе"


def test_manager_cannot_cancel_another_branchs_order(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    branch_b = make_branch(db_session, "Филиал Б")
    client_b = make_client(db_session, branch_b)
    order_b = make_order(db_session, branch_b, client_b, status="В очереди")

    manager_a = make_user(db_session, role="Менеджер", branch=branch_a)
    login_session(db_session, client, manager_a)

    client.post(f"/order/{order_b.id}/cancel")

    db_session.refresh(order_b)
    assert order_b.status == "В очереди"


def test_cancelled_order_disappears_from_director_active_orders(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="В очереди",
                       paint_code="CANCEL-DIRECTOR")
    login_session(db_session, client, manager)
    client.post(f"/order/{order.id}/cancel")

    director = make_user(db_session, role="Директор", branch=None)
    login_session(db_session, client, director)

    resp = client.get("/director")
    assert order.paint_code not in resp.text


def test_cannot_set_cancelled_status_through_generic_status_route(client, db_session):
    """Отмена — только через /order/{id}/cancel с проверкой роли; прямой POST на
    /order/{id}/status с new_status='Отменен' не должен срабатывать ни для кого,
    иначе отмену можно было бы сделать в обход ограничения 'только менеджер'."""
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="В очереди")
    login_session(db_session, client, manager)

    client.post(f"/order/{order.id}/status", data={"new_status": "Отменен"})

    db_session.refresh(order)
    assert order.status == "В очереди"