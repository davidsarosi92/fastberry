"""Run the same deep GraphQL query with and without FastPathExtension.

    python manage.py benchmark

This is where fast_path earns its keep: under sync Django every field on a
``strawberry_django`` type goes through ``django_resolver``, which calls
``in_async_context()`` (a raise/catch of RuntimeError, ~0.15 ms) per field.
``FastPathExtension`` bypasses that. Expect a meaningful speedup on the deep
tree. Run `python manage.py seed` first.
"""

import time

from django.core.management.base import BaseCommand

from catalog.models import House
from catalog.schema import plain_schema, schema

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


def _run(s, runs):
    result = s.execute_sync(QUERY)
    assert result.errors is None, result.errors
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        s.execute_sync(QUERY)
        best = min(best, time.perf_counter() - start)
    return best * 1000


class Command(BaseCommand):
    help = "Benchmark a deep GraphQL query with vs without FastPathExtension."

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=5)

    def handle(self, *args, **opts):
        if not House.objects.exists():
            self.stderr.write("No data. Run `python manage.py seed` first.")
            return

        runs = opts["runs"]
        without = _run(plain_schema, runs)
        with_fp = _run(schema, runs)

        self.stdout.write(f"\n{'schema':30s} {'min ms':>8s}")
        self.stdout.write("-" * 40)
        self.stdout.write(f"{'plain strawberry-django':30s} {without:8.1f}")
        self.stdout.write(f"{'with FastPathExtension':30s} {with_fp:8.1f}")
        self.stdout.write(f"\nspeedup: {without / with_fp:.2f}x")
