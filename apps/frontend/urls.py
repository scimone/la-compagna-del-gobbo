from django.urls import path

from apps.frontend import views

urlpatterns = [
    path("", views.index, name="index"),
]
