# fastberry

Performance helpers for read-heavy Python web APIs, on both GraphQL and REST.

On large or deeply-nested payloads, the per-instance / per-field overhead of
GraphQL and REST frameworks dominates response time — pure CPU cost with no
extra database work. `fastberry` lets you opt specific hot paths out of that
machinery.

Two independent helpers, usable separately:

- **`fast_path`** (GraphQL) — skip `strawberry-django`'s `django_resolver`
  overhead on hot types. Targets **sync Django**.
- **`fastberry.rest`** (REST) — read-only nested serialization that assembles
  the tree from column-projected queries and encodes with `orjson`. Works on
  both **Django/DRF** and **FastAPI/SQLAlchemy** — the backend is picked from
  the model class.

## Install

The core package has no hard dependencies; pick the extra for the helper you
want, and only that stack gets pulled in:

```bash
pip install 'fastberry[graphql]'     # GraphQL: fast_path on strawberry-django (+ Django, strawberry)
pip install 'fastberry[rest]'        # REST on Django/DRF (+ Django, orjson)
pip install 'fastberry[sqlalchemy]'  # REST on FastAPI/SQLAlchemy — no Django (+ SQLAlchemy, orjson)
```

Requires Python 3.10+. Django (4.2+) is only installed by the `graphql` and
`rest` extras; the `sqlalchemy` extra is Django-free.

---

## GraphQL: `fast_path`

`strawberry-django` wraps every field resolver in `django_resolver`, which calls
`in_async_context()` on each resolution. Under sync Django that call raises and
catches a `RuntimeError` internally — a fixed per-field CPU cost (roughly a
microsecond or two per field on current strawberry-django; more on older
versions) with no extra database work. Because it is paid *per field*, on large
or wide result sets it adds up and dominates response time.

Mark hot types with `@fast_path` (outermost, after `@strawberry_django.type`)
and register `FastPathExtension` on the schema:

```python
import strawberry
import strawberry_django
from fastberry import fast_path, FastPathExtension

from myapp.models import Stock


@fast_path
@strawberry_django.type(Stock, disable_optimization=True)
class StockType:
    id: int
    title: str


@strawberry.type
class Query:
    stocks: list[StockType] = strawberry_django.field()


schema = strawberry.Schema(query=Query, extensions=[FastPathExtension])
```

Only types decorated with `@fast_path` take the fast path; everything else
resolves normally. To turn it off, remove the extension (global) or the
decorator (per type). Needs the `graphql` extra
(`pip install 'fastberry[graphql]'`).

### One decorator instead of two

To avoid stacking `@fast_path` + `@strawberry_django.type` on every hot type,
use the combined wrapper. It forwards all arguments to `strawberry_django` and
applies `fast_path` on top:

```python
from fastberry import strawberry_django as fast_strawberry_django

@fast_strawberry_django.type(Stock, disable_optimization=True)
class StockType:
    id: int
    title: str
```

`fast_strawberry_django.type` and `.interface` are exposed. You still register
`FastPathExtension` on the schema once. Needs the `graphql` extra
(`pip install 'fastberry[graphql]'`).

### Generate the GraphQL type from the model

If you don't want to hand-write the type at all, decorate the **model** with
`fast_schema`. It builds a `strawberry_django` type from the model's fields,
applies `fast_path`, and stores it on the model as `__fast_type__`:

```python
from fastberry.strawberry_django import fast_schema

@fast_schema
class Stock(models.Model): ...                       # all concrete fields

@fast_schema(fields=["id", "title"], name="StockType")
class Other(models.Model): ...                        # subset + custom name

StockType = Stock.__fast_type__                       # wire into your schema
```

Extra keyword args (e.g. `disable_optimization=True`) are forwarded to
`strawberry_django.type`. The decorator returns the model unchanged, so it
composes with other model decorators. Needs the `graphql` extra.

**How it works:** the field→resolver map is built once, at class-definition
time, keyed by the GraphQL type name (`info.parent_type.name`). Plain fields
resolve via a direct `getattr`; related managers are materialized with `.all()`;
custom resolvers are called directly, bypassing the `django_resolver` wrapper.

**Benchmark** (the [`strawberry_django` example](example/strawberry_django);
3 200 stocks, sync Django + Postgres, query optimizer enabled on both sides so
only the per-field resolver overhead differs). The win scales with the number
of fields resolved per type — wide, hot types benefit most:

| Fields / type | Without fast-path | With fast-path | Speedup |
| ------------: | ----------------: | -------------: | ------- |
| 1             | 46.7 ms           | 37.1 ms        | 1.26×   |
| 8             | 123.9 ms          | 78.7 ms        | 1.57×   |
| 32            | 380.5 ms          | 214.4 ms       | 1.77×   |
| 64            | 726.0 ms          | 403.9 ms       | 1.80×   |

The speedup is roughly flat across dataset size (~1.5× on a 5-field type) and
grows with query depth and field count; on a wide real schema (~27 fields/type)
it reaches ~2.4×. See [`example/BENCHMARKS.md`](example/BENCHMARKS.md) for the
full size/depth/field sweeps.

---

## REST: `fastberry.rest`

A nested serializer (DRF's `ModelSerializer`, or hand-rolled object-graph
walking) builds an instance at every node of a relational tree and runs a
per-field pipeline across the whole tree. On a deep tree (3-4 relations) this
becomes the bottleneck even at a few hundred top-level objects.

`fastberry.rest` declares the output shape once, then at serialization time
fetches each level with a single column-projected query, assembles the tree in
Python via indexed dicts (no N+1), and encodes with `orjson`. It is **read-only
by design** — keep validation and writes on DRF or Pydantic.

It works on **Django/DRF** and **FastAPI/SQLAlchemy** as equal, first-class
backends: you write the `FastRest` declaration once and the backend is picked
from the model class. Needs the `rest` extra for Django
(`pip install 'fastberry[rest]'`) or the `sqlalchemy` extra for SQLAlchemy
(`pip install 'fastberry[sqlalchemy]'`).

### Declare the shape (both backends)

```python
from fastberry.rest import FastRest


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
    stocks = StockRest(many=True)          # reverse FK

    class Meta:
        model = Space
        fields = ["id", "name"]


class HouseRest(FastRest):
    spaces = SpaceRest(many=True)

    class Meta:
        model = House
        fields = ["id", "name", "address"]
```

The same four classes run unchanged whether `Product`/`Stock`/`Space`/`House`
are Django models or SQLAlchemy mapped classes — only the call that drives them
differs, as shown below.

### Django / DRF

Serialize a queryset directly:

```python
rows = HouseRest.serialize(House.objects.all())       # list[dict]
body = HouseRest.serialize_json(House.objects.all())  # bytes (orjson)
```

Or skip wiring a schema per view: decorate the model with `@fast_rest` and use
`FastJSONRenderer`. The view returns a raw queryset/instance; the renderer finds
the registered schema and fast-serializes it. Unregistered models fall back to
DRF's normal JSON.

```python
from fastberry.rest import fast_rest
from fastberry.rest_renderers import FastJSONRenderer


@fast_rest(fields=["id", "title", "amount"])     # explicit field list
class Stock(models.Model): ...


@fast_rest(depth=2)                               # auto-derive: expand 2 levels
class House(models.Model): ...                    # FKs -> nested objects,
                                                  # reverse FKs -> nested lists


class HouseList(APIView):
    renderer_classes = [FastJSONRenderer]
    def get(self, request):
        return Response(House.objects.all())      # no serializer needed
```

`@fast_rest` styles (mutually exclusive):

- **`fields=[...]`** (+ optional `nested={"attr": SubSchema}`) — you control
  exactly what is emitted. Recommended when the model has sensitive columns.
- **`depth=N`** — auto-derive from the model's fields/relations, expanding `N`
  relation levels (cycles broken by falling back to the FK id). `depth=0` emits
  scalars + FK ids only. **Auto-derive emits every field at each expanded
  level** — prefer explicit `fields` on models with secrets.
- Omitted — all concrete fields, FKs as ids, no nesting.

You can also register a hand-written nested `FastRest` for renderer pickup with
`register_schema(Model, MyRest)`. Set `FastJSONRenderer` globally via DRF's
`DEFAULT_RENDERER_CLASSES` to apply it everywhere; only `@fast_rest` models take
the fast path, so it's safe alongside ordinary endpoints.

### FastAPI / SQLAlchemy

Declare the same classes against your SQLAlchemy models. SQLAlchemy needs a
session, so pass `session=` to `serialize*()` (a `select()` is optional for
filtering/ordering; omit the source for all rows):

```python
rows = HouseRest.serialize(session=session)                       # all rows
body = HouseRest.serialize_json(select(House).where(...), session=session)
```

In FastAPI, hand the bytes straight back — no DRF, no renderer:

```python
@app.get("/houses")
def houses(session: Session = Depends(get_session)):
    return Response(HouseRest.serialize_json(session=session),
                    media_type="application/json")
```

See the runnable [`example/fastapi`](example/fastapi) project. (This works only
with an ORM `fastberry.rest` understands — Django or SQLAlchemy — not ORM-less
stacks or other ORMs.)

### Benchmark

Measured on the [`django` example](example/django); the SQLAlchemy backend runs
the same column-projected, one-query-per-level fetch. 200 houses × 4 spaces × 8
stocks = 6400 leaves, 4 levels deep, plus an FK to product; full tree queryset →
JSON bytes, Postgres:

| Approach                      | min ms  | queries | vs DRF+prefetch |
| ----------------------------- | ------- | ------- | --------------- |
| DRF nested, no prefetch       | 1891    | 7401    | 0.05×           |
| DRF nested, with prefetch     | 91.6    | 4       | 1.0×            |
| **fastberry.rest FastRest**   | **15.9**| **4**   | **5.8×**        |

The advantage *grows* with payload size — ~3.4× at 300 leaves up to ~6.9× at
32 000 — while the query count stays flat at 4. See
[`example/BENCHMARKS.md`](example/BENCHMARKS.md) for the full sweep.

Supported relations in this version: forward foreign key (single) and reverse
foreign key / one-to-many (`many=True`), on both the Django and SQLAlchemy
backends. ManyToMany is not yet handled.

---

## Caveats

- `@fast_path` targets **sync Django** specifically — async resolution doesn't
  pay the `django_resolver` overhead it removes. `fastberry.rest` has no such
  restriction; it works on Django/DRF and FastAPI/SQLAlchemy alike.
- Both helpers are read-optimized. `@fast_path` skips custom resolver logic;
  `fastberry.rest` does no validation. Use them on read-heavy paths; keep
  complex/write logic on the default framework path.

## Links

- Examples: [`example/`](example) — runnable Strawberry, strawberry-django,
  Django/DRF, and FastAPI/SQLAlchemy projects (each with a
  `docker-compose.yml`), plus [`example/BENCHMARKS.md`](example/BENCHMARKS.md)
- Source: <https://github.com/davidsarosi92/fastberry>
- Issues: <https://github.com/davidsarosi92/fastberry/issues>

## License

MIT
