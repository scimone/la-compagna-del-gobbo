from django.urls import path

from apps.frontend import views

urlpatterns = [
    path("", views.index, name="index"),
    path("characters/", views.characters_overview, name="characters-overview"),
    path("handbook/", views.handbook_overview, name="handbook-overview"),
    path("world/", views.world, name="world-overview"),
    path("world/backgrounds/", views.world_backgrounds, name="world-backgrounds"),
    path(
        "world/backgrounds/<slug:pk>/",
        views.world_background_detail,
        name="world-background-detail",
    ),
    path("world/classes/", views.world_classes, name="world-classes"),
    path("world/classes/<slug:pk>/", views.world_class_detail, name="world-class-detail"),
    path("world/feats/", views.world_feats, name="world-feats"),
    path("world/feats/<slug:pk>/", views.world_feat_detail, name="world-feat-detail"),
    path("world/species/", views.world_species, name="world-species"),
    path("world/species/<slug:pk>/", views.world_species_detail, name="world-species-detail"),
    path("world/spells/", views.world_spells, name="world-spells"),
    path("world/spells/<slug:pk>/", views.world_spell_detail, name="world-spell-detail"),
    path("world/rules/<slug:pk>/", views.world_rule_detail, name="world-rule-detail"),
]
