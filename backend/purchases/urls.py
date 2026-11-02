from django.urls import path

from . import views


app_name = "purchases"

urlpatterns = [
    path("", views.PurchaseInvoiceListView.as_view(), name="list"),
    path("import/", views.PurchaseInvoiceImportView.as_view(), name="import"),
    path("suppliers/", views.SupplierListView.as_view(), name="supplier_list"),
    path("suppliers/export.xlsx", views.SupplierExportView.as_view(), name="supplier_export"),
    path("suppliers/new/", views.SupplierCreateView.as_view(), name="supplier_create"),
    path("suppliers/<int:pk>/", views.SupplierUpdateView.as_view(), name="supplier_update"),
    path("<int:pk>/", views.PurchaseInvoiceUpdateView.as_view(), name="update"),
    path(
        "<int:pk>/refresh-supplier/",
        views.PurchaseInvoiceRefreshSupplierView.as_view(),
        name="refresh_supplier",
    ),
    path("<int:pk>/validate/", views.PurchaseInvoiceValidateView.as_view(), name="validate"),
]
