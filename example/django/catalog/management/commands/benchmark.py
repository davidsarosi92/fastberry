"""Compare fastberry.rest against DRF's nested ModelSerializer.

    python manage.py benchmark

Serializes the full House -> Space -> Stock -> Product tree three ways and
reports wall time + query count for each:

  1. DRF nested ModelSerializer, no prefetch  (the naive N+1 baseline)
  2. DRF nested ModelSerializer, with prefetch
  3. fastberry.rest (auto-derived @fast_rest schema)

Run `python manage.py seed` first.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext
from rest_framework import serializers

from catalog.models import House, Product, Space, Stock
from fastberry.rest import get_schema_for_model


# --- DRF nested serializers (the thing we are comparing against) ------------

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "ean"]


class StockSerializer(serializers.ModelSerializer):
    product = ProductSerializer()

    class Meta:
        model = Stock
        fields = ["id", "title", "amount", "price", "product"]


class SpaceSerializer(serializers.ModelSerializer):
    stocks = StockSerializer(many=True)

    class Meta:
        model = Space
        fields = ["id", "name", "stocks"]


class HouseSerializer(serializers.ModelSerializer):
    spaces = SpaceSerializer(many=True)

    class Meta:
        model = House
        fields = ["id", "name", "address", "spaces"]


def _measure(label, fn):
    reset_queries()
    with CaptureQueriesContext(connection) as ctx:
        # best of 3
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            fn()
            best = min(best, time.perf_counter() - start)
    return label, best * 1000, len(ctx.captured_queries)


def _drf_no_prefetch():
    HouseSerializer(House.objects.all(), many=True).data


def _drf_prefetch():
    qs = House.objects.prefetch_related("spaces__stocks__product")
    HouseSerializer(qs, many=True).data


def _fastberry():
    schema = get_schema_for_model(House)
    schema.serialize_json(House.objects.all())


class Command(BaseCommand):
    help = "Benchmark fastberry.rest vs DRF nested serializers."

    def handle(self, *args, **opts):
        if not House.objects.exists():
            self.stderr.write("No data. Run `python manage.py seed` first.")
            return

        # DEBUG must be on for query capture to record SQL.
        prev = settings.DEBUG
        settings.DEBUG = True
        try:
            results = [
                _measure("DRF nested, no prefetch", _drf_no_prefetch),
                _measure("DRF nested, with prefetch", _drf_prefetch),
                _measure("fastberry.rest", _fastberry),
            ]
        finally:
            settings.DEBUG = prev

        baseline = next(ms for label, ms, _ in results if label.endswith("with prefetch"))
        self.stdout.write(f"\n{'approach':30s} {'min ms':>8s} {'queries':>8s} {'vs prefetch':>12s}")
        self.stdout.write("-" * 62)
        for label, ms, q in results:
            self.stdout.write(f"{label:30s} {ms:8.1f} {q:8d} {baseline / ms:11.1f}x")
