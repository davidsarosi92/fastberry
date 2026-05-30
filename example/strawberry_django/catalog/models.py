"""Domain models. Same shape as the other examples.

``Product`` is decorated with ``@fast_schema`` to show the *model-driven* API:
fastberry generates a fast-pathed ``strawberry_django`` type from the model's
fields and stashes it on ``Product.__fast_type__``. The remaining types are
hand-written with the combined ``fast_strawberry_django.type`` decorator in
``schema.py``.
"""

from django.db import models

from fastberry.strawberry_django import fast_schema


@fast_schema(fields=["id", "name", "ean"], name="ProductType")
class Product(models.Model):
    name = models.CharField(max_length=100)
    ean = models.CharField(max_length=32)

    def __str__(self) -> str:
        return self.name


class House(models.Model):
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=200)


class Space(models.Model):
    name = models.CharField(max_length=100)
    house = models.ForeignKey(House, related_name="spaces", on_delete=models.CASCADE)


class Stock(models.Model):
    title = models.CharField(max_length=200)
    amount = models.FloatField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    space = models.ForeignKey(Space, related_name="stocks", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
