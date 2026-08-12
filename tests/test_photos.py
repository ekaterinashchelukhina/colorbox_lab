"""Раздача фото заказа (main.py:serve_uploaded_photo) — до рефакторинга под storage.py
читала байты прямо с диска, теперь идёт через storage.open(); эти тесты проверяют,
что поведение (изоляция по филиалу, 404 на чужое/несуществующее) не изменилось."""
import io
import json

from PIL import Image

from models import Shift
from tests.factories import make_branch, make_client, make_order, make_user, login_session


def _fake_jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buffer, "JPEG")
    return buffer.getvalue()


def _upload_scales_photo(client, db_session, order, uploader):
    login_session(db_session, client, uploader)
    resp = client.post(
        f"/order/{order.id}/upload",
        data={"photo_type": "scales"},
        files={"file": ("scales.jpg", io.BytesIO(_fake_jpeg_bytes()), "image/jpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(order)
    assert order.photo_scales is not None
    return order.photo_scales


def test_own_branch_manager_can_view_uploaded_photo(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    client_obj = make_client(db_session, branch)
    order = make_order(db_session, branch, client_obj, manager=manager, status="В работе")

    photo_url = _upload_scales_photo(client, db_session, order, manager)

    resp = client.get(photo_url)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


def test_other_branch_manager_cannot_view_photo(client, db_session):
    branch_a = make_branch(db_session)
    branch_b = make_branch(db_session)
    manager_a = make_user(db_session, role="Менеджер", branch=branch_a)
    manager_b = make_user(db_session, role="Менеджер", branch=branch_b)
    client_obj = make_client(db_session, branch_a)
    order = make_order(db_session, branch_a, client_obj, manager=manager_a, status="В работе")

    photo_url = _upload_scales_photo(client, db_session, order, manager_a)

    login_session(db_session, client, manager_b)
    resp = client.get(photo_url)
    assert resp.status_code == 404


def test_unknown_photo_url_returns_404(client, db_session):
    manager = make_user(db_session, role="Менеджер")
    login_session(db_session, client, manager)

    resp = client.get("/static/uploads/never-existed.jpg")
    assert resp.status_code == 404


def test_own_branch_can_view_shift_photo(client, db_session):
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    login_session(db_session, client, colorist)

    resp = client.post(
        "/shift/start",
        files={"photos": ("start.jpg", io.BytesIO(_fake_jpeg_bytes()), "image/jpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    shift = db_session.query(Shift).filter(Shift.user_id == colorist.id).one()
    photo_url = json.loads(shift.start_photos)[0]

    resp = client.get(photo_url)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


def test_other_branch_cannot_view_shift_photo(client, db_session):
    branch_a = make_branch(db_session)
    branch_b = make_branch(db_session)
    colorist_a = make_user(db_session, role="Колорист", branch=branch_a)
    colorist_b = make_user(db_session, role="Колорист", branch=branch_b)

    login_session(db_session, client, colorist_a)
    resp = client.post(
        "/shift/start",
        files={"photos": ("start.jpg", io.BytesIO(_fake_jpeg_bytes()), "image/jpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    shift = db_session.query(Shift).filter(Shift.user_id == colorist_a.id).one()
    photo_url = json.loads(shift.start_photos)[0]

    login_session(db_session, client, colorist_b)
    resp = client.get(photo_url)
    assert resp.status_code == 404
