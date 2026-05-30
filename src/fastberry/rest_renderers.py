"""DRF renderer that uses fastberry.rest for ``@fast_rest`` models.

Drop ``FastJSONRenderer`` onto a view (or set it globally) and return a raw
queryset / model instance from the view. If the underlying model is registered
with :func:`fastberry.rest.fast_rest`, the response is serialized via the fast
``.values()``-based path and encoded with ``orjson``. Anything else falls back
to DRF's normal JSON rendering.

This keeps the optional DRF dependency out of ``fastberry.rest`` itself; import
this module only where DRF is available.

Usage::

    from fastberry.rest import fast_rest
    from fastberry.rest_renderers import FastJSONRenderer

    @fast_rest(depth=2)
    class House(models.Model): ...

    class HouseList(APIView):
        renderer_classes = [FastJSONRenderer]
        def get(self, request):
            return Response(House.objects.all())
"""

from django.db.models import Model, QuerySet
from rest_framework.renderers import JSONRenderer

from fastberry.rest import get_schema_for_model

__all__ = ["FastJSONRenderer"]


class FastJSONRenderer(JSONRenderer):
    media_type = "application/json"
    format = "json"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        schema, payload_is_list = self._resolve(data)
        if schema is not None:
            if payload_is_list:
                return schema.serialize_json(data)
            return schema.serialize_obj_json(data)
        # Not a fast_rest model -> standard DRF JSON.
        return super().render(data, accepted_media_type, renderer_context)

    @staticmethod
    def _resolve(data):
        """Return (schema, is_list) if ``data`` maps to a @fast_rest model."""
        if isinstance(data, QuerySet):
            return get_schema_for_model(data.model), True
        if isinstance(data, Model):
            return get_schema_for_model(type(data)), False
        return None, False