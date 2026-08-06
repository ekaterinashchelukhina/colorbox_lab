import sqlite3
from database import SessionLocal
from models import User


def set_boss_token():
    db = SessionLocal()
    try:
        # Ищем пользователя с логином boss
        boss = db.query(User).filter(User.username == "boss").first()

        if boss:
            new_token = "admin_token_123"
            boss.token = new_token
            db.commit()
            print(f"✅ Успешно! Токен для директора (boss) установлен: {new_token}")
        else:
            print("❌ Ошибка: Пользователь с логином 'boss' не найден в базе.")

            # Посмотрим, кто вообще есть в базе
            users = db.query(User).all()
            print(f"👥 Доступные пользователи в базе: {[u.username for u in users]}")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    set_boss_token()