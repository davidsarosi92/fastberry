from django.urls import path
from strawberry.django.views import GraphQLView

from catalog.schema import schema

urlpatterns = [
    # GraphiQL playground + GraphQL endpoint.
    path("graphql/", GraphQLView.as_view(schema=schema)),
]
