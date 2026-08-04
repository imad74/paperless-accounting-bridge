from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("core.urls")),

    # Companies
    path("companies/", include("companies.urls")),
    path(
        "document-types/",
        include("documents.document_type_urls"),
    ),
]
