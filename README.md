# fastberry

Performance helpers for [strawberry-django](https://strawberry.rocks/docs/django)
GraphQL schemas running under **synchronous** Django.

`strawberry-django` wraps every field resolver in `django_resolver`, which calls
`in_async_context()` on each resolution. Under sync Django that call raises and
catches a `RuntimeError` internally (~0.15 ms per field). On large result sets
this dominates response time — pure CPU overhead with zero extra database
queries.

`fastberry` lets you opt specific "hot" types out of that machinery.

## Install

```bash
pip install fastberry
```

Requires Python 3.10+, Django 4.2+, and strawberry-graphql.

## Usage

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


schema = strawberry.Schema(
    query=Query,
    extensions=[FastPathExtension],
)
```

Only types decorated with `@fast_path` take the fast path; everything else
resolves normally. To turn the optimization off, remove the extension (global)
or the decorator (per type).

### How it works

- **Plain fields** resolve via a direct `getattr(root, attr)`. Related
  managers (`*-to-many`) are materialized with `.all()`.
- **Custom resolvers** are called directly, bypassing the `django_resolver`
  wrapper.

The field→resolver map is built once, at class-definition time, and keyed by the
GraphQL type name (`info.parent_type.name`) — not the Python class — because at
resolve time `root` is the Django model instance, not the Strawberry type.

## Benchmarks

Indicative numbers from a real schema (~3000 objects, ~27 fields each):

| Scenario        | Without fast-path | With fast-path | Speedup |
| --------------- | ----------------- | -------------- | ------- |
| `stocks_by_house` | 4.4 s           | 1.8 s          | ~2.4×   |

Your mileage will vary with field count and result-set size.

## Caveats

- Built for **sync** Django execution. Async schemas don't hit the overhead
  this targets.
- `@fast_path` does its own field resolution, so it skips any custom logic that
  `django_resolver` would otherwise apply. Use it on read-heavy, plain types;
  keep complex types on the default path.

## Links

- Source: <https://github.com/davidsarosi92/fastberry>
- Issues: <https://github.com/davidsarosi92/fastberry/issues>

## License

MIT