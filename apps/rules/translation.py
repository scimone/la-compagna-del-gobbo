"""Registers which `rules` model fields carry a per-language translation (django-modeltranslation).

Each registered field gets one extra column per language in `settings.LANGUAGES`
(`name_en`/`name_it`, ...) and the original attribute (`section.name`) then returns the value for
the currently active language, falling back to English when that translation is empty - so
services, API schemas and templates keep reading `section.name` unchanged.

Italian text is not edited in the database: `import_rules_data` loads it from `db/it/*.json`
(see `_import_handbook`), so a re-import never loses translations.
"""

from modeltranslation.translator import TranslationOptions, register

from apps.rules.models import (
    Ability,
    Background,
    Class,
    Equipment,
    EquipmentProperty,
    Feat,
    Feature,
    HandbookSection,
    Language,
    Mastery,
    OptionalFeature,
    Rule,
    Sense,
    Skill,
    Species,
    Spell,
    Subclass,
)


@register(HandbookSection)
class HandbookSectionTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


# The catalogs below are filled from `db/it/<file>.json` by `apps.rules.translation_sync` (the
# handbook has its own loader, `handbook_source`, because it also drops untranslated parts).
# Anything with no Italian text yet simply keeps showing English - nothing is ever removed.


@register(Feat)
class FeatTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


@register(Spell)
class SpellTranslationOptions(TranslationOptions):
    fields = ("name", "entries", "entries_higher_level")


@register(Species)
class SpeciesTranslationOptions(TranslationOptions):
    fields = ("name", "short_description", "lore", "entries")


@register(Background)
class BackgroundTranslationOptions(TranslationOptions):
    fields = ("name", "lore", "entries")


@register(Rule)
class RuleTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


@register(Skill)
class SkillTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


@register(Sense)
class SenseTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


@register(Language)
class LanguageTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


@register(Mastery)
class MasteryTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


@register(EquipmentProperty)
class EquipmentPropertyTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


@register(Equipment)
class EquipmentTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


@register(Ability)
class AbilityTranslationOptions(TranslationOptions):
    fields = ("name", "description")


@register(Class)
class ClassTranslationOptions(TranslationOptions):
    fields = ("name", "short_description", "subclass_title", "lore")


@register(Subclass)
class SubclassTranslationOptions(TranslationOptions):
    fields = ("name", "description")


@register(Feature)
class FeatureTranslationOptions(TranslationOptions):
    fields = ("name", "entries")


@register(OptionalFeature)
class OptionalFeatureTranslationOptions(TranslationOptions):
    fields = ("name", "entries")
