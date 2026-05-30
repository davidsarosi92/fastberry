# fastberry examples

Three self-contained projects, one per ecosystem fastberry targets. Each has its
own folder, its own `docker-compose.yml`, and a benchmark.

| Example | Stack | fastberry features |
| --- | --- | --- |
| [`strawberry/`](strawberry) | Pure Strawberry GraphQL (no DB, in-memory) | `fast_path`, `FastPathExtension` — wiring/API only |
| [`django/`](django) | Django + DRF REST (Postgres) | `fastberry.rest`: `@fast_rest` (explicit + `depth` auto-derive), hand-written `FastRest` + `register_schema`, `FastJSONRenderer` |
| [`strawberry_django/`](strawberry_django) | strawberry-django GraphQL (Postgres) | `fast_strawberry_django.type`, `@fast_schema`, `FastPathExtension` — the real speedup |
| [`fastapi/`](fastapi) | FastAPI + SQLAlchemy (Postgres) | `fastberry.rest` on the **SQLAlchemy** backend — same `FastRest`, no DRF |

All three use the same domain shape — **House → Space → Stock → Product** — so
the schemas line up across examples.

📊 See [`BENCHMARKS.md`](BENCHMARKS.md) for measured speedups swept across
dataset size, query depth, and field count.

## Quick start

Each example runs on its own:

```bash
cd strawberry          && docker compose up --build   # http://localhost:8000/
cd django              && docker compose up --build   # http://localhost:8000/houses/
cd strawberry_django   && docker compose up --build   # http://localhost:8000/graphql/
cd fastapi             && docker compose up --build   # http://localhost:8000/houses
```

> Run them one at a time — the `django`, `strawberry_django`, and `fastapi`
> examples all publish ports `8000` (web) and `5432` (Postgres).

The Docker builds install the **local** `fastberry` from the repo root, so the
examples always exercise your working copy.

## Running without Docker

Install fastberry editable from the repo root with the right extra, then follow
each example's README:

```bash
pip install -e '.[graphql]'      # GraphQL examples
pip install -e '.[rest]'         # Django REST example
pip install -e '.[sqlalchemy]'   # FastAPI example
```

The `django`, `strawberry_django`, and `fastapi` examples expect a Postgres at
`localhost:5432` (db/user/password = `fastberry`); the pure-Strawberry example
needs no database.

## Where the speedup is

`fast_path` removes `strawberry-django`'s per-field `django_resolver` overhead
under **sync** Django; `fastberry.rest` replaces the per-node serializer /
object-graph pipeline on read paths (DRF on Django, ORM-object loading on
SQLAlchemy). The pure-Strawberry example has neither overhead to remove, so its
benchmark shows parity by design — it's there to show the API. The genuine
numbers live in the `django`, `strawberry_django`, and `fastapi` benchmarks.
