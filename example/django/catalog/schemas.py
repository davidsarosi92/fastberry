"""Hand-written FastRest schemas registered explicitly.

Shows the third registration style: write a nested ``FastRest`` yourself and
register it with ``register_schema`` so ``FastJSONRenderer`` picks it up. This
is the way to expose a curated, safe subset of columns.
"""

from catalog.models import Product
from fastberry.rest import FastRest, register_schema


class ProductRest(FastRest):
    # Note: cost_secret is intentionally omitted.
    class Meta:
        model = Product
        fields = ["id", "name", "ean"]


register_schema(Product, ProductRest)
