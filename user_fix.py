from database import SessionLocal
from models import Branch, User
from passlib.context import CryptContext

db = SessionLocal()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 1. Находим тот самый филиал, который успел создаться
branch = db.query(Branch).first()

# 2. Проверяем, есть ли директор
director = db.query(User).filter(User.username == "director").first()

if not director:
    print("Директора нет в базе! Создаем...")
    hashed_password = pwd_context.hash("admin123")

    new_director = User(
        username="director",
        password_hash=hashed_password,
        role="director",
        branch_id=branch.id
    )
    db.add(new_director)
    db.commit()
    print("Успех! Директор с паролем admin123 успешно добавлен.")
else:
    print("Директор уже есть в базе.")

db.close()