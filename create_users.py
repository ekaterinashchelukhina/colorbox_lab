import os
from database import engine, Base, SessionLocal, DB_PATH
from models import User, Branch
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

print("🔄 Инициализация базы данных...")

# Удаляем старую базу, если она есть
if os.path.exists(DB_PATH):
    try:
        os.remove(DB_PATH)
        print("🗑 Старая база успешно удалена.")
    except Exception as e:
        print(f"⚠️ Не удалось удалить старую базу: {e}")

# Создаем таблицы
try:
    Base.metadata.create_all(bind=engine)
    print("🏗 Таблицы созданы.")
except Exception as e:
    print(f"❌ Ошибка создания таблиц: {e}")
    exit(1)

db = SessionLocal()

try:
    # 1. Создаем два филиала
    branch_1 = Branch(name="Уфа (Центральный)")
    branch_2 = Branch(name="Уфа (Южный)")
    db.add_all([branch_1, branch_2])
    db.commit()

    # 2. Создаем аккаунт Директора
    director = User(
        username="boss",
        password_hash=pwd_context.hash("123"),
        role="Директор"
    )
    db.add(director)

    # 3. Сотрудники Центрального филиала
    m1 = User(username="manager1", password_hash=pwd_context.hash("123"), role="Менеджер", branch_id=branch_1.id)
    c1 = User(username="colorist1", password_hash=pwd_context.hash("123"), role="Колорист", branch_id=branch_1.id)
    db.add_all([m1, c1])

    # 4. Сотрудники Южного филиала
    m2 = User(username="manager2", password_hash=pwd_context.hash("123"), role="Менеджер", branch_id=branch_2.id)
    c2 = User(username="colorist2", password_hash=pwd_context.hash("123"), role="Колорист", branch_id=branch_2.id)
    db.add_all([m2, c2])

    db.commit()

    print("\n✅ База успешно создана!")
    print("🔑 Доступы для входа:")
    print("   • Директор (Видит всё): boss / 123")
    print("   • Менеджер Уфы (Центр): manager1 / 123")
    print("   • Менеджер Уфы (Юг):     manager2 / 123")

except Exception as e:
    db.rollback()
    print(f"❌ Ошибка при добавлении пользователей: {e}")
finally:
    db.close()