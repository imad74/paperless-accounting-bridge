from django.urls import path
from . import views
urlpatterns=[path("",views.DocumentListView.as_view(),name="document_list")]
