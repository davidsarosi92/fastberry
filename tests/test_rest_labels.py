"""Tests for fastberry.rest label/expr/m2m field markers.

Covers LabelRef ({id,label} forward FK), Expr (DB-expression column), and
M2MLabels (capped, set-based many-to-many) — all without materializing model
instances. Uses a small tree with a many-to-many so query counts can be
asserted (no N+1).
"""

from decimal import Decimal

import pytest
from django.conf import settings
from django.db import connection, models
from django.db.models import F, Value
from django.db.models.functions import Concat
from django.test.utils import CaptureQueriesContext

from fastberry.rest import Expr, FastRest, LabelRef, M2MLabels

# --- models (fake app "rest_test_app") --------------------------------------


class LblCategory(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "rest_test_app"


class LblTag(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "rest_test_app"


class LblStock(models.Model):
    title = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.ForeignKey(
        LblCategory, null=True, related_name="stocks", on_delete=models.SET_NULL
    )
    tags = models.ManyToManyField(LblTag, related_name="stocks")

    class Meta:
        app_label = "rest_test_app"


# --- schemas ----------------------------------------------------------------


class StockLabelSchema(FastRest):
    category = LabelRef(label="name")  # {"id", "label"} or None
    title_bang = Expr(Concat("title", Value("!")))
    double_price = Expr(F("price") * Value(Decimal("2")), decimal=True)
    tags = M2MLabels(label="name", cap=2)

    class Meta:
        model = LblStock
        fields = ["id", "title", "price"]


# --- fixtures ---------------------------------------------------------------


@pytest.fixture(scope="module")
def lbl_data(django_db_blocker=None):
    for m in (LblCategory, LblTag, LblStock):
        # create_model also creates the model's m2m through tables.
        with connection.schema_editor() as se:
            se.create_model(m)

    beers = LblCategory.objects.create(name="Beers")

    t_red = LblTag.objects.create(name="red")
    t_new = LblTag.objects.create(name="new")
    t_sale = LblTag.objects.create(name="sale")

    s1 = LblStock.objects.create(title="A", price=Decimal("9.99"), category=beers)
    s1.tags.set([t_red, t_new, t_sale])  # 3 tags -> capped at 2 (+1 more)

    s2 = LblStock.objects.create(title="B", price=Decimal("1.50"), category=None)
    s2.tags.set([t_red])

    yield


# --- tests ------------------------------------------------------------------


def test_label_ref_shape_and_null(lbl_data):
    rows = {r["title"]: r for r in StockLabelSchema.serialize(LblStock.objects.order_by("id"))}
    assert rows["A"]["category"] == {"id": 1, "label": "Beers"}
    # null FK -> None
    assert rows["B"]["category"] is None
    # helper columns are stripped
    assert "category_id" not in rows["A"]
    assert "category__name" not in rows["A"]


def test_expr_columns(lbl_data):
    rows = {r["title"]: r for r in StockLabelSchema.serialize(LblStock.objects.all())}
    assert rows["A"]["title_bang"] == "A!"
    # decimal expr stringified like declared decimals (value comparison avoids
    # depending on the backend's numeric formatting, e.g. SQLite trailing zeros)
    assert isinstance(rows["A"]["double_price"], str)
    assert Decimal(rows["A"]["double_price"]) == Decimal("19.98")


def test_m2m_capped(lbl_data):
    rows = {r["title"]: r for r in StockLabelSchema.serialize(LblStock.objects.all())}
    tags_a = rows["A"]["tags"]
    assert len(tags_a) == 3  # 2 labels + "+1 more" marker
    assert tags_a[-1] == {"id": None, "label": "+1 more"}
    assert all("id" in t and "label" in t for t in tags_a)
    # uncapped row
    assert rows["B"]["tags"] == [{"id": 1, "label": "red"}]


def test_m2m_uncapped_when_cap_none(lbl_data):
    class _Uncapped(FastRest):
        tags = M2MLabels(label="name", cap=None)

        class Meta:
            model = LblStock
            fields = ["id"]

    rows = {r["id"]: r for r in _Uncapped.serialize(LblStock.objects.all())}
    assert len(rows[1]["tags"]) == 3  # all three, no marker
    assert {t["label"] for t in rows[1]["tags"]} == {"red", "new", "sale"}


def test_no_n_plus_one_with_markers(lbl_data):
    settings.DEBUG = True
    try:
        with CaptureQueriesContext(connection) as ctx:
            StockLabelSchema.serialize(LblStock.objects.all())
        # 1 query for the stock rows (with LabelRef join + Expr annotations) +
        # 1 query for the m2m through table = 2. No growth with row count.
        assert len(ctx.captured_queries) == 2, [q["sql"] for q in ctx.captured_queries]
    finally:
        settings.DEBUG = False