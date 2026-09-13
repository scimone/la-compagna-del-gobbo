"""Ninja response schemas for the rules API - one `ModelSchema` per model, all fields.

Foreign keys serialize as their raw id (e.g. `ClassLevel.klass_id`), not a nested object - the
API is one flat resource per model, callers follow the id to fetch the parent themselves.
"""

from ninja import ModelSchema

from apps.rules.models import (
    Background,
    ChoiceDefinition,
    Class,
    ClassLevel,
    Effect,
    Equipment,
    EquipmentProperty,
    Feat,
    Feature,
    Language,
    Mastery,
    OptionalFeature,
    Proficiency,
    Rule,
    Sense,
    Skill,
    Species,
    Spell,
    Subclass,
    SubclassLevel,
)


class RuleSchema(ModelSchema):
    class Meta:
        model = Rule
        fields = "__all__"


class SkillSchema(ModelSchema):
    class Meta:
        model = Skill
        fields = "__all__"


class SenseSchema(ModelSchema):
    class Meta:
        model = Sense
        fields = "__all__"


class MasterySchema(ModelSchema):
    class Meta:
        model = Mastery
        fields = "__all__"


class EquipmentPropertySchema(ModelSchema):
    class Meta:
        model = EquipmentProperty
        fields = "__all__"


class EquipmentSchema(ModelSchema):
    class Meta:
        model = Equipment
        fields = "__all__"


class SpeciesSchema(ModelSchema):
    class Meta:
        model = Species
        fields = "__all__"


class BackgroundSchema(ModelSchema):
    class Meta:
        model = Background
        fields = "__all__"


class FeatSchema(ModelSchema):
    class Meta:
        model = Feat
        fields = "__all__"


class ClassSchema(ModelSchema):
    class Meta:
        model = Class
        fields = "__all__"


class ClassLevelSchema(ModelSchema):
    class Meta:
        model = ClassLevel
        fields = "__all__"


class SubclassSchema(ModelSchema):
    class Meta:
        model = Subclass
        fields = "__all__"


class SubclassLevelSchema(ModelSchema):
    class Meta:
        model = SubclassLevel
        fields = "__all__"


class SpellSchema(ModelSchema):
    class Meta:
        model = Spell
        fields = "__all__"


class LanguageSchema(ModelSchema):
    class Meta:
        model = Language
        fields = "__all__"


class OptionalFeatureSchema(ModelSchema):
    class Meta:
        model = OptionalFeature
        fields = "__all__"


class ProficiencySchema(ModelSchema):
    class Meta:
        model = Proficiency
        fields = "__all__"


class FeatureSchema(ModelSchema):
    class Meta:
        model = Feature
        fields = "__all__"


class EffectSchema(ModelSchema):
    class Meta:
        model = Effect
        fields = "__all__"


class ChoiceDefinitionSchema(ModelSchema):
    class Meta:
        model = ChoiceDefinition
        fields = "__all__"
