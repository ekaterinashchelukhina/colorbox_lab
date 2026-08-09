import os
import sys

# Гарантируем, что корень проекта на sys.path независимо от того, как запущен pytest
# (bare `pytest`, `python -m pytest`, из другой рабочей директории и т.д.) — иначе
# `from models import ...` / `from tests.factories import ...` могут не найтись.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Направляем всё приложение (в т.ч. database.engine и lifespan/sync_schema, если вдруг
# сработает) на тестовую БД ещё до первого импорта database.py/main.py — чтобы тесты
# ни при каких обстоятельствах не задели боевую/локальную dev-базу.
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql://postgres:py@localhost:5432/colorbox_test"
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
import main

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Схема тестовой БД: создаём разово на весь прогон (см. README — colorbox_test
    нужно создать заранее командой `createdb colorbox_test`)."""
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db_session():
    """Каждый тест — в своей транзакции с rollback после теста: коммиты внутри
    роутов (db.commit()) не проливаются в реальную БД между тестами."""
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    def override_get_db():
        yield session

    main.app.dependency_overrides[get_db] = override_get_db
    try:
        yield session
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    # Без `with` — lifespan (и вызов sync_schema внутри него) не запускается,
    # схему готовит фикстура _schema через Base.metadata.create_all.
    return TestClient(main.app)
