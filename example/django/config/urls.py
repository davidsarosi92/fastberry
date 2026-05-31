from catalog import views
from django.urls import path

urlpatterns = [
    # Auto-derived schema via @fast_rest(depth=...), rendered by FastJSONRenderer.
    path("houses/", views.HouseList.as_view()),
    path("houses/<int:pk>/", views.HouseDetail.as_view()),
    # Explicit @fast_rest(fields=[...]) schema.
    path("stocks/", views.StockList.as_view()),
    # Hand-written FastRest registered with register_schema().
    path("products/", views.ProductList.as_view()),
    # Plain DRF endpoint (no @fast_rest) — proves the renderer falls back safely.
    path("plain-stocks/", views.PlainStockList.as_view()),
]
