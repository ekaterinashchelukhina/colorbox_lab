from models import Client as ClientModel
from tests.factories import make_branch, make_user, make_client, make_order, login_session


def test_pagination_link_urlencodes_search_query(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    login_session(db_session, client, manager)

    # 51 клиентов, чтобы гарантированно получить вторую страницу (page_size=50)
    for i in range(51):
        make_client(db_session, branch, name=f"Иванов #{i}")

    resp = client.get("/clients", params={"q": "Иванов #"})
    assert resp.status_code == 200
    # '#' в свободном поиске должен быть закодирован (%23) в самой ссылке (& экранируется
    # Jinja2 автоматически как &amp; — это отдельно от URL-кодирования), иначе браузер
    # обрежет всё после него как фрагмент URL и потеряет остальные параметры пагинации
    assert "q=%D0%98%D0%B2%D0%B0%D0%BD%D0%BE%D0%B2%20%23&amp;branch_id=" in resp.text
    assert "q=Иванов #&amp;branch_id=" not in resp.text


def test_only_manager_can_create_client(client, db_session):
    branch = make_branch(db_session)
    director = make_user(db_session, role="Директор", branch=None)
    login_session(db_session, client, director)

    resp = client.get("/new-client", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/clients"

    resp = client.post("/new-client", data={"client_name": "Клиент директора", "branch_id": branch.id},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert db_session.query(ClientModel).filter(ClientModel.name == "Клиент директора").first() is None


def test_manager_can_create_client(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    login_session(db_session, client, manager)

    resp = client.post("/new-client", data={"client_name": "Новый клиент", "branch_id": branch.id},
                       follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/clients"
    created = db_session.query(ClientModel).filter(ClientModel.name == "Новый клиент").first()
    assert created is not None
    assert created.branch_id == branch.id


def test_client_history_filtered_by_service_type_and_date(client, db_session):
    branch = make_branch(db_session)
    manager = make_user(db_session, role="Менеджер", branch=branch)
    login_session(db_session, client, manager)

    client_obj = make_client(db_session, branch)
    order_podbor = make_order(db_session, branch, client_obj, service_type="Подбор", paint_code="PODBOR-1")
    order_sliv = make_order(db_session, branch, client_obj, service_type="Слив по коду", paint_code="SLIV-1")

    resp = client.get(f"/client/{client_obj.id}")
    assert order_podbor.paint_code in resp.text
    assert order_sliv.paint_code in resp.text

    resp = client.get(f"/client/{client_obj.id}?service_type=Подбор")
    assert order_podbor.paint_code in resp.text
    assert order_sliv.paint_code not in resp.text

    resp = client.get(f"/client/{client_obj.id}?date_from=2099-01-01")
    assert order_podbor.paint_code not in resp.text
    assert order_sliv.paint_code not in resp.text
