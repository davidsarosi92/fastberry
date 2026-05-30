# strawberry-django (GraphQL over Django) example

Demonstrates fastberry's GraphQL helpers on a real `strawberry-django` schema —
this is where `fast_path` delivers its headline speedup.

What's shown:

| File | fastberry feature |
| --- | --- |
| [`catalog/models.py`](catalog/models.py) | `@fast_schema(...)` generates `Product.__fast_type__` from the model |
| [`catalog/schema.py`](catalog/schema.py) | `fast_strawberry_django.type` (combined `strawberry_django.type` + `fast_path`) for the hand-written types, and `FastPathExtension` on the schema |
| [`.../commands/benchmark.py`](catalog/management/commands/benchmark.py) | same deep query with vs without `FastPathExtension` |

### Why it's faster

Under **sync** Django, `strawberry-django` wraps every field resolver in
`django_resolver`, which calls `in_async_context()` on each resolution — a
raise/catch of `RuntimeError` costing ~0.15 ms *per field*. On a deep tree with
thousands of fields this dominates response time, with zero extra DB work.
`FastPathExtension` bypasses that wrapper for `fast_path`-marked types.

## Run with docker-compose

```bash
docker compose up --build
```

Starts Postgres, migrates, seeds, and serves GraphiQL at
http://localhost:8000/graphql/. Run the benchmark:

```bash
docker compose exec web python manage.py benchmark
```

## Run locally

Needs a Postgres reachable at `localhost:5432` (DB/user/password `fastberry`),
or override via `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT`.

From the repo root:

```bash
pip install -e '.[graphql]'
pip install -r example/strawberry_django/requirements.txt
```

Then from this directory:

```bash
python manage.py makemigrations catalog
python manage.py migrate
python manage.py seed --houses 200 --spaces 4 --stocks 8
python manage.py runserver        # GraphiQL at /graphql/
python manage.py benchmark
```

## Example query

```graphql
{
  houses {
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
