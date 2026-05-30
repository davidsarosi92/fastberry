# Django + DRF REST example

Demonstrates `fastberry.rest` — read-only nested serialization that replaces
DRF's per-node `ModelSerializer` pipeline on hot read paths.

What's shown:

| File | fastberry feature |
| --- | --- |
| [`catalog/models.py`](catalog/models.py) | `@fast_rest(depth=3)` (auto-derive) and `@fast_rest(fields=[...])` (explicit) |
| [`catalog/schemas.py`](catalog/schemas.py) | hand-written `FastRest` + `register_schema` |
| [`config/settings.py`](config/settings.py) | `FastJSONRenderer` set globally via `DEFAULT_RENDERER_CLASSES` |
| [`catalog/views.py`](catalog/views.py) | views return raw querysets/instances — no serializer wiring |
| [`.../commands/benchmark.py`](catalog/management/commands/benchmark.py) | fastberry.rest vs DRF nested serializer |

Endpoints:

- `GET /houses/` — full tree, auto-derived (`depth=3`)
- `GET /houses/<id>/` — single instance (`serialize_obj_json`)
- `GET /stocks/` — explicit field list (only declared columns)
- `GET /products/` — hand-written `ProductRest` (omits `cost_secret`)
- `GET /plain-stocks/` — plain DRF endpoint; proves `FastJSONRenderer` falls back
  safely for unregistered data

> **Security note.** `@fast_rest(depth=...)` auto-derive emits *every* field at
> each expanded level. `Product.cost_secret` therefore appears in the nested
> `/houses/` tree. On models with sensitive columns prefer the explicit
> `fields=[...]` form (see `Stock`) or a hand-written `FastRest` (see `Product`).

## Run with docker-compose

```bash
docker compose up --build
```

This starts Postgres, runs migrations, seeds the data, and serves on
http://localhost:8000/. Try:

```bash
curl http://localhost:8000/houses/ | head -c 500
docker compose exec web python manage.py benchmark
```

## Run locally

Needs a Postgres reachable at `localhost:5432` (DB/user/password `fastberry`),
or override via `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT`.

From the repo root:

```bash
pip install -e '.[rest]'
pip install -r example/django/requirements.txt
```

Then from this directory:

```bash
python manage.py makemigrations catalog
python manage.py migrate
python manage.py seed --houses 200 --spaces 4 --stocks 8
python manage.py runserver
python manage.py benchmark
```
