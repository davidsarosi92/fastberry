"""Populate the database with a deep relational tree.

    python manage.py seed --houses 200 --spaces 4 --stocks 8
"""

import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import House, Product, Space, Stock


class Command(BaseCommand):
    help = "Seed the catalog with a deep House -> Space -> Stock -> Product tree."

    def add_arguments(self, parser):
        parser.add_argument("--houses", type=int, default=200)
        parser.add_argument("--spaces", type=int, default=4)
        parser.add_argument("--stocks", type=int, default=8)
        parser.add_argument("--products", type=int, default=50)

    @transaction.atomic
    def handle(self, *args, **opts):
        rng = random.Random(42)

        self.stdout.write("Clearing existing data...")
        Stock.objects.all().delete()
        Space.objects.all().delete()
        House.objects.all().delete()
        Product.objects.all().delete()

        products = Product.objects.bulk_create(
            Product(name=f"Product {i}", ean=f"{4000000000000 + i}")
            for i in range(1, opts["products"] + 1)
        )

        houses = House.objects.bulk_create(
            House(name=f"House {i}", address=f"Main St {i}")
            for i in range(1, opts["houses"] + 1)
        )

        spaces = Space.objects.bulk_create(
            Space(name=f"Space {h.id}-{s}", house=h)
            for h in houses
            for s in range(opts["spaces"])
        )

        stocks = []
        for sp in spaces:
            for _ in range(opts["stocks"]):
                stocks.append(Stock(
                    title=f"Stock {len(stocks) + 1}",
                    amount=round(rng.uniform(0, 100), 2),
                    price=Decimal(f"{rng.uniform(1, 999):.2f}"),
                    space=sp,
                    product=rng.choice(products),
                ))
        Stock.objects.bulk_create(stocks)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(houses)} houses, {len(spaces)} spaces, "
            f"{len(stocks)} stocks, {len(products)} products."
        ))
