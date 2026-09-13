from ninja import Router

router = Router(tags=["Rules"])

from . import (
    get_background,
    get_class,
    get_equipment,
    get_feat,
    get_feature,
    get_rule,
    get_species,
    get_spell,
    get_subclass,
    list_backgrounds,
    list_class_levels,
    list_class_subclasses,
    list_classes,
    list_equipment,
    list_equipment_properties,
    list_feats,
    list_features,
    list_languages,
    list_masteries,
    list_proficiencies,
    list_rules,
    list_senses,
    list_skills,
    list_species,
    list_spells,
    list_subclasses,
    list_tools,
)
