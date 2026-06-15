"""ORM backends for :mod:`fastberry.rest`.

The read-only serialization core in ``fastberry.rest`` is ORM-agnostic: it
assembles the relational tree from lists of plain dicts. Only two things are
ORM-specific, and they live here behind a small backend interface:

- **introspection** — discover a model's primary key, scalar columns, decimal
  columns, and forward/reverse foreign-key relations (``ModelSpec``);
- **fetching** — project a set of columns to a list of dicts, optionally
  filtered by ``<column> IN (...)`` (one query per tree level — no N+1).

Two backends are provided: a Django ORM backend (always available, Django is a
hard dependency) and an optional SQLAlchemy backend (needs the ``sqlalchemy``
extra). :func:`get_backend` picks the right one from the model class, so the
public ``FastRest`` API is identical for both.

The Django backend works off ``Model.objects`` and needs no extra handle. The
SQLAlchemy backend needs a ``Session``, which the caller threads in via
``serialize(..., session=...)``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass
class ForwardFK:
    """A forward foreign key (this model holds the related pk)."""

    attr: str  # relation attribute name on this model
    fk_col: str  # column on THIS model holding the related pk
    related_model: Any


@dataclass
class ReverseFK:
    """A reverse foreign key / one-to-many (the child holds the fk back to us)."""

    accessor: str  # relation attribute name on this model (the "many" side)
    child_model: Any
    child_fk_col: str  # column on the CHILD holding the fk back to this model


@dataclass
class M2MRel:
    """A many-to-many relation, described via its through table.

    Lets a label-projecting serializer fetch ``(source_pk, target_pk, label)``
    triples for a set of source rows with a single query over the through
    table — set-based, no per-row manager access and no instances.
    """

    attr: str  # the m2m field/accessor name on this model
    related_model: Any  # the target model
    through: Any  # the through model
    source_col: str  # FK field name on through -> this model (e.g. "stock")
    target_col: str  # FK field name on through -> related model (e.g. "tag")
    target_pk: str  # pk name on the related model


@dataclass
class ModelSpec:
    """Normalized, ORM-independent description of a model."""

    pk_name: str
    scalar_fields: list[str]  # non-FK scalar columns (includes the pk)
    fk_columns: list[str]  # forward-FK id columns
    decimal_fields: set[str]  # columns that may yield Decimal values
    forward_fks: list[ForwardFK]
    reverse_fks: list[ReverseFK]
    m2m_rels: list[M2MRel] | None = None  # many-to-many relations (Django only)

    def __post_init__(self) -> None:
        self.forward_by_attr: dict[str, ForwardFK] = {f.attr: f for f in self.forward_fks}
        self.reverse_by_attr: dict[str, ReverseFK] = {r.accessor: r for r in self.reverse_fks}
        self.m2m_by_attr: dict[str, M2MRel] = {m.attr: m for m in (self.m2m_rels or [])}


class Backend:
    """Interface a model's ORM must satisfy. Stateless — methods take what they need."""

    def introspect(self, model: Any) -> ModelSpec:  # pragma: no cover - interface
        raise NotImplementedError

    def fetch(
        self,
        model: Any,
        columns: Sequence[str],
        *,
        where_col: str | None = None,
        where_values: Iterable[Any] | None = None,
        source: Any = None,
        session: Any = None,
        annotations: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:  # pragma: no cover - interface
        """Return rows of ``model`` (as dicts) projecting ``columns``.

        Exactly one of ``source`` (a caller-provided query for the top level) or
        ``where_col``/``where_values`` (a ``col IN values`` filter built for a
        nested level) is used; both ``None`` means "all rows".

        ``annotations`` (Django only) are applied as ``.annotate(**annotations)``
        before projection, so an expression column can be selected by name.
        """
        raise NotImplementedError

    def fetch_m2m(
        self,
        rel: M2MRel,
        source_ids: Sequence[Any],
        label_path: str | None,
        *,
        session: Any = None,
    ) -> list[tuple[Any, Any, Any]]:  # pragma: no cover - interface
        """Return ``(source_pk, target_pk, label)`` triples for ``source_ids``.

        One query over the through table. ``label_path`` is a field path on the
        target model (e.g. ``"name"``) or ``None`` to omit the label.
        """
        raise NotImplementedError


# --- Django -----------------------------------------------------------------


class DjangoBackend(Backend):
    def introspect(self, model: Any) -> ModelSpec:
        from django.db import models

        meta = model._meta
        scalars: list[str] = []
        fk_cols: list[str] = []
        decimals: list[str] = []
        forward: list[ForwardFK] = []
        for f in meta.concrete_fields:
            if isinstance(f, models.ForeignKey):
                fk_cols.append(f.attname)  # '<name>_id'
                forward.append(
                    ForwardFK(attr=f.name, fk_col=f.attname, related_model=f.related_model)
                )
            else:
                scalars.append(f.name)
                if isinstance(f, models.DecimalField):
                    decimals.append(f.name)

        reverse: list[ReverseFK] = []
        for rel in meta.related_objects:
            if not isinstance(rel, models.ManyToOneRel):
                continue  # ManyToMany / reverse OneToOne not handled
            accessor = rel.get_accessor_name()
            if accessor is None:  # related_name='+' hides the relation
                continue
            reverse.append(
                ReverseFK(
                    accessor=accessor,
                    child_model=rel.related_model,
                    child_fk_col=rel.field.attname,
                )
            )

        # Forward many-to-many fields, described via their through model so a
        # label-projecting serializer can fetch them set-based (see fetch_m2m).
        m2m: list[M2MRel] = []
        for f in meta.many_to_many:
            related = f.related_model
            m2m.append(
                M2MRel(
                    attr=f.name,
                    related_model=related,
                    through=f.remote_field.through,
                    source_col=f.m2m_field_name(),  # through FK -> this model
                    target_col=f.m2m_reverse_field_name(),  # through FK -> target
                    target_pk=related._meta.pk.name,
                )
            )

        return ModelSpec(meta.pk.name, scalars, fk_cols, set(decimals), forward, reverse, m2m)

    def fetch(
        self,
        model: Any,
        columns: Sequence[str],
        *,
        where_col: str | None = None,
        where_values: Iterable[Any] | None = None,
        source: Any = None,
        session: Any = None,
        annotations: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        qs = source if source is not None else model._default_manager.all()
        if where_col is not None:
            # where_values is paired with where_col by the caller; narrow it
            assert where_values is not None  # noqa: S101
            qs = qs.filter(**{f"{where_col}__in": list(where_values)})
        if annotations:
            qs = qs.annotate(**annotations)
        return list(qs.values(*columns))

    def fetch_m2m(
        self,
        rel: M2MRel,
        source_ids: Sequence[Any],
        label_path: str | None,
        *,
        session: Any = None,
    ) -> list[tuple[Any, Any, Any]]:
        if not source_ids:
            return []
        source_id_col = f"{rel.source_col}_id"
        target_id_col = f"{rel.target_col}_id"
        cols = [source_id_col, target_id_col]
        label_alias = f"{rel.target_col}__{label_path}" if label_path else None
        if label_alias:
            cols.append(label_alias)
        qs = rel.through._default_manager.filter(**{f"{source_id_col}__in": list(source_ids)})
        return [
            (row[source_id_col], row[target_id_col], row.get(label_alias) if label_alias else None)
            for row in qs.values(*cols)
        ]


# --- SQLAlchemy -------------------------------------------------------------


class SQLAlchemyBackend(Backend):
    def introspect(self, model: Any) -> ModelSpec:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import types as satypes
        from sqlalchemy.orm import interfaces

        m = sa_inspect(model)
        # Map Column -> python attribute key (they usually match, but need not).
        col_key = {a.columns[0]: a.key for a in m.column_attrs}

        pk_col = m.primary_key[0]
        pk_name = col_key.get(pk_col, pk_col.key)

        fk_keys: set[str] = set()
        forward: list[ForwardFK] = []
        reverse: list[ReverseFK] = []
        for rel in m.relationships:
            pairs = list(rel.local_remote_pairs)
            if not pairs:
                continue
            related = rel.mapper.class_
            if rel.direction is interfaces.MANYTOONE:
                local = pairs[0][0]
                key = col_key.get(local, local.key)
                fk_keys.add(key)
                forward.append(ForwardFK(attr=rel.key, fk_col=key, related_model=related))
            elif rel.direction is interfaces.ONETOMANY:
                remote = pairs[0][1]
                child_col_key = {a.columns[0]: a.key for a in sa_inspect(related).column_attrs}
                reverse.append(
                    ReverseFK(
                        accessor=rel.key,
                        child_model=related,
                        child_fk_col=child_col_key.get(remote, remote.key),
                    )
                )
            # MANYTOMANY skipped, like the Django backend.

        scalars: list[str] = []
        fk_cols: list[str] = []
        decimals: list[str] = []
        for a in m.column_attrs:
            key = a.key
            col = a.columns[0]
            if key in fk_keys:
                fk_cols.append(key)
                continue
            scalars.append(key)
            t = col.type
            # Numeric yields Decimal (asdecimal); Float (a Numeric subclass) does not.
            if isinstance(t, satypes.Numeric) and not isinstance(t, satypes.Float):
                decimals.append(key)

        return ModelSpec(pk_name, scalars, fk_cols, set(decimals), forward, reverse)

    def fetch(
        self,
        model: Any,
        columns: Sequence[str],
        *,
        where_col: str | None = None,
        where_values: Iterable[Any] | None = None,
        source: Any = None,
        session: Any = None,
        annotations: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select

        if annotations:
            raise NotImplementedError(
                "fastberry.rest: Expr/annotation fields are only supported on the Django backend."
            )
        if session is None:
            raise TypeError(
                "fastberry.rest: serializing a SQLAlchemy model needs a session. "
                "Pass it as serialize(..., session=session)."
            )
        if source is not None and hasattr(source, "subquery"):
            # Caller supplied a Select (filters/ordering); keep it, project our columns.
            sub = source.subquery()
            stmt = select(*(sub.c[c] for c in columns))
        else:
            stmt = select(*(getattr(model, c) for c in columns))
            if where_col is not None:
                # where_values is paired with where_col by the caller; narrow it
                assert where_values is not None  # noqa: S101
                stmt = stmt.where(getattr(model, where_col).in_(list(where_values)))
        return [dict(row) for row in session.execute(stmt).mappings().all()]


# --- dispatch + cache -------------------------------------------------------

_DJANGO = DjangoBackend()
_SQLALCHEMY = SQLAlchemyBackend()
_SPEC_CACHE: dict = {}


def get_backend(model: Any) -> Backend:
    """Return the backend for ``model`` (Django model or SQLAlchemy mapped class).

    Both ORMs are optional: Django comes with the ``rest`` extra, SQLAlchemy
    with the ``sqlalchemy`` extra. Whichever is installed is probed; a model
    from the other ORM is simply not recognized.
    """
    try:
        from django.db.models import Model as DjangoModel
    except ImportError:
        DjangoModel = None

    if DjangoModel is not None and isinstance(model, type) and issubclass(model, DjangoModel):
        return _DJANGO

    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.orm import Mapper
    except ImportError:
        sa_inspect = None  # type: ignore[assignment]

    if sa_inspect is not None:
        info = sa_inspect(model, raiseerr=False)
        if isinstance(info, Mapper):
            return _SQLALCHEMY

    raise TypeError(
        f"fastberry.rest: don't know how to introspect {model!r}; expected a "
        f"Django model (install the 'rest' extra) or a SQLAlchemy mapped class "
        f"(install the 'sqlalchemy' extra)."
    )


def introspect(model: Any) -> ModelSpec:
    """Introspect ``model`` to a :class:`ModelSpec`, cached per model class."""
    spec = _SPEC_CACHE.get(model)
    if spec is None:
        spec = get_backend(model).introspect(model)
        _SPEC_CACHE[model] = spec
    return spec
