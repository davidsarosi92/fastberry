# Build context is the repo root (see docker-compose.yml) so we can install the
# local fastberry package alongside this example.
FROM python:3.13-slim

ENV SETUPTOOLS_SCM_PRETEND_VERSION=0.1.0 \
    PYTHONUNBUFFERED=1

WORKDIR /pkg
COPY . /pkg

RUN pip install --upgrade pip \
    && pip install "/pkg[sqlalchemy]" \
    && pip install -r /pkg/example/fastapi/requirements.txt

WORKDIR /pkg/example/fastapi
RUN chmod +x entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
