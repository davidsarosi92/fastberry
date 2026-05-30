"""Tests for the @fast_rest decorator, registry, and DRF renderer.

Reuses the relational tree from test_rest.py's app (rest_test_app) but defines
its own models to keep decorator side effects isolated.
"""

from decimal import Decimal

import orjson
import pytest
from django.db import connection, models

from fastberry.rest import (
    FastRest,
    fast_rest,
    get_schema_for_model,
    register_schema,
)


# --- models -----------------------------------------------------------------

class Maker(models.Model):
    name = models.CharField(max_length=100)
    secret = models.CharField(max_length=100)

    class Meta:
        app_label = "rest_test_app"


@fast_rest(fields=["id", "name"])
class Brand(models.Model):
    name = models.CharField(max_length=100)
    secret = models.CharField(max_length=100)
    maker = models.ForeignKey(Maker, on_delete=models.CASCADE)

    class Meta:
        app_label = "rest_test_app"


@fast_rest(depth=1)
class Shelf(models.Model):
    code = models.CharField(max_length=50)

    class Meta:
        app_label = "rest_test_app"


class Item(models.Model):
    title = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    shelf = models.ForeignKey(Shelf, related_name="items", on_delete=models.CASCADE)

    class Meta:
        app_label = "rest_test_app"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    for m in (Maker, Brand, Shelf, Item):
        with connection.schema_editor() as se:
            se.create_model(m)

    mk = Maker.objects.create(name="MakerCo", secret="x")
    Brand.objects.create(name="Acme", secret="hidden", maker=mk)

    sh = Shelf.objects.create(code="A1")
    Item.objects.create(title="Widget", price=Decimal("3.50"), shelf=sh)
    Item.objects.create(title="Gadget", price=Decimal("7.00"), shelf=sh)
    yield


# --- explicit fields --------------------------------------------------------

def test_explicit_fields_registered():
    schema = get_schema_for_model(Brand)
    assert schema is not None
    assert Brand.__fast_schema__ is schema


def test_explicit_fields_only_emits_declared():
    schema = get_schema_for_model(Brand)
    rows = schema.serialize(Brand.objects.all())
    assert rows == [{"id": 1, "name": "Acme"}]
    # 'secret' and 'maker' are NOT leaked
    assert "secret" not in rows[0]
    assert "maker_id" not in rows[0]


def test_default_fields_when_omitted():
    # No fields/depth -> all concrete fields, FKs as ids.
    @fast_rest
    class PlainDefaults(models.Model):
        a = models.CharField(max_length=10)
        b = models.IntegerField()

        class Meta:
            app_label = "rest_test_app"

    schema = get_schema_for_model(PlainDefaults)
    assert set(schema._declared_fields) == {"id", "a", "b"}


# --- auto-derive depth ------------------------------------------------------

def test_auto_derive_expands_reverse_fk():
    schema = get_schema_for_model(Shelf)
    rows = schema.serialize(Shelf.objects.all())
    assert rows[0]["code"] == "A1"
    titles = sorted(i["title"] for i in rows[0]["items"])
    assert titles == ["Gadget", "Widget"]
    # Decimal handled in the nested level too
    assert all(isinstance(i["price"], str) for i in rows[0]["items"])


def test_auto_derive_depth_zero_no_nesting():
    @fast_rest(depth=0)
    class FlatShelf(models.Model):
        code = models.CharField(max_length=50)

        class Meta:
            app_label = "rest_test_app"

    schema = get_schema_for_model(FlatShelf)
    assert set(schema._declared_fields) == {"id", "code"}
    assert schema._nested == []


# --- register_schema (hand-written schema) ----------------------------------

def test_register_schema_manual():
    class MakerSchema(FastRest):
        class Meta:
            model = Maker
            fields = ["id", "name"]

    register_schema(Maker, MakerSchema)
    assert get_schema_for_model(Maker) is MakerSchema
    rows = get_schema_for_model(Maker).serialize(Maker.objects.all())
    assert rows == [{"id": 1, "name": "MakerCo"}]


# --- both styles rejected together ------------------------------------------

def test_depth_and_fields_conflict():
    with pytest.raises(TypeError):
        @fast_rest(depth=1, fields=["id"])
        class Bad(models.Model):
            class Meta:
                app_label = "rest_test_app"


# --- single object helpers --------------------------------------------------

def test_serialize_obj():
    schema = get_schema_for_model(Brand)
    obj = Brand.objects.first()
    assert schema.serialize_obj(obj) == {"id": 1, "name": "Acme"}
    assert orjson.loads(schema.serialize_obj_json(obj))["name"] == "Acme"