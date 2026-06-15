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

__all__ = [
    "Expr",
    "FastRest",
    "LabelRef",
    "M2MLabels",
    "fast_rest",
    "get_schema_for_model",
    "register_schema",
]


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


# --- field markers ----------------------------------------------------------
#
# Set as class attributes in a FastRest body, alongside (or instead of) nested
# FastRest instances. They let a schema emit human labels and many-to-many
# columns WITHOUT materializing model instances — the label/expression is
# projected by the database, so the no-instance fast path is preserved.


class LabelRef:
    """A forward FK rendered as ``{"id": <fk_id>, "label": <related.label>}``.

    ``label`` is a field path on the related model (default ``"name"``),
    projected via a spanning ``.values()`` lookup — no extra query, no instance.
    A null FK serializes to ``None``. ``relation`` defaults to the attribute the
    marker is assigned to::

        class StockRest(FastRest):
            category = LabelRef(label="name")          # -> {"id":3,"label":"Beers"}
            dealer = LabelRef("supplier", label="title")
            class Meta:
                model = Stock
                fields = ["id", "title"]
    """

    def __init__(self, relation: str | None = None, *, label: str = "name") -> None:
        self.relation = relation
        self.label = label


class Expr:
    """A field whose value is computed by a DB expression (``.annotate()``).

    The annotated column is read by the attribute name it is assigned to::

        full_name = Expr(Concat("first", Value(" "), "last"))
        total = Expr(F("qty") * F("price"), decimal=True)

    Set ``decimal=True`` when the expression yields a ``Decimal`` so it is
    stringified consistently with declared decimal fields. Django backend only.
    """

    def __init__(self, expression: Any, *, decimal: bool = False) -> None:
        self.expression = expression
        self.decimal = decimal


class M2MLabels:
    """A many-to-many column rendered as a capped list of ``{"id","label"}``.

    Fetched set-based over the through table for the whole result page (no
    per-row manager access, no instances). When more than ``cap`` related rows
    exist for a row, a ``{"id": None, "label": "+N more"}`` marker is appended.
    ``cap=None`` means no cap (every related row). ``relation`` defaults to the
    assigned attribute name::

        tags = M2MLabels(label="name", cap=20)

    Django backend only.
    """

    def __init__(
        self, relation: str | None = None, *, label: str = "name", cap: int | None = 20
    ) -> None:
        self.relation = relation
        self.label = label
        self.cap = cap


class _LabelRefSpec:
    """Resolved metadata for a LabelRef field."""

    __slots__ = ("fk_attname", "label_col", "out_attr")

    def __init__(self, out_attr: str, fk_attname: str, label_col: str) -> None:
        self.out_attr = out_attr  # output key (and assigned attr name)
        self.fk_attname = fk_attname  # fk id column on this model (e.g. "category_id")
        self.label_col = label_col  # spanning projection (e.g. "category__name")


class _ExprSpec:
    """Resolved metadata for an Expr field."""

    __slots__ = ("expression", "is_decimal", "out_attr")

    def __init__(self, out_attr: str, expression: Any, is_decimal: bool) -> None:
        self.out_attr = out_attr
        self.expression = expression
        self.is_decimal = is_decimal


class _M2MLabelSpec:
    """Resolved metadata for an M2MLabels field."""

    __slots__ = ("cap", "label_path", "out_attr", "rel")

    def __init__(self, out_attr: str, rel: Any, label_path: str, cap: int | None) -> None:
        self.out_attr = out_attr
        self.rel = rel  # rest_backends.M2MRel
        self.label_path = label_path  # field path on the related model
        self.cap = cap


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

        # Resolve declarations set as class attributes: nested FastRest instances
        # (full sub-objects) and the label/expr/m2m field markers.
        nested = []
        label_refs: list[_LabelRefSpec] = []
        exprs: list[_ExprSpec] = []
        m2m_labels: list[_M2MLabelSpec] = []
        for attr, value in list(namespace.items()):
            if isinstance(value, LabelRef):
                relation = value.relation or attr
                fk = spec.forward_by_attr.get(relation)
                if fk is None:
                    raise TypeError(
                        f"{name}.{attr}: LabelRef target {relation!r} is not a forward FK"
                    )
                label_refs.append(
                    _LabelRefSpec(
                        out_attr=attr,
                        fk_attname=fk.fk_col,
                        label_col=f"{relation}__{value.label}",
                    )
                )
            elif isinstance(value, Expr):
                exprs.append(
                    _ExprSpec(out_attr=attr, expression=value.expression, is_decimal=value.decimal)
                )
            elif isinstance(value, M2MLabels):
                relation = value.relation or attr
                rel = spec.m2m_by_attr.get(relation)
                if rel is None:
                    raise TypeError(
                        f"{name}.{attr}: M2MLabels target {relation!r} is not a many-to-many "
                        f"field (or the backend does not support m2m)"
                    )
                m2m_labels.append(
                    _M2MLabelSpec(out_attr=attr, rel=rel, label_path=value.label, cap=value.cap)
                )
            elif isinstance(value, FastRest):
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
        cls._label_refs = label_refs
        cls._exprs = exprs
        cls._m2m_labels = m2m_labels
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
    _label_refs: ClassVar[list[_LabelRefSpec]]
    _exprs: ClassVar[list[_ExprSpec]]
    _m2m_labels: ClassVar[list[_M2MLabelSpec]]

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
        # LabelRef: project the fk id (for {"id"}) + the spanning label column.
        for lr in cls._label_refs:
            value_fields.add(lr.fk_attname)
            value_fields.add(lr.label_col)
        # Expr: list the annotation alias so .values() actually selects it.
        for e in cls._exprs:
            value_fields.add(e.out_attr)
        # M2MLabels need the parent pk to group the through-table rows on.
        if cls._m2m_labels:
            value_fields.add(pk)
        value_fields.update(extra_keep)

        # Expr: computed by the DB via .annotate(), read back by its output name.
        annotations = {e.out_attr: e.expression for e in cls._exprs} or None

        rows = cls._backend.fetch(
            cls._model,
            list(value_fields),
            where_col=where_col,
            where_values=where_values,
            source=source,
            session=session,
            annotations=annotations,
        )

        decimal_names = list(cls._decimal_fields) + [e.out_attr for e in cls._exprs if e.is_decimal]
        for row in rows:
            for f in decimal_names:
                v = row.get(f)
                if isinstance(v, Decimal):
                    row[f] = str(v)

        # LabelRef -> {"id", "label"} (or None for a null FK), from projected cols.
        for lr in cls._label_refs:
            for row in rows:
                fk_id = row.get(lr.fk_attname)
                row[lr.out_attr] = (
                    None if fk_id is None else {"id": fk_id, "label": row.get(lr.label_col)}
                )

        for spec in cls._nested:
            if spec.forward:
                cls._attach_forward(rows, spec, session)
            else:
                cls._attach_reverse(rows, spec, session)

        for m in cls._m2m_labels:
            cls._attach_m2m_labels(rows, m, session)

        # Strip helper columns we added but the caller did not declare/request.
        declared = set(cls._declared_fields) | {s.attr for s in cls._nested} | set(extra_keep)
        declared |= {lr.out_attr for lr in cls._label_refs}
        declared |= {e.out_attr for e in cls._exprs}
        declared |= {m.out_attr for m in cls._m2m_labels}
        for row in rows:
            for key in [k for k in row if k not in declared]:
                del row[key]

        return rows

    @classmethod
    def _attach_m2m_labels(cls, rows: list[dict[str, Any]], m: _M2MLabelSpec, session: Any) -> None:
        pk = cls._pk_name
        parent_ids = [r[pk] for r in rows]
        triples = cls._backend.fetch_m2m(m.rel, parent_ids, m.label_path, session=session)

        groups: dict[Any, list[dict[str, Any]]] = {}
        for source_id, target_id, label in triples:
            groups.setdefault(source_id, []).append({"id": target_id, "label": label})

        cap = m.cap
        for r in rows:
            items = groups.get(r[pk], [])
            if cap is not None and len(items) > cap:
                capped = items[:cap]
                capped.append({"id": None, "label": f"+{len(items) - cap} more"})
                r[m.out_attr] = capped
            else:
                r[m.out_attr] = items

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
