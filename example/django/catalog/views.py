"""DRF views returning raw querysets / instances.

No serializer wiring: ``FastJSONRenderer`` (set globally in settings) finds the
``@fast_rest`` / ``register_schema`` schema for the model and fast-serializes
it. The one plain endpoint proves unregistered data still renders via DRF.
"""

from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

# Importing schemas registers the hand-written ProductRest.
from catalog import schemas  # noqa: F401
from catalog.models import House, Product, Stock


class HouseList(APIView):
    def get(self, request):
        # House is @fast_rest(depth=3): the whole tree is fast-serialized.
        return Response(House.objects.all())


class HouseDetail(APIView):
    def get(self, request, pk):
        # Single instance -> the renderer calls serialize_obj_json under the hood.
        return Response(House.objects.get(pk=pk))


class StockList(APIView):
    def get(self, request):
        # Stock is @fast_rest(fields=[...]) -> only the declared columns emitted.
        return Response(Stock.objects.all())


class ProductList(APIView):
    def get(self, request):
        # Product uses the hand-written, register_schema'd ProductRest.
        return Response(Product.objects.all())


class PlainStockList(APIView):
    # Force the standard DRF renderer to show the safe fallback explicitly.
    renderer_classes = [JSONRenderer]

    def get(self, request):
        data = list(Stock.objects.values("id", "title", "amount"))
        return Response(data)
