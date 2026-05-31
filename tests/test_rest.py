"""Tests for fastberry.rest — read-only nested serialization.

Uses a real in-memory SQLite database and a small relational tree
(House -> Space -> Stock -> Product) to verify correctness, query counts
(no N+1), and type handling (Decimal).
"""

from decimal import Decimal

import pytest
from django.conf import settings
from django.db import connection, models
from django.test.utils import CaptureQueriesContext

from fastberry.rest import FastRest

# --- models (fake app "rest_test_app") --------------------------------------


class Product(models.Model):
    name = models.CharField(max_length=100)
    ean = models.CharField(max_length=32)

    class Meta:
        app_label = "rest_test_app"


class House(models.Model):
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=200)

    class Meta:
        app_label = "rest_test_app"


class Space(models.Model):
    name = models.CharField(max_length=100)
    house = models.ForeignKey(House, related_name="spaces", on_delete=models.CASCADE)

    class Meta:
        app_label = "rest_test_app"


class Stock(models.Model):
    title = models.CharField(max_length=200)
    amount = models.FloatField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    space = models.ForeignKey(Space, related_name="stocks", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    class Meta:
        app_label = "rest_test_app"


# --- schemas ----------------------------------------------------------------


class ProductSchema(FastRest):
    class Meta:
        model = Product
        fields = ["id", "name", "ean"]


class StockSchema(FastRest):
    product = ProductSchema()

    class Meta:
        model = Stock
        fields = ["id", "title", "amount", "price"]


class SpaceSchema(FastRest):
    stocks = StockSchema(many=True)

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
def db_data(django_db_blocker=None):
    for m in (Product, House, Space, Stock):
        with connection.schema_editor() as se:
            se.create_model(m)

    p1 = Product.objects.create(name="Vodka", ean="111")
    p2 = Product.objects.create(name="Gin", ean="222")

    h1 = House.objects.create(name="Bar One", address="Main St 1")
    h2 = House.objects.create(name="Bar Two", address="Main St 2")

    s1 = Space.objects.create(name="Counter", house=h1)
    s2 = Space.objects.create(name="Storage", house=h1)
    _s3 = Space.objects.create(name="Cellar", house=h2)

    Stock.objects.create(title="A", amount=1.5, price=Decimal("9.99"), space=s1, product=p1)
    Stock.objects.create(title="B", amount=2.5, price=Decimal("19.50"), space=s1, product=p2)
    Stock.objects.create(title="C", amount=3.0, price=Decimal("5.00"), space=s2, product=p1)
    # h2/s3 has no stocks -> empty list expected

    yield
    # in-memory db is discarded with the connection


# --- tests ------------------------------------------------------------------


def test_flat_serialize(db_data):
    rows = ProductSchema.serialize(Product.objects.order_by("id"))
    assert rows == [
        {"id": 1, "name": "Vodka", "ean": "111"},
        {"id": 2, "name": "Gin", "ean": "222"},
    ]


def test_decimal_becomes_string(db_data):
    rows = StockSchema.serialize(Stock.objects.filter(title="A"))
    assert rows[0]["price"] == "9.99"
    assert isinstance(rows[0]["price"], str)


def test_forward_fk_nested(db_data):
    rows = StockSchema.serialize(Stock.objects.filter(title="A"))
    assert rows[0]["product"] == {"id": 1, "name": "Vodka", "ean": "111"}


def test_reverse_fk_nested_and_empty(db_data):
    houses = {h["name"]: h for h in HouseSchema.serialize(House.objects.all())}

    bar_one = houses["Bar One"]
    space_names = sorted(s["name"] for s in bar_one["spaces"])
    assert space_names == ["Counter", "Storage"]

    # Bar Two has a space but no stocks -> empty stock lists, not missing.
    bar_two = houses["Bar Two"]
    assert len(bar_two["spaces"]) == 1
    assert bar_two["spaces"][0]["stocks"] == []


def test_deep_tree_shape(db_data):
    houses = {h["name"]: h for h in HouseSchema.serialize(House.objects.all())}
    counter = next(s for s in houses["Bar One"]["spaces"] if s["name"] == "Counter")
    titles = sorted(st["title"] for st in counter["stocks"])
    assert titles == ["A", "B"]
    # nested product survives 4 levels deep
    stock_a = next(st for st in counter["stocks"] if st["title"] == "A")
    assert stock_a["product"]["name"] == "Vodka"
    # helper keys (space_id, product_id, pk where undeclared) are stripped
    assert set(stock_a.keys()) == {"id", "title", "amount", "price", "product"}


def test_no_n_plus_one(db_data):
    settings.DEBUG = True
    try:
        with CaptureQueriesContext(connection) as ctx:
            HouseSchema.serialize(House.objects.all())
        # One query per level: House, Space, Stock, Product = 4. No growth with
        # row count -> no N+1.
        assert len(ctx.captured_queries) == 4, [q["sql"] for q in ctx.captured_queries]
    finally:
        settings.DEBUG = False


def test_serialize_json_bytes(db_data):
    import orjson

    body = ProductSchema.serialize_json(Product.objects.order_by("id"))
    assert isinstance(body, bytes)
    assert orjson.loads(body)[0]["name"] == "Vodka"
