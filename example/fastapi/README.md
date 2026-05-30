# FastAPI + SQLAlchemy example

Shows that `fastberry.rest` is **not tied to Django's web layer or DRF** — only
to an ORM. Here the ORM is **SQLAlchemy** (the de-facto FastAPI pairing, since
FastAPI ships none), and the web framework is **FastAPI**.

`fastberry.rest` introspects the SQLAlchemy mapped classes through its
SQLAlchemy backend and serializes with the exact same `FastRest` declarations
you'd use on Django models. The only difference: SQLAlchemy needs a session, so
you pass `session=...` to `serialize*()`.

What's shown:

| File | fastberry feature |
| --- | --- |
| [`app/models.py`](app/models.py) | plain SQLAlchemy 2.0 mapped classes |
| [`app/schemas.py`](app/schemas.py) | nested `FastRest` declarations (identical to the Django example) |
| [`app/main.py`](app/main.py) | FastAPI returns `serialize_json(...)` bytes directly — no DRF, no renderer |
| [`app/benchmark.py`](app/benchmark.py) | fastberry.rest vs loading ORM objects + building dicts by hand |

```python
# app/main.py — the whole integration is this:
@app.get("/houses")
def houses(session: Session = Depends(get_session)):
    body = schemas.HouseRest.serialize_json(session=session)   # bytes (orjson)
    return Response(content=body, media_type="application/json")
```

Endpoints:

- `GET /houses` — full tree
- `GET /houses/{id}` — single instance (`serialize_obj_json`)
- `GET /stocks` — stocks with nested product

## Run with docker-compose

```bash
docker compose up --build
```

Starts Postgres, seeds, and serves on http://localhost:8000/ (interactive docs
at http://localhost:8000/docs). Then:

```bash
curl http://localhost:8000/houses | head -c 500
docker compose exec web python -m app.benchmark
```

## Run locally

Needs a Postgres at `localhost:5432` (db/user/password `fastberry`), or override
via `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT`.

From the repo root:

```bash
pip install -e '.[sqlalchemy]'
pip install -r example/fastapi/requirements.txt
```

Then from this directory:

```bash
python -m app.seed 200 4 8
uvicorn app.main:app --reload
python -m app.benchmark
```

> **Note.** `fastberry.rest` works under FastAPI because this app uses an ORM it
> understands (SQLAlchemy). It does **not** apply to ORM-less stacks or other
> ORMs (Tortoise, Peewee, …). The `FastJSONRenderer` is Django/DRF-only and is
> not used here — you return the `serialize_json` bytes yourself.
