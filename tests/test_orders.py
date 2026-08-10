from models import Order
from tests.factories import make_branch, make_user, make_client, make_order, login_session, error_text


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

    assert "Отсутствует фото детали" in error_text(resp)
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

    assert "больше нуля" in error_text(resp)
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

    assert "больше нуля" in error_text(resp)
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

    assert "Отсутствует фото рецепта" in error_text(resp)
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

    assert "закреплён за другим колористом" in error_text(resp)
    db_session.refresh(order)
    assert order.status == "В очереди"
    assert order.colorist_id == colorist_a.id


def test_manager_reassign_creates_pending_request_not_immediate_change(client, db_session):
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
    # colorist_id не меняется сразу — только создаётся запрос, ждущий согласия обеих сторон
    assert order.colorist_id == colorist_a.id
    assert order.pending_colorist_id == colorist_b.id
    assert order.transfer_confirmed_by_current is False
    assert order.transfer_confirmed_by_new is False


def test_transfer_completes_only_after_both_sides_accept(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", colorist_id=colorist_a.id)
    login_session(db_session, client, manager)
    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    # Новый колорист соглашается первым — передача ещё не завершена
    login_session(db_session, client, colorist_b)
    client.post(f"/order/{order.id}/transfer-respond", data={"action": "accept"})
    db_session.refresh(order)
    assert order.colorist_id == colorist_a.id
    assert order.transfer_confirmed_by_new is True
    assert order.transfer_confirmed_by_current is False

    # Текущий колорист тоже соглашается — только теперь заказ реально переходит
    login_session(db_session, client, colorist_a)
    client.post(f"/order/{order.id}/transfer-respond", data={"action": "accept"})
    db_session.refresh(order)
    assert order.colorist_id == colorist_b.id
    assert order.pending_colorist_id is None
    assert order.transfer_confirmed_by_current is False
    assert order.transfer_confirmed_by_new is False

    # После передачи colorist_b может сам взять заказ в работу
    login_session(db_session, client, colorist_b)
    resp = client.post(f"/order/{order.id}/status", data={"new_status": "В работе"})
    db_session.refresh(order)
    assert order.status == "В работе"


def test_transfer_decline_by_current_colorist_resets_request(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", colorist_id=colorist_a.id)
    login_session(db_session, client, manager)
    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    login_session(db_session, client, colorist_b)
    client.post(f"/order/{order.id}/transfer-respond", data={"action": "accept"})

    login_session(db_session, client, colorist_a)
    client.post(f"/order/{order.id}/transfer-respond", data={"action": "decline"})

    db_session.refresh(order)
    assert order.colorist_id == colorist_a.id
    assert order.pending_colorist_id is None
    assert order.transfer_confirmed_by_current is False
    assert order.transfer_confirmed_by_new is False


def test_transfer_decline_by_new_colorist_resets_request(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", colorist_id=colorist_a.id)
    login_session(db_session, client, manager)
    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    login_session(db_session, client, colorist_b)
    client.post(f"/order/{order.id}/transfer-respond", data={"action": "decline"})

    db_session.refresh(order)
    assert order.colorist_id == colorist_a.id
    assert order.pending_colorist_id is None
    assert order.transfer_confirmed_by_current is False
    assert order.transfer_confirmed_by_new is False


def test_transfer_respond_rejects_unrelated_colorist(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    colorist_c = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", colorist_id=colorist_a.id)
    login_session(db_session, client, manager)
    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    login_session(db_session, client, colorist_c)
    resp = client.post(f"/order/{order.id}/transfer-respond", data={"action": "accept"})

    assert "не касается вас" in error_text(resp)
    db_session.refresh(order)
    assert order.transfer_confirmed_by_current is False
    assert order.transfer_confirmed_by_new is False


def test_reassign_auto_confirms_current_side_when_no_colorist_assigned(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", colorist_id=None)
    login_session(db_session, client, manager)

    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})
    db_session.refresh(order)
    assert order.transfer_confirmed_by_current is True
    assert order.transfer_confirmed_by_new is False

    # Новому колористу достаточно одного согласия — заказ никому не принадлежал
    login_session(db_session, client, colorist_b)
    client.post(f"/order/{order.id}/transfer-respond", data={"action": "accept"})
    db_session.refresh(order)
    assert order.colorist_id == colorist_b.id
    assert order.pending_colorist_id is None


def test_manager_cannot_start_second_transfer_while_one_pending(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    colorist_c = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", colorist_id=colorist_a.id)
    login_session(db_session, client, manager)
    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    resp = client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_c.id})
    assert "незавершённый запрос" in error_text(resp)

    db_session.refresh(order)
    assert order.pending_colorist_id == colorist_b.id


def test_manager_cannot_start_transfer_on_locked_order(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="Выдано", colorist_id=colorist_a.id)
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})
    assert "выдан или отменён" in error_text(resp)

    db_session.refresh(order)
    assert order.pending_colorist_id is None


def test_manager_can_cancel_pending_transfer_request(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", colorist_id=colorist_a.id)
    login_session(db_session, client, manager)
    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    resp = client.post(f"/order/{order.id}/transfer-cancel", follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(order)
    assert order.colorist_id == colorist_a.id
    assert order.pending_colorist_id is None
    assert order.transfer_confirmed_by_current is False
    assert order.transfer_confirmed_by_new is False

    # Запрос отозван — колорист, не имеющий отношения к делу, больше не может ответить на него
    login_session(db_session, client, colorist_b)
    resp = client.post(f"/order/{order.id}/transfer-respond", data={"action": "accept"}, follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.colorist_id == colorist_a.id


def test_pending_transfer_auto_cancelled_if_order_becomes_locked(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", colorist_id=colorist_a.id)
    login_session(db_session, client, manager)
    client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    # Заказ блокируется (например, выдан) пока запрос ещё висит
    order.status = "Выдано"
    db_session.commit()

    login_session(db_session, client, colorist_b)
    resp = client.post(f"/order/{order.id}/transfer-respond", data={"action": "accept"})
    assert "выдан или отменён" in error_text(resp)

    db_session.refresh(order)
    assert order.colorist_id == colorist_a.id
    assert order.pending_colorist_id is None
    assert order.transfer_confirmed_by_current is False
    assert order.transfer_confirmed_by_new is False


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


def test_manager_cannot_set_order_v_rabote(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди")
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "В работе"})

    assert "только колорист" in error_text(resp)
    db_session.refresh(order)
    assert order.status == "В очереди"


def test_manager_cannot_set_order_gotovo(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В работе", service_type="Слив по коду")
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "Готово"})

    assert "только колорист" in error_text(resp)
    db_session.refresh(order)
    assert order.status == "В работе"


def test_colorist_can_take_order_into_work(client, db_session):
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", service_type="Слив по коду")
    login_session(db_session, client, colorist)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "В работе"}, follow_redirects=False)

    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.status == "В работе"
    assert order.colorist_id == colorist.id


def test_colorist_can_release_own_order(client, db_session):
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В работе", colorist_id=colorist.id)
    login_session(db_session, client, colorist)

    resp = client.post(f"/order/{order.id}/release", follow_redirects=False)

    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.status == "В очереди"
    assert order.colorist_id is None


def test_colorist_cannot_release_someone_elses_order(client, db_session):
    branch = make_branch(db_session)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В работе", colorist_id=colorist_a.id)
    login_session(db_session, client, colorist_b)

    client.post(f"/order/{order.id}/release")

    db_session.refresh(order)
    assert order.status == "В работе"
    assert order.colorist_id == colorist_a.id


def test_manager_cannot_release_order(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В работе", colorist_id=colorist.id)
    login_session(db_session, client, manager)

    client.post(f"/order/{order.id}/release")

    db_session.refresh(order)
    assert order.status == "В работе"
    assert order.colorist_id == colorist.id


def test_manager_cannot_issue_order_without_saved_price(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="Ожидает выдачи", price=0.0)
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "Выдано"})

    assert "сохраните расчёт" in error_text(resp)
    db_session.refresh(order)
    assert order.status == "Ожидает выдачи"


def test_manager_cannot_issue_order_before_colorist_finishes(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В очереди", price=4000.0)
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "Выдано"})

    assert "не завершён" in error_text(resp)
    db_session.refresh(order)
    assert order.status == "В очереди"


def test_manager_can_issue_order_when_ready_and_priced(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="Ожидает выдачи", price=4000.0)
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "Выдано"}, follow_redirects=False)

    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.status == "Выдано"
    assert order.issued_at is not None


def test_manager_cannot_manually_set_other_statuses(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="Ожидает выдачи", price=4000.0)
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "В очереди"})

    assert "только в статус" in error_text(resp)
    db_session.refresh(order)
    assert order.status == "Ожидает выдачи"


def test_colorist_cannot_revert_issued_order_to_v_rabote(client, db_session):
    """Раньше тот же колорист, что вёл заказ, мог прямым POST вернуть уже выданный
    заказ в "В работе" — старые фото уже на месте, missing-photo проверка это
    пропускала. Возврат в работу должен идти только через /order/{id}/rework."""
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="Выдано", colorist_id=colorist.id,
                       service_type="Слив по коду", photo_scales="/x.jpg")
    login_session(db_session, client, colorist)

    resp = client.post(f"/order/{order.id}/status", data={"new_status": "В работе"})

    assert "выдан или отменён" in error_text(resp)
    db_session.refresh(order)
    assert order.status == "Выдано"


def test_manager_cannot_upload_photo_after_issued(client, db_session):
    import io

    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="Выдано",
                       photo_scales="/old.jpg")
    login_session(db_session, client, manager)

    resp = client.post(
        f"/order/{order.id}/upload",
        data={"photo_type": "scales"},
        files={"file": ("new.jpg", io.BytesIO(b"replacement"), "image/jpeg")},
    )

    assert "выдан или отменён" in error_text(resp)
    db_session.refresh(order)
    assert order.photo_scales == "/old.jpg"


def test_colorist_cannot_upload_photo_to_someone_elses_order(client, db_session):
    import io

    branch = make_branch(db_session)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В работе", colorist_id=colorist_a.id)
    login_session(db_session, client, colorist_b)

    resp = client.post(
        f"/order/{order.id}/upload",
        data={"photo_type": "scales"},
        files={"file": ("photo.jpg", io.BytesIO(b"data"), "image/jpeg")},
    )

    assert "закреплён за другим колористом" in error_text(resp)
    db_session.refresh(order)
    assert order.photo_scales is None


def test_manager_cannot_edit_finance_after_issued(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="Выдано", price=4000.0)
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/finance", data={"price": "1", "is_paid": "on"})

    assert "выдан или отменён" in error_text(resp)
    db_session.refresh(order)
    assert order.price == 4000.0


def test_colorist_cannot_comment_on_someone_elses_order(client, db_session):
    branch = make_branch(db_session)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="В работе", colorist_id=colorist_a.id)
    login_session(db_session, client, colorist_b)

    resp = client.post(f"/order/{order.id}/comment",
                       data={"comment_type": "colorist", "comment_text": "чужая заметка"})

    assert "закреплён за другим колористом" in error_text(resp)
    db_session.refresh(order)
    assert order.colorist_comment is None


def test_manager_cannot_comment_after_issued(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="Выдано")
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/comment",
                       data={"comment_type": "manager", "comment_text": "поздний комментарий"})

    assert "выдан или отменён" in error_text(resp)
    db_session.refresh(order)
    assert order.manager_comment is None


def test_manager_cannot_reassign_colorist_after_issued(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_a = make_user(db_session, role="Колорист", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="Выдано", colorist_id=colorist_a.id)
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    assert "выдан или отменён" in error_text(resp)
    db_session.refresh(order)
    assert order.colorist_id == colorist_a.id


def test_manager_cannot_reassign_colorist_on_cancelled_order(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    colorist_b = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, status="Отменен")
    login_session(db_session, client, manager)

    resp = client.post(f"/order/{order.id}/reassign-colorist", data={"colorist_id": colorist_b.id})

    assert "выдан или отменён" in error_text(resp)
    db_session.refresh(order)
    assert order.colorist_id is None
