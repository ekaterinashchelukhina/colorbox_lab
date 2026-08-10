from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from database import Base, utc_now


class Branch(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    # Без cascade delete: филиал с сотрудниками/клиентами/заказами не должен исчезать
    # вместе с ними при удалении. Роут удаления филиала (routers/director.py) явно
    # отказывает в удалении, пока на филиале что-то есть.
    users = relationship("User", back_populates="branch")
    clients = relationship("Client", back_populates="branch")
    orders = relationship("Order", back_populates="branch")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String, nullable=True)  # Больше не используется, сделано nullable
    role = Column(String)  # Менеджер, Колорист, Директор
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)  # Директору филиал не нужен

    # Постоянный логин-токен сотрудника (аналог пароля, не меняется при входе)
    token = Column(String, unique=True, index=True, nullable=True)

    branch = relationship("Branch", back_populates="users")


class UserSession(Base):
    """Одна активная сессия входа. Отдельная таблица, а не колонка на User — один
    сотрудник может быть одновременно залогинен с телефона и с компьютера: раньше
    (session_token/session_expires_at прямо на User) второй вход тут же обнулял первый,
    и сессия "сама" вылетала на другом устройстве."""
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User")


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"))

    branch = relationship("Branch", back_populates="clients")
    orders = relationship("Order", back_populates="client", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    client_id = Column(Integer, ForeignKey("clients.id"))
    manager_id = Column(Integer, ForeignKey("users.id"))
    colorist_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    car = Column(String)
    detail = Column(String)
    paint_code = Column(String)
    category = Column(String)
    service_type = Column(String)
    target_volume = Column(Float)
    actual_volume = Column(Float, nullable=True)
    status = Column(String, default="В очереди")
    is_express = Column(Boolean, default=False)
    rework_count = Column(Integer, default=0)
    price = Column(Float, default=0.0)
    is_paid = Column(Boolean, default=False)

    # При удалении сотрудника (routers/director.py: delete_user) colorist_id обнуляется —
    # без снимка имени заказ, который реально кто-то делал, стал бы неотличим от заказа,
    # который вообще ещё никто не брал в работу (в обоих случаях colorist_id = None).
    colorist_deleted_name = Column(String, nullable=True)

    # Комментарии (ролевые примечания)
    manager_comment = Column(String, nullable=True)
    colorist_comment = Column(String, nullable=True)

    # Фотографии и даты
    photo_detail = Column(String, nullable=True)
    photo_scales = Column(String, nullable=True)
    photo_after = Column(String, nullable=True)
    recipe_photo = Column(String, nullable=True)  # Фото рецепта краски

    # Фотоконтроль доколеровки (заполняется заново при каждом возврате из архива)
    rework_photo_scales = Column(String, nullable=True)
    rework_photo_after = Column(String, nullable=True)
    rework_photo_test = Column(String, nullable=True)

    created_at = Column(DateTime, default=utc_now)
    deadline_at = Column(DateTime)
    issued_at = Column(DateTime, nullable=True)  # Точное время сдачи заказа (переход в статус "Выдано")

    branch = relationship("Branch", back_populates="orders")
    client = relationship("Client", back_populates="orders")

    # Явные foreign_keys обязательны: два FK на users.id (manager_id, colorist_id) —
    # без этого SQLAlchemy не может понять, какая связь к какой колонке относится.
    manager = relationship("User", foreign_keys=[manager_id])
    colorist = relationship("User", foreign_keys=[colorist_id])


class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    branch_id = Column(Integer, ForeignKey("branches.id"))

    start_time = Column(DateTime, default=utc_now)
    start_photos = Column(String, nullable=True)  # Ссылки на утренние фото через запятую

    end_time = Column(DateTime, nullable=True)
    end_photos = Column(String, nullable=True)  # Ссылки на вечерние фото

    user = relationship("User")
    branch = relationship("Branch")