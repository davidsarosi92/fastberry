# Build context is the repo root (see docker-compose.yml) so we can install the
# local fastberry package alongside this example.
FROM python:3.13-slim

# Fallback version for hatch-vcs when building without git tags/history.
ENV SETUPTOOLS_SCM_PRETEND_VERSION=0.1.0 \
    PYTHONUNBUFFERED=1

WORKDIR /pkg
COPY . /pkg

RUN pip install --upgrade pip \
    && pip install /pkg \
    && pip install -r /pkg/example/strawberry/requirements.txt

WORKDIR /pkg/example/strawberry
EXPOSE 8000
CMD ["uvicorn", "asgi:app", "--host", "0.0.0.0", "--port", "8000"]
