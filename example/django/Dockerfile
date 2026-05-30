# Build context is the repo root (see docker-compose.yml) so we can install the
# local fastberry package alongside this example.
FROM python:3.13-slim

ENV SETUPTOOLS_SCM_PRETEND_VERSION=0.1.0 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /pkg
COPY . /pkg

RUN pip install --upgrade pip \
    && pip install "/pkg[rest]" \
    && pip install -r /pkg/example/django/requirements.txt

WORKDIR /pkg/example/django
RUN chmod +x entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
