from ninja import Router

router = Router(tags=["Character Details"])

from . import (
    list_character_choices,
    list_character_classes,
    list_character_feats,
    list_character_features,
    list_character_languages,
    list_character_optional_features,
    list_character_proficiencies,
    list_character_resources,
    list_character_senses,
)
