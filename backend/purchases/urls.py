from django.urls import path

from . import views


app_name = "purchases"

urlpatterns = [
    path("", views.PurchaseInvoiceListView.as_view(), name="list"),
    path("import/", views.PurchaseInvoiceImportView.as_view(), name="import"),
    path("suppliers/new/", views.SupplierCreateView.as_view(), name="supplier_create"),
    path("<int:pk>/", views.PurchaseInvoiceUpdateView.as_view(), name="update"),
    path("<int:pk>/validate/", views.PurchaseInvoiceValidateView.as_view(), name="validate"),
]
