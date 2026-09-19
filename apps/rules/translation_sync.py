"""Loads the Italian text for every translated `rules` catalog other than the handbook.

Each model has a file `db/it/<file>.json`, `{row id: {field: italian value}}`, in the overlay
format documented in `handbook_source` - a translated field only needs the parts that have Italian
text (`null`/omitted = keep English), laid over the row's English value (its `<field>_en` column).
Rows the file doesn't mention, and fields it doesn't give, keep a NULL `<field>_it` and fall back
to English: nothing is ever removed for lacking a translation (unlike the handbook, which drops
its untranslated parts so both languages show the same content).
"""

import json

from apps.rules.handbook_source import DB_DIR, TranslationDataError, overlay_translation
from apps.rules.models import (
    Ability,
    Background,
    Class,
    Equipment,
    EquipmentProperty,
    Feat,
    Feature,
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

IT_DIR = DB_DIR / "it"

#: model -> (file under db/it/, translated fields)
TRANSLATED_CATALOGS = {
    Feat: ("feats.json", ("name", "entries")),
    Spell: ("spells.json", ("name", "entries", "entries_higher_level")),
    Species: ("species.json", ("name", "short_description", "lore", "entries")),
    Background: ("backgrounds.json", ("name", "lore", "entries")),
    Rule: ("rules.json", ("name", "entries")),
    Skill: ("skills.json", ("name", "entries")),
    Sense: ("senses.json", ("name", "entries")),
    Language: ("languages.json", ("name", "entries")),
    Mastery: ("masteries.json", ("name", "entries")),
    EquipmentProperty: ("equipment_properties.json", ("name", "entries")),
    Equipment: ("equipment.json", ("name", "entries")),
    Ability: ("abilities.json", ("name", "description")),
    Class: ("classes.json", ("name", "short_description", "subclass_title", "lore")),
    Subclass: ("subclasses.json", ("name", "description")),
    Feature: ("features.json", ("name", "entries")),
    OptionalFeature: ("optional_features.json", ("name", "entries")),
}


def sync_catalog(model, filename: str, fields: tuple[str, ...]) -> tuple[int, int]:
    """Set every `<field>_it` of `model`'s rows from `db/it/<filename>`; returns `(rows in the
    file, rows updated)`. Raises `TranslationDataError` for an unknown id or a misaligned tree.
    """
    path = IT_DIR / filename
    source = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    rows = list(model.objects.all())
    unknown = sorted(set(source) - {row.pk for row in rows})
    if unknown:
        raise TranslationDataError(
            f"db/it/{filename}: {len(unknown)} ids not in the database, e.g. {unknown[:5]}"
        )

    for row in rows:
        translated = source.get(row.pk, {})
        for field in fields:
            value = translated.get(field)
            if value is not None:
                english = getattr(row, f"{field}_en")
                value = overlay_translation(english, value, f"{filename}:{row.pk}.{field}")
            setattr(row, f"{field}_it", value)
    model.objects.bulk_update(rows, [f"{field}_it" for field in fields])
    return len(source), len(rows)


def sync_catalogs(write=lambda message: None) -> None:
    for model, (filename, fields) in TRANSLATED_CATALOGS.items():
        in_file, total = sync_catalog(model, filename, fields)
        write(f"{model.__name__}: {in_file} of {total} rows have Italian text")
