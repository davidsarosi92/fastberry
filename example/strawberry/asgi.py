"""ASGI entrypoint: ``uvicorn asgi:app``.

Serves a GraphiQL playground at http://localhost:8000/ and the GraphQL endpoint
at the same path.
"""

from strawberry.asgi import GraphQL

from app.schema import schema

app = GraphQL(schema)
