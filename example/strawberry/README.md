# Pure Strawberry example

Standalone Strawberry GraphQL server (no Django, in-memory data) showing how to
wire fastberry's low-level GraphQL helpers:

- `fast_path` — decorator marking a Strawberry type for fast field resolution.
- `FastPathExtension` — schema extension that activates the fast path.

See [`app/schema.py`](app/schema.py) for the wiring and [`benchmark.py`](benchmark.py)
for a timing comparison.

> **Note.** `fast_path`'s performance benefit comes from bypassing
> `strawberry-django`'s `django_resolver` overhead under **sync Django**. Plain
> Strawberry types have no such wrapper, so here `fast_path` is a transparent,
> zero-cost passthrough and the benchmark shows parity. This example exists to
> show the **API/wiring**; for the real speedup see
> [`../strawberry_django`](../strawberry_django).

## Run with docker-compose

```bash
docker compose up --build
```

Then open http://localhost:8000/ for the GraphiQL playground.

## Run locally

From the repo root, install the package (base install is enough — pure
Strawberry needs neither the `rest` nor the `graphql` extra) and this example's
deps:

```bash
pip install -e .
pip install -r example/strawberry/requirements.txt
```

Then, from this directory:

```bash
uvicorn asgi:app --reload      # serve GraphiQL at http://localhost:8000/
python benchmark.py            # with vs without FastPathExtension
```

## Example query

```graphql
{
  houses {
    id
    name
    spaces {
      name
      stocks {
        title
        price
        product { name ean }
      }
    }
  }
}
```
