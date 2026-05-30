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

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ForwardFK:
    """A forward foreign key (this model holds the related pk)."""

    attr: str            # relation attribute name on this model
    fk_col: str          # column on THIS model holding the related pk
    related_model: Any


@dataclass
class ReverseFK:
    """A reverse foreign key / one-to-many (the child holds the fk back to us)."""

    accessor: str        # relation attribute name on this model (the "many" side)
    child_model: Any
    child_fk_col: str    # column on the CHILD holding the fk back to this model


@dataclass
class ModelSpec:
    """Normalized, ORM-independent description of a model."""

    pk_name: str
    scalar_fields: list[str]      # non-FK scalar columns (includes the pk)
    fk_columns: list[str]         # forward-FK id columns
    decimal_fields: set[str]      # columns that may yield Decimal values
    forward_fks: list[ForwardFK]
    reverse_fks: list[ReverseFK]

    def __post_init__(self) -> None:
        self.forward_by_attr = {f.attr: f for f in self.forward_fks}
        self.reverse_by_attr = {r.accessor: r for r in self.reverse_fks}


class Backend:
    """Interface a model's ORM must satisfy. Stateless — methods take what they need."""

    def introspect(self, model) -> ModelSpec:  # pragma: no cover - interface
        raise NotImplementedError

    def fetch(
        self,
        model,
        columns,
        *,
        where_col: Optional[str] = None,
        where_values=None,
        source=None,
        session=None,
    ) -> list:  # pragma: no cover - interface
        """Return rows of ``model`` (as dicts) projecting ``columns``.

        Exactly one of ``source`` (a caller-provided query for the top level) or
        ``where_col``/``where_values`` (a ``col IN values`` filter built for a
        nested level) is used; both ``None`` means "all rows".
        """
        raise NotImplementedError


# --- Django -----------------------------------------------------------------

class DjangoBackend(Backend):
    def introspect(self, model) -> ModelSpec:
        from django.db import models

        meta = model._meta
        scalars: list[str] = []
        fk_cols: list[str] = []
        decimals: list[str] = []
        forward: list[ForwardFK] = []
        for f in meta.concrete_fields:
            if isinstance(f, models.ForeignKey):
                fk_cols.append(f.attname)  # '<name>_id'
                forward.append(ForwardFK(attr=f.name, fk_col=f.attname, related_model=f.related_model))
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
            reverse.append(ReverseFK(
                accessor=accessor, child_model=rel.related_model,
                child_fk_col=rel.field.attname,
            ))

        return ModelSpec(meta.pk.name, scalars, fk_cols, set(decimals), forward, reverse)

    def fetch(self, model, columns, *, where_col=None, where_values=None, source=None, session=None):
        qs = source if source is not None else model._default_manager.all()
        if where_col is not None:
            qs = qs.filter(**{f"{where_col}__in": list(where_values)})
        return list(qs.values(*columns))


# --- SQLAlchemy -------------------------------------------------------------

class SQLAlchemyBackend(Backend):
    def introspect(self, model) -> ModelSpec:
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
                reverse.append(ReverseFK(
                    accessor=rel.key, child_model=related,
                    child_fk_col=child_col_key.get(remote, remote.key),
                ))
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

    def fetch(self, model, columns, *, where_col=None, where_values=None, source=None, session=None):
        from sqlalchemy import select

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
                stmt = stmt.where(getattr(model, where_col).in_(list(where_values)))
        return [dict(row) for row in session.execute(stmt).mappings().all()]


# --- dispatch + cache -------------------------------------------------------

_DJANGO = DjangoBackend()
_SQLALCHEMY = SQLAlchemyBackend()
_SPEC_CACHE: dict = {}


def get_backend(model) -> Backend:
    """Return the backend for ``model`` (Django model or SQLAlchemy mapped class)."""
    from django.db.models import Model as DjangoModel

    if isinstance(model, type) and issubclass(model, DjangoModel):
        return _DJANGO

    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.orm import Mapper
    except ImportError:
        sa_inspect = None

    if sa_inspect is not None:
        info = sa_inspect(model, raiseerr=False)
        if isinstance(info, Mapper):
            return _SQLALCHEMY

    raise TypeError(
        f"fastberry.rest: don't know how to introspect {model!r}; expected a "
        f"Django model or a SQLAlchemy mapped class (install the 'sqlalchemy' extra)."
    )


def introspect(model) -> ModelSpec:
    """Introspect ``model`` to a :class:`ModelSpec`, cached per model class."""
    spec = _SPEC_CACHE.get(model)
    if spec is None:
        spec = get_backend(model).introspect(model)
        _SPEC_CACHE[model] = spec
    return spec
