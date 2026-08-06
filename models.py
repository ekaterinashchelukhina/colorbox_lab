from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from database import Base
import datetime


class Branch(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    users = relationship("User", back_populates="branch")
    clients = relationship("Client", back_populates="branch")
    orders = relationship("Order", back_populates="branch")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String)  # Менеджер, Колорист, Директор
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)  # Директору филиал не нужен

    branch = relationship("Branch", back_populates="users")


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"))

    branch = relationship("Branch", back_populates="clients")
    orders = relationship("Order", back_populates="client")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    client_id = Column(Integer, ForeignKey("clients.id"))
    manager_id = Column(Integer, ForeignKey("users.id"))

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

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    deadline_at = Column(DateTime, nullable=True)

    photo_detail = Column(String, nullable=True)
    photo_scales = Column(String, nullable=True)
    photo_after = Column(String, nullable=True)

    branch = relationship("Branch", back_populates="orders")
    client = relationship("Client", back_populates="orders")
    recipe_items = relationship("RecipeItem", back_populates="order")


class RecipeItem(Base):
    __tablename__ = "recipe_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    category = Column(String)
    toner_name = Column(String)
    weight = Column(Float)

    order = relationship("Order", back_populates="recipe_items")