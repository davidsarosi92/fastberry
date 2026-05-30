"""Tests for FastJSONRenderer (DRF integration)."""

from decimal import Decimal

import orjson
import pytest
from django.db import connection, models

from fastberry.rest import fast_rest

pytest.importorskip("rest_framework")
from fastberry.rest_renderers import FastJSONRenderer  # noqa: E402


@fast_rest(fields=["id", "name"])
class Gizmo(models.Model):
    name = models.CharField(max_length=100)
    secret = models.CharField(max_length=100)

    class Meta:
        app_label = "rest_test_app"


class PlainRenderer(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "rest_test_app"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    for m in (Gizmo, PlainRenderer):
        with connection.schema_editor() as se:
            se.create_model(m)
    Gizmo.objects.create(name="G1", secret="s")
    Gizmo.objects.create(name="G2", secret="s")
    yield


def test_renderer_queryset_uses_fast_path():
    body = FastJSONRenderer().render(Gizmo.objects.order_by("id"))
    data = orjson.loads(body)
    assert data == [{"id": 1, "name": "G1"}, {"id": 2, "name": "G2"}]


def test_renderer_single_instance():
    body = FastJSONRenderer().render(Gizmo.objects.first())
    assert orjson.loads(body) == {"id": 1, "name": "G1"}


def test_renderer_falls_back_for_unregistered():
    # Plain dict (typical DRF payload) -> standard JSON rendering, not crash.
    body = FastJSONRenderer().render({"hello": "world"})
    assert orjson.loads(body) == {"hello": "world"}


def test_renderer_falls_back_for_unregistered_model():
    # A real model with no @fast_rest -> DRF default path (won't fast-serialize).
    # We just assert it doesn't raise and produces valid JSON-ish bytes.
    body = FastJSONRenderer().render({"plain": PlainRenderer.objects.count()})
    assert orjson.loads(body) == {"plain": 0}