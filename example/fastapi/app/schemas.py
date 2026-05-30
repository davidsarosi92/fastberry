"""fastberry.rest schemas over the SQLAlchemy models.

Declaration is identical to the Django example — only the serialize() calls
differ (a SQLAlchemy session is threaded in; see app/main.py).
"""

from fastberry.rest import FastRest

from app.models import House, Product, Space, Stock


class ProductRest(FastRest):
    class Meta:
        model = Product
        fields = ["id", "name", "ean"]


class StockRest(FastRest):
    product = ProductRest()                # forward FK

    class Meta:
        model = Stock
        fields = ["id", "title", "amount", "price"]


class SpaceRest(FastRest):
    stocks = StockRest(many=True)          # reverse FK / one-to-many

    class Meta:
        model = Space
        fields = ["id", "name"]


class HouseRest(FastRest):
    spaces = SpaceRest(many=True)

    class Meta:
        model = House
        fields = ["id", "name", "address"]
