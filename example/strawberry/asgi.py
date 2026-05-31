"""ASGI entrypoint: ``uvicorn asgi:app``.

Serves a GraphiQL playground at http://localhost:8000/ and the GraphQL endpoint
at the same path.
"""

from app.schema import schema
from strawberry.asgi import GraphQL

app = GraphQL(schema)
