import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

# Строка подключения к PostgreSQL
# Формат: postgresql://username:password@host:port/database_name
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:py@localhost:5432/colorbox"
)

# pool_pre_ping: перед выдачей соединения из пула шлёт лёгкий SELECT 1, чтобы поймать
# разорванное управляемым Postgres (или прокси/файрволом) неактивное соединение и
# прозрачно переоткрыть его — без этого первый запрос после простоя падает с
# OperationalError вместо того чтобы просто отработать чуть медленнее.
# pool_recycle: подстраховка на случай, если сама СУБД рвёт соединения по таймауту без
# уведомления клиента — пересоздаёт соединение, если оно "прожито" дольше часа.
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utc_now() -> datetime:
    """Текущее время в UTC, naive (единообразное хранение во всех DateTime-колонках без tz).

    Единственное место, где это вычисляется — models.py (дефолты колонок) и utils.py
    (переэкспортирует для роутеров) используют именно эту функцию, чтобы не разойтись
    в двух местах на одном и том же вычислении."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Фиксированный ключ для pg_advisory_lock ниже — произвольное число, важно только чтобы
# оно не совпадало с ключом, который использует под себя что-то ещё в этой же базе.
_SYNC_SCHEMA_LOCK_KEY = 727271_001

def sync_schema():
    """Создаёт отсутствующие таблицы и добавляет отсутствующие колонки по моделям.

    Безопасная авто-миграция для случая, когда код (models.py) обновился раньше,
    чем схема БД на сервере. Меняет только аддитивно: новые таблицы и новые
    nullable-колонки. Существующие колонки не трогает и не удаляет лишние.

    Выполняется под pg_advisory_lock на одном соединении: при нескольких воркерах
    uvicorn (--workers N) или нескольких инстансах приложения все они запускают
    sync_schema() параллельно при старте. Без блокировки они могут одновременно
    инспектировать схему, не увидеть чужих ALTER TABLE и словить гонку/дедлок на DDL.
    С блокировкой они просто выстраиваются в очередь; кто не первый — увидит, что
    колонки уже добавлены, и ничего не сделает.
    """
    import models  # noqa: F401 — регистрирует модели в Base.metadata

    with engine.connect() as conn:
        # execute() на свежем соединении сам открывает неявную транзакцию (SQLAlchemy 2.0
        # autobegin) — отдельный conn.begin() здесь не нужен и упадёт с InvalidRequestError.
        conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _SYNC_SCHEMA_LOCK_KEY})
        try:
            Base.metadata.create_all(bind=conn)

            inspector = inspect(conn)
            existing_tables = set(inspector.get_table_names())

            for table in Base.metadata.sorted_tables:
                if table.name not in existing_tables:
                    continue
                existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in existing_columns:
                        continue
                    col_type = column.type.compile(dialect=engine.dialect)
                    conn.execute(text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{column.name}" {col_type}'
                    ))
            conn.commit()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _SYNC_SCHEMA_LOCK_KEY})
            conn.commit()