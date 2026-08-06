from database import engine
from models import Base

print("Подключаемся к PostgreSQL...")

# Эта команда создает таблицы, если их еще нет
Base.metadata.create_all(bind=engine)

print("Успех! Все таблицы успешно созданы в базе colorist_crm.")