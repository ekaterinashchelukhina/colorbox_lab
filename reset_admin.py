from database import SessionLocal
from models import Branch, User
from passlib.context import CryptContext

db = SessionLocal()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Убеждаемся, что филиал точно есть
branch = db.query(Branch).first()
if not branch:
    branch = Branch(name="Главная лаборатория (Уфа)")
    db.add(branch)
    db.commit()
    db.refresh(branch)

# Ищем директора
director = db.query(User).filter(User.username == "director").first()

hashed_pw = pwd_context.hash("admin123")

if director:
    director.password_hash = hashed_pw
    print("Пользователь найден. Пароль принудительно сброшен на admin123!")
else:
    new_director = User(
        username="director",
        password_hash=hashed_pw,
        role="director",
        branch_id=branch.id
    )
    db.add(new_director)
    print("Пользователь не найден. Создан новый директор с паролем admin123!")

db.commit()
db.close()