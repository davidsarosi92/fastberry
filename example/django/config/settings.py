"""Minimal Django settings for the fastberry REST example.

Postgres everywhere (see the answer in the project README). Connection details
come from environment variables with sane localhost defaults, so the same
settings work both under docker-compose (DB_HOST=db) and locally.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "example-only-not-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "catalog",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "fastberry"),
        "USER": os.environ.get("DB_USER", "fastberry"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "fastberry"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

# fastberry's renderer is set globally here. Only models decorated with
# @fast_rest take the fast path; every other endpoint falls back to DRF's
# standard JSON renderer, so this is safe to enable everywhere.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "fastberry.rest_renderers.FastJSONRenderer",
    ],
}
