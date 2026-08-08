import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Строка подключения к PostgreSQL
# Формат: postgresql://username:password@host:port/database_name
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:py@localhost:5432/colorbox"
)

# Для PostgreSQL аргумент check_same_thread не требуется
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sync_schema():
    """Создаёт отсутствующие таблицы и добавляет отсутствующие колонки по моделям.

    Безопасная авто-миграция для случая, когда код (models.py) обновился раньше,
    чем схема БД на сервере. Меняет только аддитивно: новые таблицы и новые
    nullable-колонки. Существующие колонки не трогает и не удаляет лишние.
    """
    import models  # noqa: F401 — регистрирует модели в Base.metadata

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{column.name}" {col_type}'))