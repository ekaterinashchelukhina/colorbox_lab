from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from database import Base


class Branch(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    users = relationship("User", back_populates="branch", cascade="all, delete-orphan")
    clients = relationship("Client", back_populates="branch", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="branch", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String, nullable=True)  # Больше не используется, сделано nullable
    role = Column(String)  # Менеджер, Колорист, Директор
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)  # Директору филиал не нужен

    # Поле для хранения токена входа и активной сессии
    token = Column(String, unique=True, index=True, nullable=True)

    branch = relationship("Branch", back_populates="users")


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
    colorist_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # <-- Добавлено поле колориста

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

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    deadline_at = Column(DateTime)
    issued_at = Column(DateTime, nullable=True)  # Точное время сдачи заказа (переход в статус "Выдано")

    branch = relationship("Branch", back_populates="orders")
    client = relationship("Client", back_populates="orders")

    # <-- Добавлены явные связи, чтобы SQLAlchemy понимала, кто менеджер, а кто колорист
    manager = relationship("User", foreign_keys=[manager_id])
    colorist = relationship("User", foreign_keys=[colorist_id])


class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    branch_id = Column(Integer, ForeignKey("branches.id"))

    start_time = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    start_photos = Column(String, nullable=True)  # Ссылки на утренние фото через запятую

    end_time = Column(DateTime, nullable=True)
    end_photos = Column(String, nullable=True)  # Ссылки на вечерние фото

    user = relationship("User")
    branch = relationship("Branch")