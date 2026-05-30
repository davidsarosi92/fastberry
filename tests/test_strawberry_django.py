"""Tests for the fast_strawberry_django wrapper decorators."""

import pytest
from django.db import models

pytest.importorskip("strawberry_django")

from fastberry import strawberry_django as fast_sd  # noqa: E402
from fastberry.strawberry_django import fast_schema  # noqa: E402
from fastberry.fastpath import FastPathExtension  # noqa: E402


class WrapStock(models.Model):
    title = models.CharField(max_length=100)
    amount = models.FloatField()

    class Meta:
        app_label = "rest_test_app"


def test_wrapper_applies_both_decorators():
    @fast_sd.type(WrapStock)
    class WrapStockType:
        id: int
        title: str

    # strawberry_django.type ran -> has the strawberry definition
    defn = WrapStockType.__strawberry_definition__
    assert defn is not None

    # fast_path ran -> the GraphQL type name is registered for fast resolution
    assert defn.name in FastPathExtension._fast_path_type_names


def test_wrapper_forwards_kwargs():
    # disable_optimization is a strawberry_django.type kwarg; it must pass through
    # without error, proving arguments are forwarded verbatim.
    @fast_sd.type(WrapStock, disable_optimization=True)
    class WrapStockType2:
        id: int

    assert WrapStockType2.__strawberry_definition__ is not None


def test_returns_the_class():
    @fast_sd.type(WrapStock)
    class WrapStockType3:
        id: int

    # decorator returns the (decorated) class, not a wrapper object
    assert isinstance(WrapStockType3, type)


# --- fast_schema: generate the type from the model --------------------------

def test_fast_schema_generates_and_fast_paths():
    @fast_schema
    class GenStockDecorated(models.Model):
        title = models.CharField(max_length=100)
        amount = models.FloatField()

        class Meta:
            app_label = "rest_test_app"

    gql = GenStockDecorated.__fast_type__
    defn = gql.__strawberry_definition__
    names = {f.name for f in defn.fields}
    assert {"id", "title", "amount"} <= names
    assert defn.name == "GenStockDecoratedType"
    assert defn.name in FastPathExtension._fast_path_type_names


def test_fast_schema_explicit_fields_and_name():
    @fast_schema(fields=["id", "title"], name="StockGql")
    class GenStock2(models.Model):
        title = models.CharField(max_length=100)
        secret = models.CharField(max_length=100)

        class Meta:
            app_label = "rest_test_app"

    defn = GenStock2.__fast_type__.__strawberry_definition__
    names = {f.name for f in defn.fields}
    assert names == {"id", "title"}
    assert "secret" not in names
    assert defn.name == "StockGql"


def test_fast_schema_returns_model():
    @fast_schema
    class GenStock3(models.Model):
        title = models.CharField(max_length=100)

        class Meta:
            app_label = "rest_test_app"

    assert issubclass(GenStock3, models.Model)
    assert hasattr(GenStock3, "__fast_type__")
