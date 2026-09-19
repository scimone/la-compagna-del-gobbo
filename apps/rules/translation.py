"""Registers which `rules` model fields carry a per-language translation (django-modeltranslation).

Each registered field gets one extra column per language in `settings.LANGUAGES`
(`name_en`/`name_it`, ...) and the original attribute (`section.name`) then returns the value for
the currently active language, falling back to English when that translation is empty - so
services, API schemas and templates keep reading `section.name` unchanged.

Italian text is not edited in the database: `import_rules_data` loads it from `db/it/*.json`
(see `_import_handbook`), so a re-import never loses translations.
"""

from modeltranslation.translator import TranslationOptions, register

from apps.rules.models import HandbookSection


@register(HandbookSection)
class HandbookSectionTranslationOptions(TranslationOptions):
    fields = ("name", "entries")
