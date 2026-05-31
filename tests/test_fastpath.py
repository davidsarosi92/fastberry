"""Tests for fastberry.fastpath.

These exercise the registry/resolution logic in isolation, without spinning up a
full Django app or GraphQL request, by faking the minimal strawberry/Django
surface the extension touches. Django itself is configured once in conftest.py.
"""

import pytest

from fastberry.fastpath import FastPathExtension, fast_path

# --- minimal fakes for the strawberry surface fast_path/register inspect -------


class _FakeBaseResolver:
    def __init__(self, fn):
        self.wrapped_func = fn


class _FakeField:
    def __init__(self, name, graphql_name=None, base_resolver=None):
        self.name = name
        self.graphql_name = graphql_name
        self.base_resolver = base_resolver


class _FakeDefinition:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields


def _make_type(type_name, fields):
    cls = type(type_name, (), {})
    cls.__strawberry_definition__ = _FakeDefinition(type_name, fields)
    return cls


class _FakeParentType:
    def __init__(self, name):
        self.name = name


class _FakeInfo:
    def __init__(self, type_name, field_name):
        self.parent_type = _FakeParentType(type_name)
        self.field_name = field_name


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate the global registry between tests."""
    FastPathExtension._fast_path_type_names = set()
    FastPathExtension._registry = {}
    yield
    FastPathExtension._fast_path_type_names = set()
    FastPathExtension._registry = {}


def _sentinel_next(*args, **kwargs):
    return "FELLTHROUGH"


# --- tests --------------------------------------------------------------------


def test_plain_field_getattr():
    fast_path(_make_type("WidgetType", [_FakeField("title")]))

    ext = FastPathExtension()
    root = type("Widget", (), {"title": "hello"})()
    info = _FakeInfo("WidgetType", "title")

    assert ext.resolve(_sentinel_next, root, info) == "hello"


def test_camel_case_graphql_name():
    fast_path(_make_type("WidgetType", [_FakeField("created_at")]))

    ext = FastPathExtension()
    root = type("Widget", (), {"created_at": 42})()
    # GraphQL field name is camelCased by default.
    info = _FakeInfo("WidgetType", "createdAt")

    assert ext.resolve(_sentinel_next, root, info) == 42


def test_unregistered_type_falls_through():
    ext = FastPathExtension()
    root = object()
    info = _FakeInfo("UnknownType", "whatever")

    assert ext.resolve(_sentinel_next, root, info) == "FELLTHROUGH"


def test_unknown_field_on_registered_type_falls_through():
    fast_path(_make_type("WidgetType", [_FakeField("title")]))

    ext = FastPathExtension()
    root = type("Widget", (), {"title": "x"})()
    info = _FakeInfo("WidgetType", "missing")

    assert ext.resolve(_sentinel_next, root, info) == "FELLTHROUGH"


def test_manager_is_materialized():
    class _FakeQuerySet:
        def __init__(self, items):
            self._items = items

    from django.db.models import Manager

    class _FakeManager(Manager):
        def __init__(self, items):
            self._items = items

        def all(self):
            return _FakeQuerySet(self._items)

    fast_path(_make_type("WidgetType", [_FakeField("children")]))

    ext = FastPathExtension()
    mgr = _FakeManager([1, 2, 3])
    root = type("Widget", (), {"children": mgr})()
    info = _FakeInfo("WidgetType", "children")

    result = ext.resolve(_sentinel_next, root, info)
    assert isinstance(result, _FakeQuerySet)
    assert result._items == [1, 2, 3]


def test_custom_resolver_single_param():
    def resolver(root):
        return root.value * 2

    field = _FakeField("doubled", base_resolver=_FakeBaseResolver(resolver))
    fast_path(_make_type("WidgetType", [field]))

    ext = FastPathExtension()
    root = type("Widget", (), {"value": 21})()
    info = _FakeInfo("WidgetType", "doubled")

    assert ext.resolve(_sentinel_next, root, info) == 42


def test_custom_resolver_with_info_and_kwargs():
    def resolver(root, info, factor=1):
        return root.value * factor

    field = _FakeField("scaled", base_resolver=_FakeBaseResolver(resolver))
    fast_path(_make_type("WidgetType", [field]))

    ext = FastPathExtension()
    root = type("Widget", (), {"value": 10})()
    info = _FakeInfo("WidgetType", "scaled")

    assert ext.resolve(_sentinel_next, root, info, factor=3) == 30
