"""Loads the Italian text for every translated `rules` catalog other than the handbook.

Each model has a file `db/it/<file>.json`, `{row id: {field: italian value}}`, in the overlay
format documented in `handbook_source` - a translated field only needs the parts that have Italian
text (`null`/omitted = keep English), laid over the row's English value (its `<field>_en` column).
Rows the file doesn't mention, and fields it doesn't give, keep a NULL `<field>_it` and fall back
to English: nothing is ever removed for lacking a translation (unlike the handbook, which drops
its untranslated parts so both languages show the same content).

A row's entry may also carry `"_self": [...]`, alongside its translated fields - not itself a
field name, so `sync_catalog()`'s per-`field` loop below never touches it - listing exactly which
of that row's *own* translated fields were hand-translated for this project rather than lifted
from an official Italian source (the SRD PDF, for everything translated up to that point), e.g.
`["lore"]` on a species whose `name`/`entries` are official SRD text but whose `lore` (PHB-only,
never covered by the SRD) necessarily isn't. This sets the row's own `self_translated_fields`
column, which the frontend uses to show a "Traduzione" badge next to the *specific* heading/card
built from a hand-translated field, instead of a single flag that would blanket an entire page
even where only one part of it isn't official.
"""

import json

from django.utils.text import slugify

from apps.rules.handbook_source import DB_DIR, TranslationDataError, overlay_translation
from apps.rules.models import (
    Ability,
    Background,
    Class,
    Condition,
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
    Background: ("backgrounds.json", ("name", "short_description", "lore", "entries")),
    Rule: ("rules.json", ("name", "entries")),
    Skill: ("skills.json", ("name", "entries")),
    Sense: ("senses.json", ("name", "entries")),
    Condition: ("conditions.json", ("name", "entries")),
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


def key_map(model) -> dict:
    """`{row pk: key used in db/it/<model>.json}`. Most catalogs are keyed by their slug pk;
    `Subclass` and `Feature` have auto-incrementing numeric pks that change on every re-import,
    so they get a natural key built from their parent and name instead - e.g.
    `class:barbarian:1:rage`,
    `subclass:barbarian:path-of-the-berserker:3:frenzy` (`-2`, `-3`, ... if a name repeats within
    one parent).
    """
    if model is Subclass:
        return {s.pk: f"{s.klass_id}:{slugify(s.name_en)}" for s in Subclass.objects.all()}
    if model is not Feature:
        return {pk: pk for pk in model.objects.values_list("pk", flat=True)}

    keys, seen = {}, {}
    rows = Feature.objects.select_related(
        "class_level", "subclass_level__subclass", "species", "feat"
    ).order_by("pk")
    for f in rows:
        if f.class_level_id:
            parent = f"class:{f.class_level.klass_id}:{f.class_level.level}"
        elif f.subclass_level_id:
            sub = f.subclass_level.subclass
            parent = f"subclass:{sub.klass_id}:{slugify(sub.name_en)}:{f.subclass_level.level}"
        elif f.species_id:
            parent = f"species:{f.species_id}"
        elif f.feat_id:
            parent = f"feat:{f.feat_id}"
        else:
            parent = "feature"
        key = f"{parent}:{slugify(f.name_en)}"
        seen[key] = seen.get(key, 0) + 1
        keys[f.pk] = key if seen[key] == 1 else f"{key}-{seen[key]}"
    return keys


def sync_catalog(model, filename: str, fields: tuple[str, ...]) -> tuple[int, int]:
    """Set every `<field>_it` of `model`'s rows from `db/it/<filename>`; returns `(rows in the
    file, rows updated)`. Raises `TranslationDataError` for an unknown key or a misaligned tree.
    """
    path = IT_DIR / filename
    source = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    keys = key_map(model)
    rows = list(model.objects.all())
    unknown = sorted(set(source) - set(keys.values()))
    if unknown:
        raise TranslationDataError(
            f"db/it/{filename}: {len(unknown)} keys not in the database, e.g. {unknown[:5]}"
        )

    for row in rows:
        key = keys[row.pk]
        translated = source.get(key, {})
        for field in fields:
            value = translated.get(field)
            if value is not None:
                english = getattr(row, f"{field}_en")
                value = overlay_translation(english, value, f"{filename}:{key}.{field}")
            setattr(row, f"{field}_it", value)
        row.self_translated_fields = list(translated.get("_self") or [])
    model.objects.bulk_update(
        rows, [*(f"{field}_it" for field in fields), "self_translated_fields"]
    )
    return len(source), len(rows)


def sync_catalogs(write=lambda message: None) -> None:
    for model, (filename, fields) in TRANSLATED_CATALOGS.items():
        in_file, total = sync_catalog(model, filename, fields)
        write(f"{model.__name__}: {in_file} of {total} rows have Italian text")
