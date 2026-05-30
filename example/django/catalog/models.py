"""Domain models + fastberry.rest wiring.

Shared shape across all examples: House -> Space -> Stock -> Product.

This module demonstrates the three ``@fast_rest`` styles described in the
README, plus a hand-written ``FastRest`` registered explicitly (in
``schemas.py``).
"""

from django.db import models

from fastberry.rest import fast_rest


class Product(models.Model):
    name = models.CharField(max_length=100)
    ean = models.CharField(max_length=32)
    # A column we do NOT want leaking through auto-derive — see Stock below.
    cost_secret = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self) -> str:
        return self.name


class House(models.Model):
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.name


class Space(models.Model):
    name = models.CharField(max_length=100)
    house = models.ForeignKey(House, related_name="spaces", on_delete=models.CASCADE)


class Stock(models.Model):
    title = models.CharField(max_length=200)
    amount = models.FloatField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    space = models.ForeignKey(Space, related_name="stocks", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)


# --- fastberry.rest registration --------------------------------------------
#
# House: auto-derive the whole tree, expanding 3 relation levels
# (House -> Space -> Stock -> Product). FKs become nested objects, reverse FKs
# become nested lists. Convenient, but emits *every* field at each level.
fast_rest(depth=3)(House)

# Stock: explicit field list. Note we deliberately expose only product_id here,
# not the full Product (which carries cost_secret). Use the explicit form on
# models that have sensitive columns.
fast_rest(fields=["id", "title", "amount", "price", "product_id"])(Stock)

# Product gets a hand-written nested FastRest registered in schemas.py instead,
# so it can pick the safe columns explicitly.
