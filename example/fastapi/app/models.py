"""SQLAlchemy models. Same shape as the other examples.

This is the realistic FastAPI pairing — FastAPI ships no ORM, and SQLAlchemy is
the de-facto choice. fastberry.rest introspects these mapped classes through its
SQLAlchemy backend exactly the way it does Django models.
"""

from decimal import Decimal

from sqlalchemy import Float, ForeignKey, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "product"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    ean: Mapped[str] = mapped_column(String(32))


class House(Base):
    __tablename__ = "house"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(200))
    spaces: Mapped[list["Space"]] = relationship(back_populates="house")


class Space(Base):
    __tablename__ = "space"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    house_id: Mapped[int] = mapped_column(ForeignKey("house.id"))
    house: Mapped[House] = relationship(back_populates="spaces")
    stocks: Mapped[list["Stock"]] = relationship(back_populates="space")


class Stock(Base):
    __tablename__ = "stock"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    space_id: Mapped[int] = mapped_column(ForeignKey("space.id"))
    space: Mapped[Space] = relationship(back_populates="stocks")
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    product: Mapped[Product] = relationship()
