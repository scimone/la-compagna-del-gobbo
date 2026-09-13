"""Ninja schemas for the characters API.

Foreign keys serialize as their raw id (e.g. `CharacterClass.klass_id`), matching the `rules`
API's own convention - callers follow the id into the `rules` API themselves.
"""

from ninja import ModelSchema, Schema

from apps.characters.models import (
    Character,
    CharacterAbilityScoreIncrease,
    CharacterChoice,
    CharacterClass,
    CharacterCurrency,
    CharacterFeat,
    CharacterFeature,
    CharacterInventoryItem,
    CharacterLanguage,
    CharacterOptionalFeature,
    CharacterProficiency,
    CharacterResource,
    CharacterSense,
    CharacterSpell,
)

CHARACTER_WRITABLE_FIELDS = [
    "name",
    "species",
    "background",
    "alignment",
    "size",
    "appearance",
    "notes",
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
    "max_hit_points",
    "current_hit_points",
    "temporary_hit_points",
    "inspiration",
]


class CharacterOutSchema(ModelSchema):
    class Meta:
        model = Character
        fields = "__all__"


class CharacterCreateSchema(ModelSchema):
    class Meta:
        model = Character
        fields = CHARACTER_WRITABLE_FIELDS


class CharacterUpdateSchema(ModelSchema):
    class Meta:
        model = Character
        fields = CHARACTER_WRITABLE_FIELDS
        fields_optional = "__all__"


class CharacterClassSchema(ModelSchema):
    class Meta:
        model = CharacterClass
        fields = "__all__"


class CharacterAbilityScoreIncreaseSchema(ModelSchema):
    class Meta:
        model = CharacterAbilityScoreIncrease
        fields = "__all__"


class CharacterChoiceSchema(ModelSchema):
    class Meta:
        model = CharacterChoice
        fields = "__all__"


class CharacterFeatureSchema(ModelSchema):
    class Meta:
        model = CharacterFeature
        fields = "__all__"


class CharacterFeatSchema(ModelSchema):
    class Meta:
        model = CharacterFeat
        fields = "__all__"


class CharacterOptionalFeatureSchema(ModelSchema):
    class Meta:
        model = CharacterOptionalFeature
        fields = "__all__"


class CharacterLanguageSchema(ModelSchema):
    class Meta:
        model = CharacterLanguage
        fields = "__all__"


class CharacterProficiencySchema(ModelSchema):
    class Meta:
        model = CharacterProficiency
        fields = "__all__"


class CharacterSenseSchema(ModelSchema):
    class Meta:
        model = CharacterSense
        fields = "__all__"


class CharacterInventoryItemSchema(ModelSchema):
    class Meta:
        model = CharacterInventoryItem
        fields = "__all__"


class CharacterInventoryItemCreateSchema(ModelSchema):
    class Meta:
        model = CharacterInventoryItem
        fields = ["equipment", "quantity", "equipped", "attuned", "notes"]


class CharacterInventoryItemUpdateSchema(ModelSchema):
    class Meta:
        model = CharacterInventoryItem
        fields = ["quantity", "equipped", "attuned", "notes"]
        fields_optional = "__all__"


class CharacterCurrencySchema(ModelSchema):
    class Meta:
        model = CharacterCurrency
        fields = "__all__"


class CharacterCurrencyUpdateSchema(ModelSchema):
    class Meta:
        model = CharacterCurrency
        fields = ["copper", "silver", "electrum", "gold", "platinum"]
        fields_optional = "__all__"


class CharacterSpellSchema(ModelSchema):
    class Meta:
        model = CharacterSpell
        fields = "__all__"


class CharacterSpellCreateSchema(ModelSchema):
    class Meta:
        model = CharacterSpell
        fields = ["spell", "prepared", "always_prepared", "source"]


class CharacterResourceSchema(ModelSchema):
    class Meta:
        model = CharacterResource
        fields = "__all__"


class CharacterSheetSchema(Schema):
    """The fully resolved character sheet - every collection a character owns, aggregated into
    one response so a frontend doesn't have to make a dozen requests.

    Deliberately does NOT include derived combat stats (AC, initiative, spell save DC, passive
    Perception, ...) - those depend on rules resolution that doesn't exist yet (see
    `builder.services.derived_stats` in the README). This is everything that's already
    *persisted*, aggregated; not everything a finished character sheet will eventually show.
    """

    character: CharacterOutSchema
    classes: list[CharacterClassSchema]
    ability_score_increases: list[CharacterAbilityScoreIncreaseSchema]
    features: list[CharacterFeatureSchema]
    feats: list[CharacterFeatSchema]
    optional_features: list[CharacterOptionalFeatureSchema]
    languages: list[CharacterLanguageSchema]
    proficiencies: list[CharacterProficiencySchema]
    senses: list[CharacterSenseSchema]
    inventory_items: list[CharacterInventoryItemSchema]
    currency: CharacterCurrencySchema | None
    spells: list[CharacterSpellSchema]
    resources: list[CharacterResourceSchema]
