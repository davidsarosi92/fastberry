"""Compare fastberry.rest against the typical SQLAlchemy approach.

    python -m app.benchmark

The baseline loads full ORM objects (with selectinload, so the query count is
the same 4) and builds the nested dicts by hand — the usual FastAPI pattern.
fastberry.rest instead projects columns straight to dicts. Both issue the same
queries; the difference is the per-object ORM/instance overhead.

Run `python -m app.seed` first.
"""

import time

from sqlalchemy import event, select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal, engine
from app.models import House, Space, Stock
from app.schemas import HouseRest


def orm_nested(session):
    stmt = select(House).options(
        selectinload(House.spaces).selectinload(Space.stocks).selectinload(Stock.product)
    )
    houses = session.execute(stmt).scalars().all()
    return [
        {
            "id": h.id,
            "name": h.name,
            "address": h.address,
            "spaces": [
                {
                    "id": sp.id,
                    "name": sp.name,
                    "stocks": [
                        {
                            "id": st.id,
                            "title": st.title,
                            "amount": st.amount,
                            "price": str(st.price),
                            "product": {
                                "id": st.product.id,
                                "name": st.product.name,
                                "ean": st.product.ean,
                            },
                        }
                        for st in sp.stocks
                    ],
                }
                for sp in h.spaces
            ],
        }
        for h in houses
    ]


def fastberry(session):
    return HouseRest.serialize(session=session)


def _measure(label, fn, runs=3):
    count = {"n": 0}

    @event.listens_for(engine, "after_cursor_execute")
    def _c(*args):
        count["n"] += 1

    try:
        with SessionLocal() as s:
            fn(s)  # warm
        best = float("inf")
        for _ in range(runs):
            count["n"] = 0
            with SessionLocal() as s:
                start = time.perf_counter()
                fn(s)
                best = min(best, time.perf_counter() - start)
                queries = count["n"]
    finally:
        event.remove(engine, "after_cursor_execute", _c)
    return label, best * 1000, queries


def main():
    with SessionLocal() as s:
        if not s.execute(select(House.id).limit(1)).first():
            print("No data. Run `python -m app.seed` first.")
            return

    results = [
        _measure("SQLAlchemy ORM objects + manual dicts", orm_nested),
        _measure("fastberry.rest", fastberry),
    ]
    baseline = results[0][1]
    print(f"\n{'approach':40s} {'min ms':>8s} {'queries':>8s} {'speedup':>8s}")
    print("-" * 68)
    for label, ms, q in results:
        print(f"{label:40s} {ms:8.1f} {q:8d} {baseline / ms:7.1f}x")


if __name__ == "__main__":
    main()
