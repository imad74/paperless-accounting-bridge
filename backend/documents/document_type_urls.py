from django.urls import path

from .views import (
    DocumentTypeCreateView,
    DocumentTypeListView,
    DocumentTypeToggleActiveView,
    DocumentTypeUpdateView,
)


app_name = "document_types"

urlpatterns = [
    path("", DocumentTypeListView.as_view(), name="list"),
    path("new/", DocumentTypeCreateView.as_view(), name="create"),
    path("<int:pk>/edit/", DocumentTypeUpdateView.as_view(), name="update"),
    path(
        "<int:pk>/toggle-active/",
        DocumentTypeToggleActiveView.as_view(),
        name="toggle_active",
    ),
]
