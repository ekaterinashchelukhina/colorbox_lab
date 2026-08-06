from database import SessionLocal
from models import Branch, User, Client, Order
from datetime import datetime, timedelta, timezone

db = SessionLocal()

# Находим наш филиал и директора
branch = db.query(Branch).first()
manager = db.query(User).filter_by(username="director").first()

# 1. Создаем клиента
client = Client(name="Иван Тестовый", phone="+79991234567", branch_id=branch.id)
db.add(client)
db.commit()
db.refresh(client)

# 2. Создаем заказ на краску
order = Order(
    branch_id=branch.id,
    client_id=client.id,
    manager_id=manager.id,
    car="Toyota Camry",
    detail="Бампер передний",
    paint_code="070 (Белый перламутр)",
    category="Перламутр",
    service_type="Подбор",
    target_volume=0.3, # 300 грамм
    price=2500.0,
    deadline_at=datetime.now(timezone.utc) + timedelta(days=1)
)
db.add(order)
db.commit()

print("Успех! Тестовый клиент и заказ добавлены в базу.")
db.close()