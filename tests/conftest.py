"""Shared Django configuration for the test suite.

Configures Django once for all tests so individual test modules don't each call
``settings.configure`` (which clashes when the whole suite runs together).
``rest_test_app`` is a real, importable package under ``tests/`` so models
declared with ``app_label = "rest_test_app"`` have a home and their tables can
be created.
"""

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "rest_test_app",
        ],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    )
    django.setup()