from django.urls import path

from .views import CompanySelectionView


app_name = "accounts"

urlpatterns = [
    path("company/select/", CompanySelectionView.as_view(), name="company_select"),
]
