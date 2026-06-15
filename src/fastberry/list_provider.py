"""A pluggable list-serialization provider built on :mod:`fastberry.rest`.

This is the integration point for frameworks (e.g. an admin/CRUD layer) that want
fast, instance-free list rows without importing fastberry types directly. The
host passes a *field plan* — a plain object describing what each row should hold
— and this provider compiles it to a :class:`~fastberry.rest.FastRest` once and
serializes pages from it.

The plan is duck-typed (no import coupling either way); it must expose:

- ``model``         — the Django model class.
- ``pk_name``       — primary key field name (must also appear in ``scalar_fields``).
- ``scalar_fields`` — list of scalar column names to emit verbatim.
- ``fk_labels``     — list of ``(attr, label_field)``: a forward FK emitted as
                      ``{"id","label"}`` with ``label`` projected from
                      ``related.<label_field>``.
- ``m2m_labels``    — list of ``(attr, label_field, cap)``: a many-to-many emitted
                      as a capped ``[{"id","label"}, …]`` list (``cap`` may be None).

``serialize_page(plan, source)`` returns a list of dicts keyed by field name —
relation labels resolved, decimals stringified — leaving any further row shaping
(e.g. adding ``pk``/``__str__`` keys) to the caller.
"""

from __future__ import annotations

from typing import Any


class ListProvider:
    """Compiles field plans to FastRest schemas (cached per model) and serializes."""

    def __init__(self) -> None:
        self._cache: dict[type, Any] = {}

    def serialize_page(self, plan: Any, source: Any) -> list[dict[str, Any]]:
        return self._schema_for(plan).serialize(source)

    def _schema_for(self, plan: Any) -> Any:
        cached = self._cache.get(plan.model)
        if cached is not None:
            return cached

        from fastberry.rest import FastRest, FastRestMeta, LabelRef, M2MLabels

        namespace: dict[str, Any] = {}
        for attr, label_field in plan.fk_labels:
            namespace[attr] = LabelRef(attr, label=label_field)
        for attr, label_field, cap in plan.m2m_labels:
            namespace[attr] = M2MLabels(attr, label=label_field, cap=cap)
        namespace["Meta"] = type(
            "Meta", (), {"model": plan.model, "fields": list(plan.scalar_fields)}
        )
        schema = FastRestMeta(f"_ListProvider{plan.model.__name__}", (FastRest,), namespace)
        self._cache[plan.model] = schema
        return schema
