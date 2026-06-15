"""Tests for fastberry.list_provider.ListProvider.

The provider compiles a duck-typed field plan to a FastRest and serializes pages
of {id,label} / capped-m2m rows — the integration surface a host admin layer
plugs into without importing fastberry types.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import connection, models

from fastberry.list_provider import ListProvider

APP = "rest_test_app"


class LPCategory(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = APP


class LPTag(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = APP


class LPStock(models.Model):
    title = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.ForeignKey(LPCategory, null=True, on_delete=models.SET_NULL)
    tags = models.ManyToManyField(LPTag)

    class Meta:
        app_label = APP


def _plan():
    return SimpleNamespace(
        model=LPStock,
        pk_name="id",
        scalar_fields=["id", "title", "price"],
        fk_labels=[("category", "name")],
        m2m_labels=[("tags", "name", 2)],
    )


@pytest.fixture(scope="module")
def data(django_db_blocker=None):
    for m in (LPCategory, LPTag, LPStock):
        with connection.schema_editor() as se:
            se.create_model(m)
    c = LPCategory.objects.create(name="Beers")
    t1 = LPTag.objects.create(name="red")
    t2 = LPTag.objects.create(name="new")
    t3 = LPTag.objects.create(name="sale")
    s1 = LPStock.objects.create(title="A", price=Decimal("9.99"), category=c)
    s1.tags.set([t1, t2, t3])
    LPStock.objects.create(title="B", price=Decimal("1.50"), category=None)
    yield


def test_provider_serializes_plan(data):
    rows = {
        r["title"]: r
        for r in ListProvider().serialize_page(_plan(), LPStock.objects.order_by("pk"))
    }
    assert rows["A"]["category"] == {"id": 1, "label": "Beers"}
    assert rows["B"]["category"] is None
    assert rows["A"]["price"] == "9.99"  # decimal stringified
    assert rows["A"]["tags"][-1] == {"id": None, "label": "+1 more"}  # capped at 2
    assert rows["B"]["tags"] == []


def test_provider_caches_schema_per_model(data):
    p = ListProvider()
    plan = _plan()
    p.serialize_page(plan, LPStock.objects.all())
    assert plan.model in p._cache
    schema_first = p._cache[plan.model]
    p.serialize_page(plan, LPStock.objects.all())
    assert p._cache[plan.model] is schema_first  # not rebuilt
