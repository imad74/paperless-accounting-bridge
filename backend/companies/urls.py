from django.urls import path

from .views import (
    CompanyListView,
    CompanyCreateView,
    CompanyUpdateView,
    CompanyDeleteView,
)

app_name = "companies"

urlpatterns = [
    path(
        "",
        CompanyListView.as_view(),
        name="list",
    ),

    path(
        "new/",
        CompanyCreateView.as_view(),
        name="create",
    ),

    path(
        "<int:pk>/edit/",
        CompanyUpdateView.as_view(),
        name="update",
    ),

    path(
        "<int:pk>/delete/",
        CompanyDeleteView.as_view(),
        name="delete",
    ),
]