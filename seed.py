from database import SessionLocal
from models import Branch, User
from passlib.context import CryptContext

# Настройка шифрования
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def seed_data():
    db = SessionLocal()

    # Проверяем, не заполнена ли уже база, чтобы не плодить клонов
    if db.query(Branch).first():
        print("В базе уже есть данные! Скрипт остановлен.")
        db.close()
        return

    # 1. Создаем первый филиал
    first_branch = Branch(name="Главная лаборатория (Уфа)")
    db.add(first_branch)
    db.commit()
    db.refresh(first_branch)  # Получаем ID только что созданного филиала

    # 2. Создаем учетную запись Директора
    hashed_password = pwd_context.hash("admin123")  # Надежно шифруем пароль
    director = User(
        username="director",
        password_hash=hashed_password,
        role="director",
        branch_id=first_branch.id
    )
    db.add(director)
    db.commit()

    print(f"Успех! Создан филиал: {first_branch.name}")
    print(f"Создан пользователь: логин 'director', пароль 'admin123' (зашифрован)")
    db.close()


if __name__ == "__main__":
    seed_data()