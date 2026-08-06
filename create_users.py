import os
from database import engine, Base, SessionLocal
from models import User, Branch
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Удаляем старую базу для чистой инициализации
if os.path.exists("crm_base.db"):
    os.remove("crm_base.db")

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# 1. Создаем два филиала
branch_1 = Branch(name="Уфа (Центральный)")
branch_2 = Branch(name="Уфа (Южный)")
db.add_all([branch_1, branch_2])
db.commit()

# 2. Создаем аккаунт Директора (без привязки к филиалу)
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

print("База успешно создана!")
print("🔑 Доступы:")
print("Директор (Видит всё): boss / 123")
print("Менеджер Центрального: manager1 / 123")
print("Менеджер Южного: manager2 / 123")