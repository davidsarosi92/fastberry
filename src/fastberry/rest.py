"""Fast read-only nested serialization for Django **and** SQLAlchemy.

The problem: an ORM's nested serializer (DRF's ``ModelSerializer``, or hand-rolled
object-graph walking) builds an instance at every node of a relational tree and
runs a per-field pipeline across the whole tree. On a deep tree (3-4 relations)
this becomes the bottleneck even at a few hundred top-level objects — the same
per-instance overhead that ``fast_path`` removes on the GraphQL side.

The fix: declare the output shape once, and at serialization time

- fetch each level with a single column-projected query (no model instances),
- assemble the tree in Python via indexed dicts (no N+1),
- encode with ``orjson``.

This is read-only by design. Validation / writes stay with DRF / Pydantic /
your ORM — this only replaces the read path, where the cost is.

The serialization core is ORM-agnostic; the ORM-specific bits (introspection +
fetching) live in :mod:`fastberry.rest_backends`. The backend is chosen from the
model class, so the API below is the same for Django and SQLAlchemy — except
that SQLAlchemy needs a session::

    # Django (uses Model.objects):
    HouseRest.serialize(House.objects.all())
    HouseRest.serialize_json(House.objects.all())          # bytes (orjson)

    # SQLAlchemy (pass a session; optionally a select() to filter/order):
    HouseRest.serialize(session=session)                   # all rows
    HouseRest.serialize_json(select(House).where(...), session=session)

Schema declaration is identical for both::

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

Supported relations: forward foreign key (single) and reverse foreign key /
one-to-many (``many=True``). ManyToMany is not handled.
"""

from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from typing import Any, ClassVar, cast

from fastberry.rest_backends import Backend, ModelSpec, get_backend, introspect

try:
    import orjson
except ImportError as _exc:  # pragma: no cover - exercised via install extras
    raise ImportError(
        "fastberry.rest requires orjson. Install it with: pip install 'fastberry[rest]'"
    ) from _exc

__all__ = ["FastRest", "fast_rest", "get_schema_for_model", "register_schema"]


# model class -> resolved FastRest subclass.
_SCHEMA_REGISTRY: dict[type, "type[FastRest]"] = {}
# model class -> zero-arg builder, for schemas that must be built lazily
# (auto-derive needs every related model loaded, which isn't guaranteed at
# decoration time — reverse relations from models defined later would be missed).
_SCHEMA_BUILDERS: dict[type, Callable[[], "type[FastRest]"]] = {}


def register_schema(model: Any, schema: "type[FastRest]") -> None:
    """Associate a hand-written FastRest subclass with a model.

    Lets a renderer (or any caller) find the schema for a model instance or
    queryset. Use this when you've written an explicit nested FastRest and
    want it picked up automatically.
    """
    _SCHEMA_REGISTRY[model] = schema
    model.__fast_schema__ = schema


def _register_lazy(model: Any, builder: "Callable[[], type[FastRest]]") -> None:
    """Register a builder to construct the schema on first lookup."""
    _SCHEMA_BUILDERS[model] = builder


def get_schema_for_model(model: Any) -> "type[FastRest] | None":
    """Return the FastRest for ``model``, or ``None``.

    Resolves and caches a lazily-registered (auto-derived) schema on first use.
    """
    schema = _SCHEMA_REGISTRY.get(model)
    if schema is not None:
        return schema
    builder = _SCHEMA_BUILDERS.get(model)
    if builder is not None:
        schema = builder()
        register_schema(model, schema)
        return schema
    return None


class _NestedSpec:
    """Resolved metadata for one nested relation on a schema."""

    __slots__ = ("attr", "child_fk_attname", "fk_attname", "forward", "many", "schema")

    def __init__(
        self,
        attr: str,
        schema: "type[FastRest]",
        many: bool,
        forward: bool,
        fk_attname: str | None,
        child_fk_attname: str | None,
    ) -> None:
        self.attr = attr
        self.schema = schema
        self.many = many
        self.forward = forward
        self.fk_attname = fk_attname  # forward: fk col on this model
        self.child_fk_attname = child_fk_attname  # reverse: fk col on the child model


class FastRestMeta(type):
    def __new__(
        mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any]
    ) -> "type[FastRest]":
        # The produced class is a FastRest subclass; cast so the attribute
        # wiring below (and callers) see the FastRest interface, not the bare
        # metaclass.
        cls = cast("type[FastRest]", super().__new__(mcs, name, bases, namespace))

        meta = namespace.get("Meta")
        if meta is None:
            # Base class itself, nothing to wire up.
            return cls

        model = meta.model
        declared_fields = list(meta.fields)
        spec = introspect(model)

        cls._model = model
        cls._backend = get_backend(model)
        cls._spec = spec
        cls._pk_name = spec.pk_name
        cls._declared_fields = declared_fields

        # Decide Decimal conversion once, at class-definition time.
        cls._decimal_fields = [f for f in declared_fields if f in spec.decimal_fields]

        # Resolve nested declarations (instances of FastRest set as attributes).
        nested = []
        for attr, value in list(namespace.items()):
            if not isinstance(value, FastRest):
                continue
            if attr in spec.forward_by_attr:
                fk = spec.forward_by_attr[attr]
                nested.append(
                    _NestedSpec(
                        attr=attr,
                        schema=value.__class__,
                        many=False,
                        forward=True,
                        fk_attname=fk.fk_col,
                        child_fk_attname=None,
                    )
                )
            elif attr in spec.reverse_by_attr:
                rev = spec.reverse_by_attr[attr]
                nested.append(
                    _NestedSpec(
                        attr=attr,
                        schema=value.__class__,
                        many=True,
                        forward=False,
                        fk_attname=None,
                        child_fk_attname=rev.child_fk_col,
                    )
                )
            else:
                raise TypeError(
                    f"{name}.{attr}: unsupported relation (only forward FK and "
                    f"reverse FK / one-to-many are supported)"
                )
        cls._nested = nested
        return cls


class FastRest(metaclass=FastRestMeta):
    # Populated by FastRestMeta for concrete subclasses (those declaring a Meta).
    _model: ClassVar[type]
    _backend: ClassVar[Backend]
    _spec: ClassVar[ModelSpec]
    _pk_name: ClassVar[str]
    _declared_fields: ClassVar[list[str]]
    _decimal_fields: ClassVar[list[str]]
    _nested: ClassVar[list[_NestedSpec]]

    def __init__(self, many: bool = False) -> None:
        # Instances act as nested-relation markers in a parent schema body.
        self.many = many

    # --- public API ---------------------------------------------------------

    @classmethod
    def serialize(cls, source: Any = None, *, session: Any = None) -> list[dict[str, Any]]:
        """Serialize to a list of plain dicts.

        ``source`` is a Django queryset, a SQLAlchemy ``select()``, or ``None``
        for all rows. SQLAlchemy models also require ``session``.
        """
        return cls._collect(source=source, session=session)

    @classmethod
    def serialize_json(cls, source: Any = None, *, session: Any = None) -> bytes:
        """Serialize directly to JSON bytes via orjson."""
        return orjson.dumps(cls._collect(source=source, session=session))

    @classmethod
    def serialize_obj(cls, obj: Any, *, session: Any = None) -> dict[str, Any] | None:
        """Serialize a single model instance to one dict.

        Convenience for detail endpoints. Internally reuses the list path on a
        one-row fetch so all the nesting/typing logic is shared.
        """
        pk_val = getattr(obj, cls._pk_name)
        rows = cls._collect(where_col=cls._pk_name, where_values=[pk_val], session=session)
        return rows[0] if rows else None

    @classmethod
    def serialize_obj_json(cls, obj: Any, *, session: Any = None) -> bytes:
        """Serialize a single model instance directly to JSON bytes."""
        return orjson.dumps(cls.serialize_obj(obj, session=session))

    # --- internals ----------------------------------------------------------

    @classmethod
    def _collect(
        cls,
        *,
        source: Any = None,
        session: Any = None,
        where_col: str | None = None,
        where_values: Iterable[Any] | None = None,
        extra_keep: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        pk = cls._pk_name

        # Columns we must fetch: declared scalars, pk (for joins), forward FK
        # ids (for forward nesting), and any keys the caller asked us to keep
        # (e.g. the reverse fk used for grouping).
        value_fields = set(cls._declared_fields)
        value_fields.add(pk)
        for spec in cls._nested:
            if spec.forward and spec.fk_attname is not None:
                value_fields.add(spec.fk_attname)
        value_fields.update(extra_keep)

        rows = cls._backend.fetch(
            cls._model,
            list(value_fields),
            where_col=where_col,
            where_values=where_values,
            source=source,
            session=session,
        )

        for row in rows:
            for f in cls._decimal_fields:
                v = row.get(f)
                if isinstance(v, Decimal):
                    row[f] = str(v)

        for spec in cls._nested:
            if spec.forward:
                cls._attach_forward(rows, spec, session)
            else:
                cls._attach_reverse(rows, spec, session)

        # Strip helper columns we added but the caller did not declare/request.
        declared = set(cls._declared_fields) | {s.attr for s in cls._nested} | set(extra_keep)
        for row in rows:
            for key in [k for k in row if k not in declared]:
                del row[key]

        return rows

    @classmethod
    def _attach_forward(cls, rows: list[dict[str, Any]], spec: _NestedSpec, session: Any) -> None:
        sub = spec.schema
        fk = spec.fk_attname
        # forward spec always carries its fk column; narrow for the type checker
        assert fk is not None  # noqa: S101
        ids = {r[fk] for r in rows if r.get(fk) is not None}

        index = {}
        if ids:
            sub_pk = sub._pk_name
            sub_rows = sub._collect(
                where_col=sub_pk,
                where_values=ids,
                session=session,
                extra_keep=(sub_pk,),
            )
            for sr in sub_rows:
                index[sr[sub_pk]] = sr
            # Drop the helper pk if the child didn't declare it.
            if sub_pk not in sub._declared_fields:
                for sr in sub_rows:
                    sr.pop(sub_pk, None)

        for r in rows:
            r[spec.attr] = index.get(r.get(fk))

    @classmethod
    def _attach_reverse(cls, rows: list[dict[str, Any]], spec: _NestedSpec, session: Any) -> None:
        sub = spec.schema
        child_fk = spec.child_fk_attname
        # reverse spec always carries the child fk column; narrow for the type checker
        assert child_fk is not None  # noqa: S101
        parent_pk = cls._pk_name
        parent_ids = [r[parent_pk] for r in rows]

        groups: dict[Any, list[dict[str, Any]]] = {}
        if parent_ids:
            child_rows = sub._collect(
                where_col=child_fk,
                where_values=parent_ids,
                session=session,
                extra_keep=(child_fk,),
            )
            for cr in child_rows:
                groups.setdefault(cr[child_fk], []).append(cr)
            # Drop the grouping fk if the child didn't declare it.
            if child_fk not in sub._declared_fields:
                for cr in child_rows:
                    cr.pop(child_fk, None)

        for r in rows:
            r[spec.attr] = groups.get(r[parent_pk], [])


# --- @fast_rest decorator + auto-derive -------------------------------------


def _concrete_field_names(model: Any) -> list[str]:
    """Local (non-relational) field names + FK ids, for default scalar output."""
    spec = introspect(model)
    return list(spec.scalar_fields) + list(spec.fk_columns)


def _build_auto_schema(model: Any, depth: int, _seen: frozenset[Any]) -> "type[FastRest]":
    """Build a FastRest for ``model`` automatically from its fields.

    ``depth`` controls how many relation levels to expand:
      - depth == 0: scalars + FK ids only, no nested objects.
      - depth >= 1: also expand forward FKs and reverse FK sets one level,
        recursing with depth - 1.

    ``_seen`` guards against cycles (a model already on the current path is not
    re-expanded; it falls back to its FK id / is skipped).
    """
    spec = introspect(model)

    namespace: dict[str, Any] = {}
    fields = list(spec.scalar_fields)

    if depth <= 0:
        # No expansion: include FK ids as scalars so nothing relational is lost.
        fields += list(spec.fk_columns)
    else:
        next_seen = _seen | {model}
        # Forward FKs -> nested single object (or id if it would cycle).
        for fk in spec.forward_fks:
            if fk.related_model in next_seen:
                fields.append(fk.fk_col)  # avoid cycle: keep the id
                continue
            sub = _build_auto_schema(fk.related_model, depth - 1, next_seen)
            namespace[fk.attr] = sub(many=False)
        # Reverse FK relations -> nested list (skip if it would cycle).
        for rev in spec.reverse_fks:
            if rev.child_model in next_seen:
                continue
            sub = _build_auto_schema(rev.child_model, depth - 1, next_seen)
            namespace[rev.accessor] = sub(many=True)

    Meta = type("Meta", (), {"model": model, "fields": fields})
    namespace["Meta"] = Meta
    name = f"_Auto{model.__name__}Rest"
    return cast("type[FastRest]", FastRestMeta(name, (FastRest,), namespace))


def fast_rest(
    _cls: Any = None,
    *,
    fields: Sequence[str] | None = None,
    nested: "dict[str, type[FastRest]] | None" = None,
    depth: int | None = None,
) -> Any:
    """Class decorator: attach a read-only FastRest to a model.

    Works for Django models and SQLAlchemy mapped classes alike. The schema is
    registered so a renderer (or any caller) can look it up by model — that is
    what makes ``return Response(queryset)`` work with
    :class:`fastberry.rest_renderers.FastJSONRenderer` without writing a
    serializer (Django/DRF only).

    Two styles (mutually exclusive):

    Explicit — you control exactly what is emitted::

        @fast_rest(fields=["id", "title", "amount"])
        class Stock(models.Model): ...

        @fast_rest(
            fields=["id", "name", "address"],
            nested={"spaces": SpaceRest},   # SpaceRest is a FastRest subclass
        )
        class House(models.Model): ...

    Auto-derive — build the schema from the model's fields/relations::

        @fast_rest(depth=2)
        class House(models.Model): ...

    With ``depth``, FKs become nested objects and reverse-FK sets become nested
    lists, recursively, down to ``depth`` levels (cycles are broken by falling
    back to the FK id). ``depth=0`` emits scalars + FK ids only.

    Security note: auto-derive emits *every* field at each expanded level. On
    models with sensitive columns, prefer the explicit ``fields`` form.
    """

    def wrap(model):
        if depth is not None and (fields is not None or nested is not None):
            raise TypeError("fast_rest: use either depth= or fields=/nested=, not both")

        if depth is not None:
            # Build lazily: auto-derive must see all related models, which may
            # not be loaded yet when this decorator runs at import time.
            _register_lazy(model, lambda: _build_auto_schema(model, depth, frozenset()))
        else:
            schema_fields = fields if fields is not None else _concrete_field_names(model)
            namespace = {}
            if nested:
                for attr, sub in nested.items():
                    namespace[attr] = sub(many=_is_to_many(model, attr))
            namespace["Meta"] = type("Meta", (), {"model": model, "fields": list(schema_fields)})
            schema = FastRestMeta(f"_FastRest{model.__name__}", (FastRest,), namespace)
            register_schema(model, schema)
        return model

    return wrap if _cls is None else wrap(_cls)


def _is_to_many(model: Any, attr: str) -> bool:
    """True if ``attr`` on ``model`` is a reverse FK / to-many relation."""
    return attr in introspect(model).reverse_by_attr
