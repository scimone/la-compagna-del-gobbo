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
    path("world/class-features/", views.world_class_features, name="world-class-features"),
    path(
        "world/class-features/<int:pk>/",
        views.world_class_feature_detail,
        name="world-class-feature-detail",
    ),
    path("world/feats/", views.world_feats, name="world-feats"),
    path("world/feats/<slug:pk>/", views.world_feat_detail, name="world-feat-detail"),
    path("world/races/", views.world_races, name="world-races"),
    path("world/races/<slug:pk>/", views.world_race_detail, name="world-race-detail"),
    path("world/subraces/", views.world_subraces, name="world-subraces"),
    path("world/spells/", views.world_spells, name="world-spells"),
    path("world/spells/<slug:pk>/", views.world_spell_detail, name="world-spell-detail"),
    path("world/rules/<slug:pk>/", views.world_rule_detail, name="world-rule-detail"),
]
