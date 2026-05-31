"""Nox sessions for fastberry.

    nox            # run the default set (lint, typecheck, tests, isolation)
    nox -l         # list sessions
    nox -s lint    # one session
    nox -s isolation   # the dependency-decoupling guard

`tests` runs the suite across the supported Python versions (missing
interpreters are skipped locally; CI provides all of them). `isolation` is the
important one for this package: the normal suite runs under the ``dev`` extra
where *everything* is installed, so it can never notice an optional dependency
leaking into the wrong import path. Those sessions install one extra at a time
and assert the boundaries hold.
"""

import nox

nox.options.sessions = ["lint", "typecheck", "tests", "isolation"]

PYTHONS = ["3.10", "3.11", "3.12", "3.13"]


@nox.session(python=PYTHONS)
def tests(session):
    """Run the test suite with coverage (fail-under enforced via pyproject)."""
    session.install("-e", ".[dev]")
    session.run("pytest", "--cov=fastberry", "--cov-report=term-missing", *session.posargs)


@nox.session
def lint(session):
    """Ruff lint + format check."""
    session.install("ruff>=0.6")
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")


@nox.session
def typecheck(session):
    """Static type check with mypy."""
    session.install("-e", ".[dev]")
    session.run("mypy")


# --- decoupling guards ------------------------------------------------------
# Each script installs exactly one extra and asserts that the *other* stacks
# are absent — i.e. that core stays dependency-free and the lazy imports hold.

_REST_ONLY = """
import fastberry.rest                       # imports with no strawberry present
import importlib.util as u
assert u.find_spec("strawberry") is None, "strawberry leaked into [rest]"
"""

_SQLALCHEMY_ONLY = """
import fastberry.rest                       # imports with no Django present
import importlib.util as u
assert u.find_spec("django") is None, "Django leaked into [sqlalchemy]"
"""

_GRAPHQL_ONLY = """
import fastberry
fastberry.fast_path                         # lazy GraphQL helper resolves
import importlib.util as u
assert u.find_spec("orjson") is None, "orjson leaked into [graphql]"
"""


@nox.session
@nox.parametrize(
    "extra,script",
    [("rest", _REST_ONLY), ("sqlalchemy", _SQLALCHEMY_ONLY), ("graphql", _GRAPHQL_ONLY)],
    ids=["rest", "sqlalchemy", "graphql"],
)
def isolation(session, extra, script):
    """An optional extra must install only its own stack."""
    session.install(f".[{extra}]")
    session.run("python", "-c", script)
