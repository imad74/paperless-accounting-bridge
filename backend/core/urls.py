from django.urls import path

from .views import HomeView, health_check

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("health/", health_check, name="health_check"),
]
