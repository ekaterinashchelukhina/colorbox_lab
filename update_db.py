from models import Base
# Внимание: если твой engine создается в main.py, то вместо 'database' напиши 'main'
from database import engine

print("Подключение к базе данных...")
Base.metadata.create_all(bind=engine)
print("Все недостающие таблицы успешно созданы!")