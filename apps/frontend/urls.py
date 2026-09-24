from django.urls import path

from apps.frontend import character_sheet, character_views, views

urlpatterns = [
    path("", views.index, name="index"),
    path("characters/", character_views.characters_list, name="characters-overview"),
    path("characters/new/", character_views.character_new, name="character-new"),
    path(
        "characters/describe/<slug:kind>/<slug:pk>/",
        character_views.describe,
        name="character-describe",
    ),
    path("characters/<int:pk>/", character_sheet.character_detail, name="character-detail"),
    path("characters/<int:pk>/act/", character_sheet.character_act, name="character-act"),
    path("characters/<int:pk>/items/", character_sheet.character_items, name="character-items"),
    path("characters/<int:pk>/spells/", character_sheet.character_spells, name="character-spells"),
    path(
        "characters/<int:pk>/features/",
        character_sheet.character_features,
        name="character-features",
    ),
    # One item's page: what a row of the inventory (a stack of catalog gear, or a custom item) or
    # of the "add an item" list opens - the third has no row of the character's yet, just the
    # catalog entry, with the Add/Buy buttons.
    path(
        "characters/<int:pk>/inventory/<int:ref>/",
        character_sheet.character_item,
        {"kind": "stack"},
        name="character-stack-item",
    ),
    path(
        "characters/<int:pk>/inventory/custom/<int:ref>/",
        character_sheet.character_item,
        {"kind": "custom"},
        name="character-custom-item",
    ),
    path(
        "characters/<int:pk>/catalog/<slug:ref>/",
        character_sheet.character_item,
        {"kind": "catalog"},
        name="character-catalog-item",
    ),
    path(
        "characters/<int:pk>/portrait/",
        character_sheet.character_portrait,
        name="character-portrait",
    ),
    path(
        "characters/<int:pk>/create/finish/",
        character_views.wizard_finish,
        name="character-finish",
    ),
    path(
        "characters/<int:pk>/create/discard/",
        character_views.wizard_discard,
        name="character-discard",
    ),
    path(
        "characters/<int:pk>/create/<slug:step>/",
        character_views.wizard,
        name="character-wizard",
    ),
    path("handbook/", views.handbook_overview, name="handbook-overview"),
    # Must come before `handbook/<slug:pk>/` below, or that catch-all would try to resolve
    # "rules-glossary" as a `HandbookSection` pk instead.
    path(
        "handbook/rules-glossary/",
        views.handbook_rules_glossary,
        name="handbook-rules-glossary",
    ),
    path(
        "handbook/<slug:pk>/",
        views.handbook_section_detail,
        name="handbook-section-detail",
    ),
    path("account/", views.account, name="account"),
    path("account/logout/", views.account_logout, name="account-logout"),
    path("bookmarks/toggle/", views.bookmark_toggle, name="bookmark-toggle"),
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
    path(
        "world/feats/feature/<int:pk>/",
        views.world_feature_detail,
        name="world-feature-detail",
    ),
    path(
        "world/feats/option/<slug:pk>/",
        views.world_option_detail,
        name="world-option-detail",
    ),
    path("world/feats/<slug:pk>/", views.world_feat_detail, name="world-feat-detail"),
    path("world/species/", views.world_species, name="world-species"),
    path("world/species/<slug:pk>/", views.world_species_detail, name="world-species-detail"),
    path("world/spells/", views.world_spells, name="world-spells"),
    path("world/spells/<slug:pk>/", views.world_spell_detail, name="world-spell-detail"),
    path("world/rules/<slug:pk>/", views.world_rule_detail, name="world-rule-detail"),
]
