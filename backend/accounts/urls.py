from django.urls import path

from .views import (
    CompanyMembershipCreateView,
    CompanyMembershipDeleteView,
    CompanyMembershipListView,
    CompanyMembershipUpdateView,
    CompanySelectionView,
)


app_name = "accounts"

urlpatterns = [
    path("company/select/", CompanySelectionView.as_view(), name="company_select"),
    path("members/", CompanyMembershipListView.as_view(), name="membership_list"),
    path(
        "members/new/",
        CompanyMembershipCreateView.as_view(),
        name="membership_create",
    ),
    path(
        "members/<int:pk>/edit/",
        CompanyMembershipUpdateView.as_view(),
        name="membership_update",
    ),
    path(
        "members/<int:pk>/delete/",
        CompanyMembershipDeleteView.as_view(),
        name="membership_delete",
    ),
]
