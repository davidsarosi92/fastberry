# fastberry benchmarks

Speedup data collected from the example projects, swept across dataset size,
query shape, and field count. Absolute milliseconds are machine-dependent — the
**ratios** (speedup) are the takeaway.

## Environment

- Postgres 16 (the examples' `docker-compose.yml` setup)
- Python 3.13, Django 6.0.5, djangorestframework 3.17.1, orjson 3.11.9
- strawberry-graphql 0.316.0, strawberry-graphql-django 0.86.0, fastberry 0.1.0
- Each data point is the **best of 3–4 runs** after one warm-up, querying the
  full tree to JSON.
- Domain shape: `House → Space → Stock → Product` (one forward FK + two reverse
  FK levels).

Reproduce: bring up an example with `docker compose up -d`, then run the sweep
snippets via `docker compose exec -T web python - < script.py` (the exact
scripts used are in this PR's history), or just
`docker compose exec web python manage.py benchmark` for the single-config
number.

---

## REST — `fastberry.rest` vs DRF nested `ModelSerializer`

Serializing the whole tree to JSON. Query count is **constant (4)** for both
prefetch-DRF and fastberry — one query per level, no N+1.

| Leaves (stocks) | DRF, no prefetch | DRF + prefetch | fastberry.rest | **vs prefetch** | vs no-prefetch |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 300    | 92.6 ms (381 q) | 6.6 ms  | 1.9 ms  | **3.4×** | 48× |
| 1 600  | 460 ms (1851 q) | 24.4 ms | 4.9 ms  | **5.0×** | 94× |
| 6 400  | — *(N+1, ~thousands of q)* | 91.6 ms | 15.9 ms | **5.8×** | — |
| 16 000 | —               | 237 ms  | 39.2 ms | **6.0×** | — |
| 32 000 | —               | 564 ms  | 81.8 ms | **6.9×** | — |

**Takeaways**

- **~5–7× over a properly prefetched DRF serializer**, and the ratio *grows*
  with dataset size: DRF builds a serializer instance and runs its per-field
  pipeline at every node, so its constant per-object cost compounds.
- Versus a naive (no-prefetch) serializer the gap is **1–2 orders of
  magnitude** — but that is mostly the N+1 query explosion, not fastberry's
  doing. Prefetch is the fair baseline.
- fastberry holds the query count flat (4) regardless of size.

---

## GraphQL — `FastPathExtension` vs plain strawberry-django

Same schema, query optimizer enabled on both sides; the **only** difference is
`FastPathExtension`. So this isolates the per-field `django_resolver` /
`in_async_context()` overhead that `fast_path` removes.

### By dataset size (full-depth query, ~5 fields/type)

| Houses | Stocks | plain | with fast_path | speedup |
| ---: | ---: | ---: | ---: | ---: |
| 50  | 1 600  | 73.0 ms  | 46.9 ms  | 1.56× |
| 100 | 3 200  | 140.8 ms | 92.3 ms  | 1.53× |
| 200 | 6 400  | 278.9 ms | 179.5 ms | 1.55× |
| 400 | 12 800 | 557.0 ms | 365.2 ms | 1.53× |

The ratio is **flat (~1.5×) across scale** — both paths are linear in the
number of resolved fields, so fast_path shaves a constant fraction.

### By query depth (100×4×8 dataset)

| Query | plain | with fast_path | speedup |
| --- | ---: | ---: | ---: |
| L1 — houses only            | 2.1 ms   | 1.5 ms  | 1.36× |
| L2 — + spaces               | 10.3 ms  | 7.0 ms  | 1.48× |
| L3 — + stocks               | 86.0 ms  | 56.2 ms | 1.53× |
| L4 — + products (full tree) | 138.7 ms | 92.3 ms | 1.50× |

The deeper the selection, the more fields get resolved, the larger the win.

### By field count per node — *the main driver* (100×4×8 = 3 200 stocks)

Scalar fields per stock varied with GraphQL aliases (each alias = one field
resolution).

| Fields / stock | Field resolutions | plain | with fast_path | speedup | µs saved / field |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1  | 3 200   | 46.7 ms  | 37.1 ms  | 1.26× | — |
| 4  | 12 800  | 79.9 ms  | 54.8 ms  | 1.46× | 1.96 |
| 8  | 25 600  | 123.9 ms | 78.7 ms  | 1.57× | 1.77 |
| 16 | 51 200  | 208.6 ms | 127.1 ms | 1.64× | 1.59 |
| 32 | 102 400 | 380.5 ms | 214.4 ms | 1.77× | 1.62 |
| 64 | 204 800 | 726.0 ms | 403.9 ms | 1.80× | 1.57 |

**Takeaways**

- **The speedup scales with the number of fields per type**: ~1.26× at 1 field,
  ~1.8× at 64 and still climbing. Wide types (the README's real schema had ~27
  fields/type → ~2.4×) benefit most; narrow types benefit least.
- The saving is a **constant ~1.6 µs per field resolution** on this stack. That
  is notably smaller than the ~0.15 ms/field quoted in the older README
  measurement — modern strawberry / strawberry-django have made
  `in_async_context()` cheaper, so the *relative* win on a given schema is more
  modest now (≈1.5× on a 5-field type) but still real and free.
- Because it is a per-field constant, the win is predictable:
  `time_saved ≈ 1.6 µs × (total fields resolved)`.

---

## REST on SQLAlchemy — `fastberry.rest` vs ORM objects (FastAPI example)

Same tree, but the [`fastapi` example](fastapi) on the **SQLAlchemy**
backend. The baseline is the usual FastAPI pattern: load full ORM objects (with
`selectinload`, so the query count matches) and build the nested dicts by hand.
fastberry projects columns straight to dicts instead.

| Approach | min ms | queries | speedup |
| --- | ---: | ---: | --- |
| SQLAlchemy ORM objects + manual dicts | 68.5 ms | 5 | 1.0× |
| **fastberry.rest** | **26.0 ms** | **4** | **2.6×** |

*(200 × 4 × 8 = 6 400 stocks, Postgres.)*

**Takeaway:** ~2.6× over hydrated ORM objects. The win is smaller than vs DRF
(SQLAlchemy's instance loading is leaner than DRF's serializer pipeline) but
still meaningful — and it confirms the helper is **not Django-specific**: the
identical `FastRest` declarations run under FastAPI + SQLAlchemy.

---

## Pure Strawberry (no Django)

`fast_path` is a transparent no-op here: plain Strawberry types never had the
`django_resolver` wrapper, so there is nothing to bypass.

| | with FastPathExtension | plain schema |
| --- | ---: | ---: |
| full-depth query | 30.8 ms | 30.3 ms |

**Parity by design.** This example exists to show the API/wiring; the helper
only pays off under sync Django.

---

## Summary

| Case | Typical speedup | Grows with |
| --- | --- | --- |
| `fastberry.rest` (Django) vs DRF + prefetch | **5–7×** | dataset size |
| `fastberry.rest` (Django) vs DRF no prefetch | 50–100× | (N+1 baseline — not a fair comparison) |
| `fastberry.rest` (SQLAlchemy) vs ORM objects | **~2.6×** | dataset size |
| `FastPathExtension` vs plain strawberry-django | **~1.5×** (up to ~1.8×+) | fields per type, query depth |
| pure Strawberry | ~1.0× (no-op) | — |

**Rules of thumb**

- Reach for **`fastberry.rest`** on read-heavy, deeply-nested REST endpoints —
  the win is large (2.6× vs SQLAlchemy objects, 5×+ vs DRF) and grows with
  payload size. Works on both the Django and SQLAlchemy backends.
- Reach for **`fast_path`** on GraphQL types that are both **wide** (many
  fields) and **hot** (returned in large lists). The win is a constant fraction
  that compounds with field count; on narrow types it is marginal.
- `fast_path` targets sync-Django resolver overhead; `fastberry.rest` is a
  read-path optimization for either ORM. Neither helps write paths.
