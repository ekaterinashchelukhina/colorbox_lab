from models import Order
from tests.factories import make_branch, make_user, make_client, make_order, login_session


def _start_manager_shift(client, db_session, manager):
    login_session(db_session, client, manager)
    client.post("/manager/shift/start")


def test_create_order_requires_photo_for_podbor(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    _start_manager_shift(client, db_session, manager)

    resp = client.post("/new-order", data={
        "client_name": "Клиент", "car": "Kia", "detail": "Крыло",
        "service_type": "Подбор", "target_volume": "100", "deadline": "2026-12-31",
    })

    assert "Отсутствует фото детали" in resp.text
    assert db_session.query(Order).count() == 0


def test_create_order_slив_po_kodu_no_photo_required(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    _start_manager_shift(client, db_session, manager)

    resp = client.post("/new-order", data={
        "client_name": "Клиент", "car": "Kia", "detail": "Крыло",
        "service_type": "Слив по коду", "target_volume": "100", "deadline": "2026-12-31",
    }, follow_redirects=False)

    assert resp.status_code == 303
    assert db_session.query(Order).count() == 1


def test_new_order_deadline_is_naive_utc(client, db_session):
    """deadline_at должен быть naive datetime, как и все остальные DateTime-колонки
    (см. database.utc_now) — иначе сравнение с utc_now() в будущем упадёт с TypeError
    на смешивании naive/aware datetime."""
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    _start_manager_shift(client, db_session, manager)

    client.post("/new-order", data={
        "client_name": "Клиент", "car": "Kia", "detail": "Крыло",
        "service_type": "Слив по коду", "target_volume": "100", "deadline": "2026-12-31",
    })

    order = db_session.query(Order).first()
    assert order.deadline_at.tzinfo is None


def test_create_order_rejects_negative_volume(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    _start_manager_shift(client, db_session, manager)

    resp = client.post("/new-order", data={
        "client_name": "Клиент", "car": "Kia", "detail": "Крыло",
        "service_type": "Слив по коду", "target_volume": "-50", "deadline": "2026-12-31",
    })

    assert "больше нуля" in resp.text
    assert db_session.query(Order).count() == 0


def test_order_completion_rejects_negative_actual_volume(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, service_type="Слив по коду",
                       photo_scales="/x.jpg")

    colorist = make_user(db_session, role="Колорист", branch=branch)
    login_session(db_session, client, colorist)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "Готово", "actual_volume": "-10"})

    assert "больше нуля" in resp.text
    db_session.refresh(order)
    assert order.status == "В очереди"
    assert order.actual_volume is None


def test_order_completion_requires_recipe_photo_for_podbor(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, service_type="Подбор",
                       photo_scales="/x.jpg", photo_after="/x.jpg", photo_detail="/x.jpg")

    colorist = make_user(db_session, role="Колорист", branch=branch)
    login_session(db_session, client, colorist)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "Готово", "actual_volume": "95"})

    assert "Отсутствует фото рецепта" in resp.text
    db_session.refresh(order)
    assert order.status == "В очереди"  # статус не поменялся


def test_order_completion_recipe_photo_optional_for_sliv_po_kodu(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, service_type="Слив по коду",
                       photo_scales="/x.jpg")

    colorist = make_user(db_session, role="Колорист", branch=branch)
    login_session(db_session, client, colorist)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "Готово", "actual_volume": "95"},
                       follow_redirects=False)

    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.status == "Ожидает выдачи"


def test_rework_resets_fields(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="Выдано",
                       rework_count=0, rework_photo_scales="/old.jpg")
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/rework", follow_redirects=False)

    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.status == "В очереди"
    assert order.rework_count == 1
    assert order.rework_photo_scales is None
    assert order.issued_at is None


def test_director_cannot_send_order_to_rework(client, db_session):
    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="Выдано", rework_count=0)
    login_session(db_session, client, director)

    client.post(f"/order/{order.id}/rework")

    db_session.refresh(order)
    assert order.status == "Выдано"
    assert order.rework_count == 0


def test_colorist_cannot_send_order_to_rework(client, db_session):
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="Выдано", rework_count=0)
    login_session(db_session, client, colorist)

    client.post(f"/order/{order.id}/rework")

    db_session.refresh(order)
    assert order.status == "Выдано"
    assert order.rework_count == 0


def test_director_cannot_change_order_status(client, db_session):
    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди")
    login_session(db_session, client, director)

    client.post(f"/order/{order.id}/status", data={"new_status": "Выдано"})

    db_session.refresh(order)
    assert order.status == "В очереди"


def test_director_cannot_upload_order_photo(client, db_session):
    import io

    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди")
    login_session(db_session, client, director)

    resp = client.post(
        f"/order/{order.id}/upload",
        data={"photo_type": "scales"},
        files={"file": ("photo.jpg", io.BytesIO(b"not checked, blocked before validation"), "image/jpeg")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.photo_scales is None


def test_other_colorist_cannot_take_over_assigned_order(client, db_session):
    branch = make_branch(db_session)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди",
                       rework_count=1, colorist_id=colorist_a.id, service_type="Слив по коду")
    login_session(db_session, client, colorist_b)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "В работе"})

    assert "закреплён за другим колористом" in resp.text
    db_session.refresh(order)
    assert order.status == "В очереди"
    assert order.colorist_id == colorist_a.id


def test_manager_can_reassign_order_to_another_colorist(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди",
                       rework_count=1, colorist_id=colorist_a.id, service_type="Слив по коду")
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/reassign-colorist",
                       data={"colorist_id": colorist_b.id}, follow_redirects=False)

    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.colorist_id == colorist_b.id

    # После передачи colorist_b может сам взять заказ в работу, colorist_a — уже нет
    login_session(db_session, client, colorist_b)
    resp = client.post(f"/order/{order.id}/status", data={"new_status": "В работе"})
    db_session.refresh(order)
    assert order.status == "В работе"


def test_reassign_colorist_blocked_for_non_manager(client, db_session):
    branch = make_branch(db_session)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", colorist_id=colorist_a.id)
    login_session(db_session, client, colorist_a)

    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    db_session.refresh(order)
    assert order.colorist_id == colorist_a.id


def test_reassign_colorist_rejects_colorist_from_another_branch(client, db_session):
    branch_a = make_branch(db_session, "Филиал А")
    branch_b = make_branch(db_session, "Филиал Б")
    manager_a = make_user(db_session, role="Менеджер", branch=branch_a)
    colorist_a = make_user(db_session, role="Колорист", branch=branch_a)
    colorist_b = make_user(db_session, role="Колорист", branch=branch_b)
    client_obj = make_client(db_session, branch_a)
    order = make_order(db_session, branch_a, client_obj, status="В очереди", colorist_id=colorist_a.id)
    login_session(db_session, client, manager_a)

    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    db_session.refresh(order)
    assert order.colorist_id == colorist_a.id
