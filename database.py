from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Задаем имя для базы данных
SQLALCHEMY_DATABASE_URL = "sqlite:///./crm_base.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ВОТ ОНО! Создаем базовый класс для всех моделей
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Импортируем модели СТРОГО ПОСЛЕ объявления Base,
# чтобы избежать ошибки цикличного импорта, и создаем таблицы
import models
Base.metadata.create_all(bind=engine)