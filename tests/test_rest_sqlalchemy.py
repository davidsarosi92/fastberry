"""Tests for the SQLAlchemy backend of fastberry.rest.

Mirrors test_rest.py's House -> Space -> Stock -> Product tree, but with
SQLAlchemy mapped classes and a real in-memory SQLite session, to verify the
backend produces the same shapes, the same query economy (no N+1), Decimal
handling, and the session-required behaviour.
"""

from decimal import Decimal

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import (  # noqa: E402
    Float,
    ForeignKey,
    Numeric,
    String,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import (  # noqa: E402
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

from fastberry.rest import FastRest, fast_rest, get_schema_for_model  # noqa: E402

# --- models -----------------------------------------------------------------


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


# --- schemas ----------------------------------------------------------------


class ProductSchema(FastRest):
    class Meta:
        model = Product
        fields = ["id", "name", "ean"]


class StockSchema(FastRest):
    product = ProductSchema()  # forward FK

    class Meta:
        model = Stock
        fields = ["id", "title", "amount", "price"]


class SpaceSchema(FastRest):
    stocks = StockSchema(many=True)  # reverse FK / one-to-many

    class Meta:
        model = Space
        fields = ["id", "name"]


class HouseSchema(FastRest):
    spaces = SpaceSchema(many=True)

    class Meta:
        model = House
        fields = ["id", "name", "address"]


# --- fixtures ---------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        p1 = Product(name="Vodka", ean="111")
        p2 = Product(name="Gin", ean="222")
        h1 = House(name="Bar One", address="Main St 1")
        h2 = House(name="Bar Two", address="Main St 2")
        s1 = Space(name="Counter", house=h1)
        s2 = Space(name="Storage", house=h1)
        s3 = Space(name="Cellar", house=h2)
        s.add_all([p1, p2, h1, h2, s1, s2, s3])
        s.add_all(
            [
                Stock(title="A", amount=1.5, price=Decimal("9.99"), space=s1, product=p1),
                Stock(title="B", amount=2.5, price=Decimal("19.50"), space=s1, product=p2),
                Stock(title="C", amount=3.0, price=Decimal("5.00"), space=s2, product=p1),
            ]
        )
        s.commit()
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


# --- tests ------------------------------------------------------------------


def test_flat_serialize(session):
    rows = ProductSchema.serialize(select(Product).order_by(Product.id), session=session)
    assert rows == [
        {"id": 1, "name": "Vodka", "ean": "111"},
        {"id": 2, "name": "Gin", "ean": "222"},
    ]


def test_serialize_all_rows_without_source(session):
    rows = ProductSchema.serialize(session=session)
    assert {r["name"] for r in rows} == {"Vodka", "Gin"}


def test_decimal_becomes_string(session):
    rows = StockSchema.serialize(select(Stock).where(Stock.title == "A"), session=session)
    assert rows[0]["price"] == "9.99"
    assert isinstance(rows[0]["price"], str)
    # Float stays a float
    assert rows[0]["amount"] == 1.5


def test_forward_fk_nested(session):
    rows = StockSchema.serialize(select(Stock).where(Stock.title == "A"), session=session)
    assert rows[0]["product"] == {"id": 1, "name": "Vodka", "ean": "111"}


def test_reverse_fk_nested_and_empty(session):
    houses = {h["name"]: h for h in HouseSchema.serialize(session=session)}

    bar_one = houses["Bar One"]
    assert sorted(s["name"] for s in bar_one["spaces"]) == ["Counter", "Storage"]

    bar_two = houses["Bar Two"]
    assert len(bar_two["spaces"]) == 1
    assert bar_two["spaces"][0]["stocks"] == []


def test_deep_tree_shape_and_helper_stripping(session):
    houses = {h["name"]: h for h in HouseSchema.serialize(session=session)}
    counter = next(s for s in houses["Bar One"]["spaces"] if s["name"] == "Counter")
    assert sorted(st["title"] for st in counter["stocks"]) == ["A", "B"]
    stock_a = next(st for st in counter["stocks"] if st["title"] == "A")
    assert stock_a["product"]["name"] == "Vodka"
    # helper keys (space_id, product_id, undeclared pk) are stripped
    assert set(stock_a.keys()) == {"id", "title", "amount", "price", "product"}


def test_no_n_plus_one(session):
    count = {"n": 0}

    @event.listens_for(session.bind, "after_cursor_execute")
    def _count(*args):
        count["n"] += 1

    try:
        HouseSchema.serialize(session=session)
    finally:
        event.remove(session.bind, "after_cursor_execute", _count)

    # One query per level: House, Space, Stock, Product = 4. No growth with rows.
    assert count["n"] == 4


def test_serialize_json_bytes(session):
    import orjson

    body = ProductSchema.serialize_json(select(Product).order_by(Product.id), session=session)
    assert isinstance(body, bytes)
    assert orjson.loads(body)[0]["name"] == "Vodka"


def test_serialize_obj(session):
    obj = session.get(Product, 1)
    assert ProductSchema.serialize_obj(obj, session=session) == {
        "id": 1,
        "name": "Vodka",
        "ean": "111",
    }


def test_missing_session_raises(engine):
    with pytest.raises(TypeError, match="session"):
        ProductSchema.serialize()


# --- @fast_rest on SQLAlchemy models ----------------------------------------


def test_fast_rest_explicit_fields_hides_columns(session):
    @fast_rest(fields=["id", "title"])
    class SecretStock(Base):
        __tablename__ = "secret_stock"
        id: Mapped[int] = mapped_column(primary_key=True)
        title: Mapped[str] = mapped_column(String(100))
        secret: Mapped[str] = mapped_column(String(100))

    Base.metadata.create_all(session.bind)
    session.add(SecretStock(title="visible", secret="hidden"))
    session.commit()

    schema = get_schema_for_model(SecretStock)
    rows = schema.serialize(session=session)
    assert rows == [{"id": 1, "title": "visible"}]
    assert "secret" not in rows[0]


def test_fast_rest_auto_derive_depth(session):
    schema = get_schema_for_model(House)  # not registered -> None
    assert schema is None

    @fast_rest(depth=2)
    class AutoHouse(Base):
        __tablename__ = "auto_house"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str] = mapped_column(String(100))
        rooms: Mapped[list["AutoRoom"]] = relationship(back_populates="house")

    class AutoRoom(Base):
        __tablename__ = "auto_room"
        id: Mapped[int] = mapped_column(primary_key=True)
        label: Mapped[str] = mapped_column(String(100))
        house_id: Mapped[int] = mapped_column(ForeignKey("auto_house.id"))
        house: Mapped[AutoHouse] = relationship(back_populates="rooms")

    Base.metadata.create_all(session.bind)
    h = AutoHouse(name="H1")
    h.rooms = [AutoRoom(label="R1"), AutoRoom(label="R2")]
    session.add(h)
    session.commit()

    schema = get_schema_for_model(AutoHouse)
    rows = schema.serialize(session=session)
    assert rows[0]["name"] == "H1"
    assert sorted(r["label"] for r in rows[0]["rooms"]) == ["R1", "R2"]
