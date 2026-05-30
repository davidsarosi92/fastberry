"""Run the same query with and without FastPathExtension and time it.

    python benchmark.py

On plain Strawberry types the two paths are equivalent, so expect parity (this
example is about *wiring*, not speedup). The genuine win shows up under
strawberry-django — see ../strawberry_django/catalog/management/commands/benchmark.py
"""

from __future__ import annotations

import time

from app.schema import plain_schema, schema

QUERY = """
{
  houses {
    id
    name
    address
    spaces {
      id
      name
      stocks {
        id
        title
        amount
        price
        product { id name ean }
      }
    }
  }
}
"""


def _time(s, runs: int) -> float:
    # Warm up once, then take the best of `runs` to reduce noise.
    s.execute_sync(QUERY)
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        result = s.execute_sync(QUERY)
        best = min(best, time.perf_counter() - start)
        assert result.errors is None, result.errors
    return best * 1000


def main() -> None:
    runs = 10
    with_ext = _time(schema, runs)
    without = _time(plain_schema, runs)
    print(f"{'with FastPathExtension':30s} {with_ext:7.1f} ms")
    print(f"{'plain Strawberry schema':30s} {without:7.1f} ms")
    print()
    print(
        "Parity is expected here: plain Strawberry has no django_resolver to "
        "bypass.\nSee the strawberry_django example for the real speedup."
    )


if __name__ == "__main__":
    main()
