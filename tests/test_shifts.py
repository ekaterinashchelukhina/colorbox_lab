import io

from models import Shift
from tests.factories import make_branch, make_user, make_client, make_order, login_session, error_text


def _fake_photo():
    # Не настоящий JPEG, но utils._compress_image открывает через PIL —
    # используем крошечный валидный PNG (PIL умеет читать PNG не хуже JPEG).
    import struct
    import zlib

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xffffffff
        )

    width, height = 1, 1
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"\x00" + b"\xff\x00\x00"
    idat = zlib.compress(raw)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return io.BytesIO(png)


def _photo_files(field="photos", count=4):
    return [(field, (f"p{i}.png", _fake_photo(), "image/png")) for i in range(count)]


def test_colorist_shift_start_requires_photos(client, db_session):
    colorist = make_user(db_session, role="Колорист")
    login_session(db_session, client, colorist)

    resp = client.post("/shift/start")

    assert resp.status_code == 422  # File(...) обязателен


def test_colorist_shift_start_and_end(client, db_session):
    colorist = make_user(db_session, role="Колорист")
    login_session(db_session, client, colorist)

    resp = client.post("/shift/start", files=_photo_files(), follow_redirects=False)
    assert resp.status_code == 303

    shift = db_session.query(Shift).filter(Shift.user_id == colorist.id).first()
    assert shift is not None
    assert shift.start_time is not None
    assert shift.end_time is None

    resp = client.post("/shift/end", files=_photo_files(), follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(shift)
    assert shift.end_time is not None


def test_manager_shift_start_end_without_photos(client, db_session):
    manager = make_user(db_session, role="Менеджер")
    login_session(db_session, client, manager)

    resp = client.post("/manager/shift/start", follow_redirects=False)
    assert resp.status_code == 303

    shift = db_session.query(Shift).filter(Shift.user_id == manager.id).first()
    assert shift is not None and shift.end_time is None

    resp = client.post("/manager/shift/end", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(shift)
    assert shift.end_time is not None


def test_manager_shift_endpoints_blocked_for_other_roles(client, db_session):
    colorist = make_user(db_session, role="Колорист")
    login_session(db_session, client, colorist)

    resp = client.post("/manager/shift/start", follow_redirects=False)
    assert resp.status_code == 303
    assert db_session.query(Shift).filter(Shift.user_id == colorist.id).count() == 0


def test_shift_start_rejects_non_image_file(client, db_session):
    colorist = make_user(db_session, role="Колорист")
    login_session(db_session, client, colorist)

    bad_file = io.BytesIO(b"this is not an image")
    resp = client.post("/shift/start", files=[("photos", ("not_a_photo.jpg", bad_file, "image/jpeg"))])

    assert "не является изображением" in error_text(resp)
    assert db_session.query(Shift).filter(Shift.user_id == colorist.id).count() == 0


def test_colorist_dashboard_has_single_logout_button(client, db_session):
    colorist = make_user(db_session, role="Колорист")
    login_session(db_session, client, colorist)

    resp = client.get("/colorist")

    assert resp.text.count('href="/logout"') == 1


def test_rework_order_visible_only_to_original_colorist(client, db_session):
    branch = make_branch(db_session)
    colorist_a = make_user(db_session, role="Колорист", branch=branch, username="colorist_a")
    colorist_b = make_user(db_session, role="Колорист", branch=branch, username="colorist_b")
    client_obj = make_client(db_session, branch)
    # Заказ вернулся из доколеровки: colorist_id остался с прошлого цикла работы,
    # статус — снова "В очереди" (см. send_order_to_rework).
    order = make_order(db_session, branch, client_obj, status="В очереди",
                       rework_count=1, colorist_id=colorist_a.id, paint_code="REWORK-1")

    login_session(db_session, client, colorist_a)
    client.post("/shift/start", files=_photo_files())
    resp_a = client.get("/colorist")
    assert "REWORK-1" in resp_a.text

    login_session(db_session, client, colorist_b)
    client.post("/shift/start", files=_photo_files())
    resp_b = client.get("/colorist")
    assert "REWORK-1" not in resp_b.text


def test_unclaimed_order_visible_to_any_colorist_on_shift(client, db_session):
    branch = make_branch(db_session)
    colorist = make_user(db_session, role="Колорист", branch=branch)
    client_obj = make_client(db_session, branch)
    make_order(db_session, branch, client_obj, status="В очереди", paint_code="FRESH-1")

    login_session(db_session, client, colorist)
    client.post("/shift/start", files=_photo_files())
    resp = client.get("/colorist")

    assert "FRESH-1" in resp.text


def test_new_order_blocked_without_active_manager_shift(client, db_session):
    manager = make_user(db_session, role="Менеджер")
    login_session(db_session, client, manager)

    resp = client.get("/new-order", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"

    resp = client.post("/new-order", data={
        "client_name": "Клиент", "car": "Kia", "detail": "Крыло",
        "service_type": "Слив по коду", "target_volume": "100", "deadline": "2026-12-31",
    })
    assert "Сначала начните смену" in error_text(resp)
