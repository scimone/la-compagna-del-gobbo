from django.urls import path

from apps.frontend import views

urlpatterns = [
    path("", views.index, name="index"),
    path("characters/", views.characters_overview, name="characters-overview"),
    path("handbook/", views.handbook_overview, name="handbook-overview"),
    path("world/", views.world_overview, name="world-overview"),
]
