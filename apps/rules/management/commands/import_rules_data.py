import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import translation
from django.utils.text import slugify

from apps.rules.handbook_source import TranslationDataError, load_handbook
from apps.rules.lineage_features import land_features, lineage_feature, link_lands
from apps.rules.models import (
    Ability,
    Background,
    BackgroundStartingEquipmentOption,
    ChoiceDefinition,
    Class,
    ClassLevel,
    ClassStartingEquipmentOption,
    Condition,
    Effect,
    Equipment,
    EquipmentGroup,
    EquipmentPackContent,
    EquipmentProperty,
    EquipmentType,
    Feat,
    Feature,
    HandbookChapter,
    HandbookSection,
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
from apps.rules.models.effect import TAG_PATTERN
from apps.rules.translation_sync import sync_catalogs

DB_DIR = Path(settings.BASE_DIR) / "db"
#: `Spell.classes`/`subclasses` are read from `db/spell_classes.json` (`{spell name: {classes,
#: subclasses}}`), since the 2025 `db/` dump has no spell-list data (see
#: `docs/data_migration_2025.md` §2/§3.4).

#: Single-letter/short-code decode tables - the new source uses these throughout instead of the
#: old dump's spelled-out words. Only the codes actually observed in `db/` are listed; anything
#: unrecognized falls back to the raw code rather than silently guessing.
RULE_TYPE_CODES = {"C": "Core"}
SCHOOL_CODES = {
    "A": "Abjuration",
    "C": "Conjuration",
    "D": "Divination",
    "E": "Enchantment",
    "V": "Evocation",
    "I": "Illusion",
    "N": "Necromancy",
    "T": "Transmutation",
}
DAMAGE_TYPE_CODES = {
    "A": "acid",
    "B": "bludgeoning",
    "C": "cold",
    "F": "fire",
    "O": "force",
    "L": "lightning",
    "N": "necrotic",
    "I": "poison",
    "P": "piercing",
    "Y": "psychic",
    "R": "radiant",
    "S": "slashing",
    "T": "thunder",
}
FEAT_CATEGORY_CODES = {"O": "Origin", "G": "General", "FS": "Fighting Style", "EB": "Epic Boon"}
#: The source's proficiency/sense/resistance grant keys on a feat, kept verbatim in `Feat.grants`.
FEAT_GRANT_KEYS = (
    "skillProficiencies",
    "toolProficiencies",
    "weaponProficiencies",
    "armorProficiencies",
    "savingThrowProficiencies",
    "skillToolLanguageProficiencies",
    "expertise",
    "senses",
    "resist",
)
OPTIONAL_FEATURE_TYPE_CODES = {"EI": "Eldritch Invocation", "MM": "Metamagic", "MV": "Maneuver"}

#: `Equipment.stats` catch-all - mechanical fields real enough to keep but too sparse/per-category
#: to earn their own column (see `Equipment`'s docstring).
EQUIPMENT_STAT_KEYS = [
    "containerCapacity",
    "crew",
    "vehAc",
    "vehHp",
    "vehSpeed",
    "capPassenger",
    "capCargo",
    "carryingCapacity",
    "travelCost",
    "ammoType",
    "reload",
]

# Short one-line blurbs for the World menu buttons (`Class.short_description`/
# `Species.short_description`) - there's no such field in the source JSON, so these are
# hand-written here rather than loaded from db/*.json like everything else in this file.
CLASS_SHORT_DESCRIPTIONS = {
    "barbarian": "A fierce warrior fueled by primal rage.",
    "bard": "A performer whose art channels magic.",
    "cleric": "A priestly champion wielding divine magic.",
    "druid": "A shapeshifter who commands the wild.",
    "fighter": "A master of weapons and combat tactics.",
    "monk": "A disciplined master of martial arts.",
    "paladin": "A holy warrior bound by a sacred oath.",
    "ranger": "A tracker skilled in nature and combat.",
    "rogue": "A master of stealth and cunning strikes.",
    "sorcerer": "A spellcaster with innate, inherited magic.",
    "warlock": "Bound by pact to an otherworldly patron.",
    "wizard": "A scholar who masters magic through study.",
}

#: `Grung` (source VGM) is absent from `db/species.json` as shipped (see
#: `docs/data_migration_2025.md` §3.5 - dropped there because it isn't XPHB content) - added
#: back by hand afterward, at the project owner's request, from the old dump's species row
#: converted into the new format (see that entry's own `"source": "VGM"`, kept as-is rather than
#: relabeled XPHB, and its `page` is `0` since the old data never carried a real one either).
SPECIES_SHORT_DESCRIPTIONS = {
    "aasimar": "Mortals touched by celestial power.",
    "dragonborn": "Proud, draconic folk with elemental breath.",
    "dwarf": "Sturdy folk of mountain and stone.",
    "elf": "Graceful, long-lived, attuned to magic.",
    "gnome": "Small, inventive folk full of curiosity.",
    "goliath": "Towering folk from harsh mountain peaks.",
    "grung": "Cheerful frog-folk at home in water and jungle.",
    "halfling": "Small, nimble folk known for luck and cheer.",
    "human": "Adaptable, ambitious, and endlessly diverse.",
    "orc": "Strong, resilient folk of fierce endurance.",
    "tiefling": "Mortals marked by an infernal bloodline.",
}

BACKGROUND_SHORT_DESCRIPTIONS = {
    "acolyte": "A devoted servant of a temple and its faith.",
    "artisan": "A skilled crafter who trades in fine goods.",
    "charlatan": "A smooth-talking con artist and swindler.",
    "criminal": "A survivor of the streets and the underworld.",
    "entertainer": "A performer who thrives on a crowd's attention.",
    "farmer": "A hardy tender of the land and its harvest.",
    "guard": "A vigilant watcher of gates, walls, and law.",
    "guide": "A seasoned pathfinder of wilderness and ruin.",
    "hermit": "A solitary seeker of quiet and hidden truths.",
    "merchant": "A shrewd trader who lives by the deal.",
    "noble": "A well-born heir to wealth and influence.",
    "sage": "A tireless scholar in pursuit of knowledge.",
    "sailor": "A weathered wanderer of the open seas.",
    "scribe": "A meticulous keeper of words and records.",
    "soldier": "A disciplined veteran forged by war.",
    "wayfarer": "A resourceful drifter who lives by their wits.",
}


def _load(filename: str) -> dict:
    with open(DB_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def _load_if_exists(filename: str) -> dict | None:
    """Like `_load`, but returns `None` instead of raising when the file doesn't exist - used
    only for the fluff files `_import_lore` reads, which weren't shipped with the initial 2025
    `db/` drop and were added later (see `docs/data_migration_2025.md` §3.7); keeping this lookup
    optional means a future `db/` refresh that drops one of these files again degrades gracefully
    (that class/species/background's `lore` just stays empty) instead of crashing the whole import.
    """
    if not (DB_DIR / filename).exists():
        return None
    return _load(filename)


def _slug(name: str) -> str:
    slug = slugify(name)
    if not slug:
        raise CommandError(f"Cannot derive a slug from name={name!r}")
    return slug


def _decode_code(code: str, mapping: dict[str, str]) -> str:
    """Decode a short code, tolerating a `PREFIX:SUFFIX` shape (e.g. Feat category "FS:R", or
    OptionalFeature type "MV:B" for a Battle Master Maneuver) by decoding the prefix and keeping
    the suffix as extra context rather than trying to look it up too.
    """
    if ":" in code:
        prefix, suffix = code.split(":", 1)
        base = mapping.get(prefix, prefix)
        if prefix == "MV" and suffix == "B":
            return f"{base}, Battle Master"
        return f"{base} ({suffix})"
    return mapping.get(code, code)


def _parse_ref(ref: str) -> tuple[str, str | None]:
    """A `"name|source"` (or bare `"name"`) reference key - the pervasive cross-reference
    convention the new source uses everywhere (spells, equipment, feats, ...). Returns
    (name.lower(), source.lower() or None).
    """
    if "|" in ref:
        name, source = ref.split("|", 1)
        return name.strip().lower(), source.strip().lower()
    return ref.strip().lower(), None


def _feat_ref_base_name(ref_key: str) -> str:
    """A background's `feats` grant key, e.g. `"magic initiate; wizard|xphb"` - references a
    specific *variant* of a feat expanded via 5etools' templating (not imported as separate rows
    here, see `Species`'s docstring on `_versions`/`_mod` fields) - strip the `"; variant"` suffix
    to match against the single unexpanded `Feat` row this project does import.
    """
    return ref_key.split("|")[0].split(";")[0].strip().lower()


def _feat_ref_variant(ref_key: str) -> str:
    """The `"; variant"` part `_feat_ref_base_name` strips, slugified: `"magic initiate; cleric|
    xphb"` -> `"cleric"`; `""` when the reference names no variant.
    """
    head = ref_key.split("|")[0]
    return _slug(head.split(";", 1)[1]) if ";" in head else ""


def _class_weapon_proficiencies(starting_prof: dict) -> list:
    """A class's weapon proficiency grant, in the same `[{"simple": True, ...}]` shape armor uses.

    The source only fills `weaponProficiencies` (structured) for Monk and Rogue, whose grant has a
    filter ("Martial weapons with the Light property"). Every other class has just the display
    list `weapons: ["simple", "martial"]`, which the importer used to ignore - leaving ten of the
    twelve classes with no weapon proficiency at all.
    """
    structured = starting_prof.get("weaponProficiencies")
    if structured:
        return structured
    flags = {w: True for w in starting_prof.get("weapons", []) if w in ("simple", "martial")}
    return [flags] if flags else []


_LINEAGE_LABEL_RE = re.compile(r"\((.+)\)\s*$")


def _lineage_from_version(version: dict) -> dict | None:
    """One entry of a species' `_versions` (the 5etools "pick one of these variants" mechanism)
    as a lineage - see `Species`'s docstring for the normalised shape. The lineage's name is not
    a field of its own in the source: it is the parenthesised part of the trait the version
    swaps in ("Elven Lineage (Drow)" -> "Drow").
    """
    mods = (version.get("_mod") or {}).get("entries") or []
    for mod in mods if isinstance(mods, list) else [mods]:
        items = mod.get("items") if isinstance(mod, dict) else None
        match = _LINEAGE_LABEL_RE.search((items or {}).get("name", ""))
        if mod.get("mode") == "replaceArr" and match:
            label = match.group(1)
            lineage = {
                "key": _slug(label),
                "label": label,
                "replaces": mod["replace"],
                "resistances": [r for r in version.get("resist", []) if isinstance(r, str)],
                "additional_spells": version.get("additionalSpells", []),
            }
            for field in ("darkvision", "speed"):
                if field in version:
                    lineage[field] = version[field]
            return lineage
    return None


def _species_lineages(raw: dict) -> list[dict]:
    lineages = []
    for version in raw.get("_versions", []):
        if "_abstract" in version:
            # Dragonborn: one abstract template expanded once per colour (`_implementations`).
            for impl in version["_implementations"]:
                colour = impl["_variables"]["color"]
                lineages.append(
                    {
                        "key": _slug(colour),
                        "label": colour,
                        "replaces": "Draconic Ancestry",
                        "damage_type": impl["_variables"]["damageType"].lower(),
                        "resistances": impl.get("resist", []),
                        "additional_spells": [],
                    }
                )
        elif (lineage := _lineage_from_version(version)) is not None:
            lineages.append(lineage)
    return lineages


def _named_dicts(entries: list) -> list[dict]:
    """Top-level list items that are dicts with an explicit "name" key - see Feature's docstring
    for why only these (never bare prose strings, never nested sub-blocks) become Feature rows.
    """
    return [x for x in entries if isinstance(x, dict) and "name" in x]


def _walk_tags(node):
    """Yield (tag, raw) for every literal {@tag ...} occurrence anywhere in a JSON tree."""
    if isinstance(node, str):
        for m in TAG_PATTERN.finditer(node):
            yield m.group(1), m.group(0)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_tags(item)
    elif isinstance(node, dict):
        for value in node.values():
            yield from _walk_tags(value)


def _flag_items(raw_list: list[dict] | None):
    """A flat proficiency-grant list, e.g. `[{"light": true, "medium": true}]` or (Monk's weapon
    grant) `[{"simple": true, "all": {"fromFilter": "..."}}]`. Yields (name, extra) - `extra` is
    `None` for a plain `true` flag, or the nested filter/detail dict for a non-boolean value.
    """
    for entry in raw_list or []:
        for key, value in entry.items():
            if value is True:
                yield key, None
            elif isinstance(value, dict):
                yield key, value


def _iter_choice_rows(kind: str, grant_list: list | None, **parent_kwargs):
    """A choice-shaped grant list (`{"choose": {"from": [...], "count"|"amount": N}}` or a bare
    `{"any": N}`) - see `ChoiceDefinition`'s docstring. Flat (non-choice) grants yield nothing.
    """
    for entry in grant_list or []:
        if not isinstance(entry, dict):
            continue
        choose = entry.get("choose")
        if isinstance(choose, dict) and "from" in choose:
            options = choose["from"]
            if kind == "skills":
                # Source names ("sleight of hand") -> `Skill` ids ("sleight-of-hand"), so an
                # option can be used as a key without the consumer having to know that.
                options = [_slug(o) if isinstance(o, str) else o for o in options]
            yield ChoiceDefinition(
                kind=kind,
                options=options,
                count=choose.get("count", choose.get("amount")),
                **parent_kwargs,
            )
        elif "any" in entry:
            yield ChoiceDefinition(kind=kind, options=[], count=entry["any"], **parent_kwargs)


def _iter_feat_category_choice_rows(grant_list: list | None, **parent_kwargs):
    """Species' `feats` grant, e.g. Human's `{"anyFromCategory": {"category": ["O"], "count":
    1}}` - a different choice idiom than `_iter_choice_rows` (no "from" list, a Feat *category*
    instead), so it gets its own small extractor.
    """
    for entry in grant_list or []:
        if not isinstance(entry, dict):
            continue
        category = entry.get("anyFromCategory")
        if isinstance(category, dict):
            yield ChoiceDefinition(
                kind="feats",
                options=[
                    _decode_code(c, FEAT_CATEGORY_CODES) for c in category.get("category", [])
                ],
                count=category.get("count"),
                **parent_kwargs,
            )


def _pack_content_entries(pack_contents: list | None):
    """An `item.packContents` entry is a bare `"name|source"` string (implicit quantity 1) or a
    `{"item": "name|source", "quantity": N}` dict."""
    for entry in pack_contents or []:
        if isinstance(entry, str):
            yield entry, 1
        elif isinstance(entry, dict) and "item" in entry:
            yield entry["item"], entry.get("quantity", 1)


def _starting_equipment_rows(raw_list: list | None, equipment_by_name: dict, group_by_name: dict):
    """A `startingEquipment` value: a list holding one `{"A": [...], "B": [...], ...}` dict (both
    `Background.startingEquipment` and `Class.startingEquipment.defaultData` share this shape).
    Yields (option, item_or_None, group_or_None, quantity, gold_value_or_None).

    An `"item"` ref usually names a concrete `Equipment` row, but two references in the whole
    source (Acolyte's/Druid's "Holy Symbol"/"Druidic Focus") actually name an `EquipmentGroup`
    instead - "pick any Holy Symbol", not a specific item - verified this is the *only* shape
    that fails to resolve against `Equipment`, across every Background/Class starting-equipment
    reference in `db/`, so falling back to `EquipmentGroup` covers it completely rather than
    leaving a silently broken all-`None` row. Category-placeholder picks (`{"equipmentType":
    "setGaming"}` - "any gaming set", no specific row *or* group to resolve to) are skipped, same
    scope limit as the ad hoc tool-proficiency shapes elsewhere.
    """
    for entry in raw_list or []:
        if not isinstance(entry, dict):
            continue
        for option, picks in entry.items():
            if not isinstance(picks, list):
                continue
            for pick in picks:
                if not isinstance(pick, dict):
                    continue
                if "item" in pick:
                    name, _source = _parse_ref(pick["item"])
                    item = equipment_by_name.get(name)
                    group = None if item else group_by_name.get(name)
                    yield option, item, group, pick.get("quantity", 1), None
                elif "value" in pick:
                    yield option, None, None, 1, pick["value"]


def _walk_feature_pointers(node, pointer_type: str, key_field: str):
    """Yield every `node[key_field]` value found on a `{"type": pointer_type, ...}` dict, anywhere
    in a JSON tree. A class/subclass's `classFeatures`/`subclassFeatures` list does *not* always
    enumerate every feature - a choice between features (e.g. Cleric's level-1 Divine Order
    choosing "Protector" or "Thaumaturge") or a subclass's granting-level wrapper (e.g. "Life
    Domain" bundling "Disciple of Life"/"Life Domain Spells"/"Preserve Life") instead points at
    its siblings via `{"type": "refClassFeature", "classFeature": "..."}` / `{"type":
    "refSubclassFeature", "subclassFeature": "..."}` nodes buried in its own `entries` - verified
    on Cleric (both cases) before relying on this as the general resolution strategy, not a
    one-off special case for either pointer type.
    """
    if isinstance(node, dict):
        if node.get("type") == pointer_type and key_field in node:
            yield node[key_field]
        for value in node.values():
            yield from _walk_feature_pointers(value, pointer_type, key_field)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_feature_pointers(item, pointer_type, key_field)


def _option_pointer_refs(node, inside: bool = False):
    """Every `refClassFeature` ref found inside an `options` node ("choose one of these") - the
    alternatives of a choice, as opposed to sub-features that all apply."""
    if isinstance(node, dict):
        inside = inside or node.get("type") == "options"
        if inside and node.get("type") == "refClassFeature" and "classFeature" in node:
            yield node["classFeature"]
        for value in node.values():
            yield from _option_pointer_refs(value, inside)
    elif isinstance(node, list):
        for item in node:
            yield from _option_pointer_refs(item, inside)


def _parse_class_feature_ref(ref: str) -> tuple[str, str, str, int]:
    """A `classFeature` reference key. Two shapes occur - a bare 4-part grant in `class.
    classFeatures[]` (`"Second Wind|Fighter|XPHB|1"`) and a 5-part `refClassFeature` pointer
    inside another feature's `entries` (`"Protector|Cleric|XPHB|1|XPHB"`, trailing feature-source
    always redundant with `classSource`) - both are handled by only ever reading the first four
    parts (name, className, classSource, level), never requiring or matching a 5th segment.
    """
    parts = ref.split("|")
    name, class_name, class_source, level = parts[0], parts[1], parts[2], parts[3]
    return (
        name.strip().lower(),
        class_name.strip().lower(),
        class_source.strip().lower(),
        int(level),
    )


def _inline_header_class_features(node, class_feature_lookup: dict):
    """Replace a `{"type": "refClassFeature", "classFeature": ref}` pointer to a *sub-heading*
    `classFeature` (one with a `header` field - 5etools' own nesting-depth marker) with that
    feature's own name/entries inlined as a named nested block, recursively.

    Verified against every `classFeature` row with `header` set (12 total, across Cleric/Druid/
    Monk - e.g. Monk's Martial Arts embeds Bonus Unarmed Strike/Martial Arts Die/Dexterous
    Attacks this way, Cleric's Channel Divinity embeds Divine Spark/Turn Undead): every one is
    reachable *only* via a `refClassFeature` pointer like this, never listed directly in a
    class's own top-level `classFeatures[]` - this is how the printed book itself presents them,
    as sub-entries of one feature, not standalone ones, and matches
    `_import_classes()`'s own BFS skipping a `Feature` row for any of them (see there) - this is
    the other half of that: without it, the pointer itself doesn't render (`entries_render.py`
    has no case for a bare `refClassFeature` node) and the text would silently vanish from the
    page instead of just being duplicated onto it.

    A pointer to a `classFeature` with no `header` (a genuine standalone feature, e.g. Cleric's
    Protector/Thaumaturge choice) is inlined too - it keeps its own `Feature` row, created
    separately by the caller, so its text appears twice; leaving the pointer instead would
    render nothing (the renderer has no case for a bare `refClassFeature`), cutting the parent
    feature off right after "Choose one:".
    """
    if isinstance(node, dict):
        if node.get("type") == "refClassFeature" and "classFeature" in node:
            raw = class_feature_lookup.get(_parse_class_feature_ref(node["classFeature"]))
            if raw is not None:
                return {
                    "type": "entries",
                    "name": raw["name"],
                    "entries": _inline_header_class_features(
                        raw.get("entries", []), class_feature_lookup
                    ),
                }
            return node
        return {k: _inline_header_class_features(v, class_feature_lookup) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_header_class_features(item, class_feature_lookup) for item in node]
    return node


def _parse_subclass_feature_ref(ref: str) -> tuple[str, str, str, str, int]:
    """A `subclassFeature` reference key (`"Life Domain Spells|Cleric|XPHB|Life|XPHB|3"`) - name,
    className, classSource, subclassShortName, subclassSource, level. `classSource` is dropped
    (redundant with `className` within one class's own subclasses), matching how
    `subclass_feature_lookup` is keyed.
    """
    parts = ref.split("|")
    name, class_name, subclass_short, subclass_source, level = (
        parts[0],
        parts[1],
        parts[3],
        parts[4],
        parts[5],
    )
    return (
        name.strip().lower(),
        class_name.strip().lower(),
        subclass_short.strip().lower(),
        subclass_source.strip().lower(),
        int(level),
    )


def _inline_subclass_features(node, subclass_feature_lookup: dict):
    """Subclass counterpart of `_inline_header_class_features()`: a `refSubclassFeature` pointer to
    a sub-heading feature (College of Dance's Dazzling Footwork -> Dance Virtuoso, Unarmored
    Defense...) becomes that feature's own name/entries as a nested block, so the parent reads as
    the book prints it instead of ending after "you gain the following benefits"."""
    if isinstance(node, dict):
        if node.get("type") == "refSubclassFeature" and "subclassFeature" in node:
            raw = subclass_feature_lookup.get(_parse_subclass_feature_ref(node["subclassFeature"]))
            if raw is not None:
                return {
                    "type": "entries",
                    "name": raw["name"],
                    "entries": _inline_subclass_features(
                        raw.get("entries", []), subclass_feature_lookup
                    ),
                }
            return node
        return {k: _inline_subclass_features(v, subclass_feature_lookup) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_subclass_features(item, subclass_feature_lookup) for item in node]
    return node


#: A `classTableGroups` colLabel is sometimes a literal 5etools `{@filter Display Text|...}` tag
#: (e.g. `"{@filter Invocations|optionalfeatures|feature type=ei}"`), not a display string - the
#: importer isn't a renderer (that's `apps/frontend/entries_render.py`'s job) and doesn't resolve
#: these into real links, but leaving the raw tag syntax as a column header is unreadable, so it's
#: at least unwrapped down to its display text.
_FILTER_TAG_RE = re.compile(r"\{@filter ([^|}]+)\|[^}]*\}")

#: A column whose (unwrapped) label is one of these duplicates `cantrips_known`/
#: `spells_known_or_prepared` - verified across all 12 classes' `classTableGroups`: some classes
#: (Cleric, Wizard, ...) group these two columns together with a real resource column (Channel
#: Divinity, Wild Shape) in the very same `classTableGroups` entry, so the redundant *group*
#: can't be dropped wholesale (Warlock's is the clearest case - one group mixes a genuine
#: "Invocations" column with the redundant Cantrips/Prepared Spells ones and its own real "Spell
#: Slots"/"Slot Level" pact-magic columns, which have no other source) - only the matching
#: *column* is skipped.
_REDUNDANT_SPELL_COUNT_LABELS = {"cantrips", "prepared spells"}


def _clean_column_label(label: str) -> str:
    match = _FILTER_TAG_RE.fullmatch(label.strip())
    return match.group(1) if match else label


def _class_levels_by_number(class_data: dict) -> dict[int, dict]:
    """Per-level `spell_slots`/`cantrips_known`/`spells_known_or_prepared`/`columns` kwargs for
    levels 1-20, from the class's structured progression fields - see `ClassLevel`'s docstring.
    """
    cantrip_progression = class_data.get("cantripProgression")
    known_progression = (
        class_data.get("preparedSpellsProgression")
        or class_data.get("spellsKnownProgressionFixed")
        or class_data.get("spellsKnownProgressionFixedByLevel")
    )
    spell_slot_rows = None
    other_groups = []
    for group in class_data.get("classTableGroups") or []:
        if group.get("rowsSpellProgression"):
            spell_slot_rows = group["rowsSpellProgression"]
        elif group.get("rows"):
            other_groups.append(group)

    result = {}
    for level in range(1, 21):
        idx = level - 1
        columns = {}
        for group in other_groups:
            if idx < len(group["rows"]):
                for label, value in zip(group["colLabels"], group["rows"][idx], strict=False):
                    clean_label = _clean_column_label(label)
                    if clean_label.strip().lower() in _REDUNDANT_SPELL_COUNT_LABELS:
                        continue
                    columns[clean_label] = value
        result[level] = {
            "spell_slots": (
                spell_slot_rows[idx] if spell_slot_rows and idx < len(spell_slot_rows) else []
            ),
            "cantrips_known": (
                cantrip_progression[idx]
                if cantrip_progression and idx < len(cantrip_progression)
                else None
            ),
            "spells_known_or_prepared": (
                known_progression[idx]
                if known_progression and idx < len(known_progression)
                else None
            ),
            "columns": columns,
        }
    return result


class Command(BaseCommand):
    help = (
        "Wipe and reload every rules model from the XPHB data dumped in db/ "
        "(plus the Italian translations in db/it/, where they exist)."
    )

    @transaction.atomic
    @translation.override(settings.MODELTRANSLATION_DEFAULT_LANGUAGE)
    def handle(self, *args, **options):
        # name=/entries= on a translated model mean "the active language's column" - pin that to
        # English so the source text always lands in the `*_en` columns.
        self._delete_existing()

        self._import_rules()
        self._import_ability()
        self._import_skills()
        self._import_senses()
        self._import_conditions()
        self._import_masteries()
        self._import_languages()
        self._import_equipment_types()
        self._import_equipment_properties()
        self._import_species()
        self._import_feats()
        self._import_optional_features()
        self._import_classes()
        self._import_equipment_groups()
        self._import_equipment()
        self._import_spells()
        self._import_backgrounds()
        self._import_background_starting_equipment()
        self._import_class_starting_equipment()
        self._import_proficiencies()
        features_by_source = self._import_features()
        self._import_effects(features_by_source)
        self._import_choice_definitions()
        self._import_handbook()
        self._import_lore()
        try:
            sync_catalogs(lambda message: self.stdout.write(f"  {message}"))
        except TranslationDataError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Rules data imported."))

    def _check_unique(self, model, rows) -> None:
        ids = [r.id for r in rows]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise CommandError(f"{model.__name__}: duplicate ids after slugify: {dupes}")

    def _delete_existing(self):
        # Feature is deleted explicitly, not left to cascade from the catalogs below - see the
        # README's "Known data-import issues" (Issue 4) for why a future FK restructuring could
        # otherwise orphan rows a cascade-only approach would miss.
        Feature.objects.all().delete()

        # Equipment first, explicitly: EquipmentType is a PROTECT FK target now (unlike every
        # other catalog here, which cascades or SET_NULLs), so it must be empty before the loop
        # below deletes EquipmentType itself.
        Equipment.objects.all().delete()

        for model in [
            Ability,
            Class,
            Species,
            Background,
            Feat,
            Rule,
            Skill,
            Sense,
            Condition,
            Mastery,
            EquipmentProperty,
            EquipmentType,
            EquipmentGroup,
            Language,
            OptionalFeature,
            Spell,
            HandbookSection,
            HandbookChapter,
        ]:
            model.objects.all().delete()

    def _import_rules(self):
        rows = [
            Rule(
                id=_slug(it["name"]),
                name=it["name"],
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                rule_type=RULE_TYPE_CODES.get(it.get("ruleType", ""), it.get("ruleType", "")),
                entries=it.get("entries", []),
            )
            for it in _load("rules.json")["variantrule"]
        ]
        self._check_unique(Rule, rows)
        Rule.objects.bulk_create(rows)
        self.stdout.write(f"  Rule: {Rule.objects.count()}")

    def _import_ability(self):
        Ability.objects.bulk_create(
            Ability(id=it["short"], name=it["name"], description=(it.get("entries") or [""])[0])
            for it in _load("abilities.json")["ability"]
        )
        self.stdout.write(f"  Ability: {Ability.objects.count()}")

    def _import_skills(self):
        rows = [
            Skill(
                id=_slug(it["name"]),
                name=it["name"],
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                ability_id=it["ability"].lower(),
                entries=it.get("entries", []),
            )
            for it in _load("skills.json")["skill"]
        ]
        self._check_unique(Skill, rows)
        Skill.objects.bulk_create(rows)
        self.stdout.write(f"  Skill: {Skill.objects.count()}")

    def _import_senses(self):
        rows = [
            Sense(
                id=_slug(it["name"]),
                name=it["name"],
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                entries=it.get("entries", []),
            )
            for it in _load("senses.json")["sense"]
        ]
        self._check_unique(Sense, rows)
        Sense.objects.bulk_create(rows)
        self.stdout.write(f"  Sense: {Sense.objects.count()}")

    def _import_conditions(self):
        data = _load("conditions.json")
        rows = [
            Condition(
                id=_slug(it["name"]),
                name=it["name"],
                kind=kind,
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                entries=it.get("entries", []),
            )
            for kind in (Condition.KIND_CONDITION, Condition.KIND_STATUS)
            for it in data[kind]
        ]
        self._check_unique(Condition, rows)
        Condition.objects.bulk_create(rows)
        self.stdout.write(f"  Condition: {Condition.objects.count()}")

    def _import_masteries(self):
        rows = [
            Mastery(
                id=_slug(it["name"]),
                name=it["name"],
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                entries=it.get("entries", []),
            )
            for it in _load("masteries.json")["itemMastery"]
        ]
        self._check_unique(Mastery, rows)
        Mastery.objects.bulk_create(rows)
        self.stdout.write(f"  Mastery: {Mastery.objects.count()}")

    def _import_languages(self):
        rows = [
            Language(
                id=_slug(it["name"]),
                name=it["name"],
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                language_type=it.get("type", ""),
                script=it.get("script", ""),
                typical_speakers=it.get("origin", ""),
                entries=it.get("entries", []),
            )
            for it in _load("languages.json")["language"]
        ]
        self._check_unique(Language, rows)
        Language.objects.bulk_create(rows)
        self.stdout.write(f"  Language: {Language.objects.count()}")

    def _import_equipment_types(self):
        rows = [
            EquipmentType(
                id=_slug(it["abbreviation"]),
                name=it["name"],
                abbreviation=it["abbreviation"],
                page=it.get("page"),
            )
            for it in _load("equipment-base.json")["itemType"]
        ]
        self._check_unique(EquipmentType, rows)
        EquipmentType.objects.bulk_create(rows)
        self.stdout.write(f"  EquipmentType: {EquipmentType.objects.count()}")

    def _import_equipment_properties(self):
        rows = []
        for it in _load("equipment-base.json")["itemProperty"]:
            display_name = it["abbreviation"]
            if it.get("entries") and isinstance(it["entries"][0], dict):
                display_name = it["entries"][0].get("name", display_name)
            rows.append(
                EquipmentProperty(
                    id=_slug(it["abbreviation"]),
                    name=display_name,
                    page=it["page"],
                    srd=bool(it.get("srd52", False)),
                    abbreviation=it["abbreviation"],
                    hidden=it.get("hidden", False),
                    entries=it.get("entries", []),
                )
            )
        self._check_unique(EquipmentProperty, rows)
        EquipmentProperty.objects.bulk_create(rows)
        self.stdout.write(f"  EquipmentProperty: {EquipmentProperty.objects.count()}")

    def _import_species(self):
        rows = [
            Species(
                id=_slug(it["name"]),
                name=it["name"],
                short_description=SPECIES_SHORT_DESCRIPTIONS.get(_slug(it["name"]), ""),
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                hidden=it.get("hidden", False),
                size=it.get("size", []),
                speed=it["speed"] if isinstance(it.get("speed"), int) else 30,
                darkvision=it.get("darkvision", 0),
                creature_types=it.get("creatureTypes", []),
                resistances=[r for r in it.get("resist", []) if isinstance(r, str)],
                additional_spells=[a for a in it.get("additionalSpells", []) if "name" not in a],
                lineages=_species_lineages(it),
                entries=it.get("entries", []),
            )
            for it in _load("species.json")["race"]
        ]
        self._check_unique(Species, rows)
        Species.objects.bulk_create(rows)
        self.stdout.write(f"  Species: {Species.objects.count()}")

    def _import_feats(self):
        rows = [
            Feat(
                id=_slug(it["name"]),
                name=it["name"],
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                category=_decode_code(it.get("category", ""), FEAT_CATEGORY_CODES),
                prerequisite=it.get("prerequisite", []),
                ability=it.get("ability", []),
                additional_spells=it.get("additionalSpells", []),
                grants={k: it[k] for k in FEAT_GRANT_KEYS if k in it},
                entries=it.get("entries", []),
            )
            for it in _load("feats.json")["feat"]
        ]
        self._check_unique(Feat, rows)
        Feat.objects.bulk_create(rows)
        self.stdout.write(f"  Feat: {Feat.objects.count()}")

    def _import_optional_features(self):
        rows = [
            OptionalFeature(
                id=_slug(it["name"]),
                name=it["name"],
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                feature_type=", ".join(
                    _decode_code(c, OPTIONAL_FEATURE_TYPE_CODES) for c in it.get("featureType", [])
                ),
                prerequisite=it.get("prerequisite", []),
                consumes_resource_name=(it.get("consumes") or {}).get("name", ""),
                additional_spells=it.get("additionalSpells", []),
                entries=it.get("entries", []),
            )
            for it in _load("optionalfeatures.json")["optionalfeature"]
        ]
        self._check_unique(OptionalFeature, rows)
        OptionalFeature.objects.bulk_create(rows)
        self.stdout.write(f"  OptionalFeature: {OptionalFeature.objects.count()}")

    def _import_classes(self):
        data = _load("classes.json")
        class_feature_lookup = {
            (
                cf["name"].strip().lower(),
                cf["className"].strip().lower(),
                cf["classSource"].strip().lower(),
                cf["level"],
            ): cf
            for cf in data["classFeature"]
        }
        subclass_feature_lookup = {
            (
                sf["name"].strip().lower(),
                sf["className"].strip().lower(),
                sf.get("subclassShortName", "").strip().lower(),
                sf.get("subclassSource", "").strip().lower(),
                sf["level"],
            ): sf
            for sf in data["subclassFeature"]
        }
        subclasses_by_class: dict[str, list[dict]] = {}
        for sc in data["subclass"]:
            subclasses_by_class.setdefault(sc["className"].strip().lower(), []).append(sc)

        ability_by_id = {a.id: a for a in Ability.objects.all()}
        class_features = []
        subclass_features = []
        choice_option_keys = {
            _parse_class_feature_ref(ref)
            for cf in class_feature_lookup.values()
            for ref in _option_pointer_refs(cf.get("entries", []))
        }
        skipped_refs = []

        for it in data["class"]:
            cid = _slug(it["name"])
            primary_list = it.get("primaryAbility", [])
            if len(primary_list) > 1:
                conjunction = "or"
            elif len(primary_list) == 1 and len(primary_list[0]) > 1:
                conjunction = "and"
            else:
                conjunction = ""
            primary_codes = [code for d in primary_list for code in d]
            saving_codes = it.get("proficiency", [])
            hd = it.get("hd") or {}
            starting_prof = it.get("startingProficiencies") or {}

            klass = Class.objects.create(
                id=cid,
                name=it["name"],
                short_description=CLASS_SHORT_DESCRIPTIONS.get(cid, ""),
                page=it["page"],
                srd=bool(it.get("srd52", False)),
                hit_die=f"d{hd['faces']}" if hd else "",
                primary_ability_conjunction=conjunction,
                armor_proficiencies=starting_prof.get("armorProficiencies", []),
                weapon_proficiencies=_class_weapon_proficiencies(starting_prof),
                tool_proficiencies=starting_prof.get("toolProficiencies", []),
                subclass_title=it.get("subclassTitle", ""),
                spellcasting_ability=ability_by_id.get(it.get("spellcastingAbility", "")),
                caster_progression=it.get("casterProgression") or "",
            )
            klass.primary_abilities.set(
                ability_by_id[c] for c in primary_codes if c in ability_by_id
            )
            klass.saving_throw_abilities.set(
                ability_by_id[c] for c in saving_codes if c in ability_by_id
            )

            level_data = _class_levels_by_number(it)
            class_levels = ClassLevel.objects.bulk_create(
                ClassLevel(klass=klass, level=level, **level_data[level]) for level in range(1, 21)
            )
            class_level_by_number = {cl.level: cl for cl in class_levels}

            seen_keys: set = set()
            queue = list(it.get("classFeatures", []))
            while queue:
                ref = queue.pop(0)
                ref_str = ref["classFeature"] if isinstance(ref, dict) else ref
                key = _parse_class_feature_ref(ref_str)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                raw = class_feature_lookup.get(key)
                if raw is None:
                    skipped_refs.append(("classFeature", it["name"], ref_str))
                    continue
                queue.extend(
                    _walk_feature_pointers(
                        raw.get("entries", []), "refClassFeature", "classFeature"
                    )
                )
                if raw.get("header"):
                    # A sub-heading, not a standalone feature - inlined into whichever feature(s)
                    # point at it instead (see `_inline_header_class_features()`), not given its
                    # own `Feature` row here.
                    continue
                class_features.append(
                    Feature(
                        class_level=class_level_by_number[key[3]],
                        name=raw["name"],
                        entries=_inline_header_class_features(
                            raw.get("entries", []), class_feature_lookup
                        ),
                        consumes_resource_name=(raw.get("consumes") or {}).get("name", ""),
                        choice_option=key in choice_option_keys,
                    )
                )

            for sc in subclasses_by_class.get(it["name"].strip().lower(), []):
                if sc.get("source") != "XPHB":
                    continue
                subclass_obj = Subclass.objects.create(
                    klass=klass,
                    name=sc["name"],
                    description=[],
                    additional_spells=sc.get("additionalSpells", []),
                )
                description: list = []
                entries_by_level = []
                levels_needed: set[int] = set()
                seen_keys = set()
                queue = list(sc.get("subclassFeatures", []))
                while queue:
                    ref = queue.pop(0)
                    key = _parse_subclass_feature_ref(ref)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    raw = subclass_feature_lookup.get(key)
                    if raw is None:
                        skipped_refs.append(("subclassFeature", sc["name"], ref))
                        continue
                    level = key[4]
                    levels_needed.add(level)
                    if raw["name"].strip().lower() == sc["name"].strip().lower():
                        description = [e for e in raw.get("entries", []) if isinstance(e, str)]
                    else:
                        entries_by_level.append((level, raw))
                    queue.extend(
                        _walk_feature_pointers(
                            raw.get("entries", []), "refSubclassFeature", "subclassFeature"
                        )
                    )

                # Sub-heading features (`header` set) that a feature other than the subclass's own
                # wrapper points at are inlined into it, not listed as features of their own.
                nested = {
                    _parse_subclass_feature_ref(r)
                    for _, raw in entries_by_level
                    if raw["name"].strip().lower() != sc["name"].strip().lower()
                    for r in _walk_feature_pointers(
                        raw.get("entries", []), "refSubclassFeature", "subclassFeature"
                    )
                }
                entries_by_level = [
                    (level, raw)
                    for level, raw in entries_by_level
                    if not (
                        raw.get("header")
                        and (
                            raw["name"].strip().lower(),
                            raw["className"].strip().lower(),
                            raw["subclassShortName"].strip().lower(),
                            raw["subclassSource"].strip().lower(),
                            raw["level"],
                        )
                        in nested
                    )
                ]

                subclass_obj.description = description
                subclass_obj.save(update_fields=["description"])

                subclass_levels = SubclassLevel.objects.bulk_create(
                    SubclassLevel(subclass=subclass_obj, level=level)
                    for level in sorted(levels_needed)
                )
                level_by_number = {sl.level: sl for sl in subclass_levels}
                for level, raw in entries_by_level:
                    lands = land_features(raw["name"], raw.get("entries", []), None)
                    generic_entries = _inline_subclass_features(
                        raw.get("entries", []), subclass_feature_lookup
                    )
                    if lands:
                        captions = [
                            e["caption"]
                            for e in generic_entries
                            if isinstance(e, dict) and e.get("type") == "table"
                        ]
                        generic_entries = link_lands(generic_entries, raw["name"], captions)
                    subclass_features.append(
                        Feature(
                            subclass_level=level_by_number[level],
                            name=raw["name"],
                            entries=generic_entries,
                            consumes_resource_name=(raw.get("consumes") or {}).get("name", ""),
                        )
                    )
                    for land in lands:
                        subclass_features.append(
                            Feature(
                                subclass_level=level_by_number[level],
                                name=land[0],
                                entries=land[1],
                                choice_option=True,
                            )
                        )

        Feature.objects.bulk_create(class_features + subclass_features)

        if skipped_refs:
            self.stdout.write(
                self.style.WARNING(f"  Skipped {len(skipped_refs)} unresolved feature refs:")
            )
            for kind, parent, ref in skipped_refs[:20]:
                self.stdout.write(f"    {kind} {parent!r}: {ref!r}")

        self.stdout.write(
            f"  Class: {Class.objects.count()}, ClassLevel: {ClassLevel.objects.count()}, "
            f"Subclass: {Subclass.objects.count()}, SubclassLevel: {SubclassLevel.objects.count()}"
        )

    def _import_equipment_groups(self):
        class_by_name = {c.name.lower(): c for c in Class.objects.all()}
        rows = []
        focus_by_id = {}
        for it in _load("equipment.json")["itemGroup"]:
            gid = _slug(it["name"])
            rows.append(EquipmentGroup(id=gid, name=it["name"], page=it.get("page")))
            focus_by_id[gid] = it.get("focus", [])
        self._check_unique(EquipmentGroup, rows)
        EquipmentGroup.objects.bulk_create(rows)
        for group in EquipmentGroup.objects.all():
            names = focus_by_id.get(group.id, [])
            group.focus_classes.set(
                class_by_name[n.lower()] for n in names if n.lower() in class_by_name
            )
        self.stdout.write(f"  EquipmentGroup: {EquipmentGroup.objects.count()}")

    def _import_equipment(self):
        equipment_type_by_abbr = {t.abbreviation.lower(): t for t in EquipmentType.objects.all()}
        property_by_abbr = {p.abbreviation.lower(): p for p in EquipmentProperty.objects.all()}
        mastery_by_name = {m.name.lower(): m for m in Mastery.objects.all()}
        group_by_name = {g.name.lower(): g for g in EquipmentGroup.objects.all()}

        raw_items = [
            *_load("equipment-base.json")["baseitem"],
            *_load("equipment.json")["item"],
        ]

        rows = []
        for it in raw_items:
            type_ref = it.get("type", "")
            type_abbr = type_ref.split("|")[0].lower() if type_ref else None
            strength = it.get("strength") or None
            group_refs = it.get("group") or []
            group = group_by_name.get(group_refs[0].lower()) if group_refs else None

            rows.append(
                Equipment(
                    id=_slug(it["name"]),
                    name=it["name"],
                    page=it["page"],
                    srd=bool(it.get("srd52", False)),
                    type=equipment_type_by_abbr.get(type_abbr),
                    weapon_category=it.get("weaponCategory", ""),
                    weight=it.get("weight"),
                    value=it.get("value"),
                    damage_dice=it.get("dmg1", ""),
                    damage_type=DAMAGE_TYPE_CODES.get(it.get("dmgType", ""), it.get("dmgType", "")),
                    versatile_damage_dice=it.get("dmg2", ""),
                    ac=it.get("ac"),
                    strength_requirement=int(strength) if strength else None,
                    stealth_disadvantage=it.get("stealth", False),
                    range=str(it["range"]) if it.get("range") else "",
                    group=group,
                    stats={k: it[k] for k in EQUIPMENT_STAT_KEYS if k in it},
                    entries=it.get("entries", []),
                )
            )

        self._check_unique(Equipment, rows)
        Equipment.objects.bulk_create(rows)

        equipment_by_id = {e.id: e for e in Equipment.objects.all()}
        for it in raw_items:
            equipment = equipment_by_id[_slug(it["name"])]
            # A property/mastery ref is usually a bare "abbrev|source"/"name|source" string, but
            # can carry an extra note (e.g. Lance's Two-Handed property, "unless mounted") as
            # {"uid": "...", "note": "..."} instead - the note itself isn't modeled, just unwrapped.
            prop_refs = [
                (p["uid"] if isinstance(p, dict) else p).split("|")[0].lower()
                for p in it.get("property", [])
            ]
            equipment.properties.set(
                property_by_abbr[r] for r in prop_refs if r in property_by_abbr
            )
            mastery_refs = [
                (m["uid"] if isinstance(m, dict) else m).split("|")[0].lower()
                for m in it.get("mastery", [])
            ]
            equipment.masteries.set(
                mastery_by_name[r] for r in mastery_refs if r in mastery_by_name
            )

        equipment_by_name = {e.name.lower(): e for e in Equipment.objects.all()}
        pack_rows = []
        for it in _load("equipment.json")["item"]:
            pack = equipment_by_name.get(it["name"].lower())
            for ref, qty in _pack_content_entries(it.get("packContents")):
                name, _source = _parse_ref(ref)
                content = equipment_by_name.get(name)
                if pack and content:
                    pack_rows.append(EquipmentPackContent(pack=pack, item=content, quantity=qty))
        EquipmentPackContent.objects.bulk_create(pack_rows)

        self.stdout.write(
            f"  Equipment: {Equipment.objects.count()}, "
            f"EquipmentPackContent: {EquipmentPackContent.objects.count()}"
        )

    def _import_spells(self):
        spell_classes = {n.lower(): v for n, v in _load("spell_classes.json").items()}
        ability_by_name = {a.name.lower(): a for a in Ability.objects.all()}

        rows = []
        for it in _load("spells.json")["spell"]:
            old = spell_classes.get(it["name"].lower(), {})
            rows.append(
                Spell(
                    id=_slug(it["name"]),
                    name=it["name"],
                    page=it["page"],
                    srd=bool(it.get("srd52", False)),
                    level=it["level"],
                    school=SCHOOL_CODES.get(it.get("school", ""), it.get("school", "")),
                    casting_time=it.get("time", []),
                    range=it.get("range", {}),
                    components=it.get("components", {}),
                    duration=it.get("duration", []),
                    concentration=any(
                        isinstance(d, dict) and d.get("concentration")
                        for d in it.get("duration", [])
                    ),
                    ritual=bool((it.get("meta") or {}).get("ritual", False)),
                    classes=old.get("classes", []),
                    subclasses=old.get("subclasses", []),
                    entries=it.get("entries", []),
                    entries_higher_level=it.get("entriesHigherLevel", []),
                )
            )
        self._check_unique(Spell, rows)
        Spell.objects.bulk_create(rows)

        spell_by_id = {s.id: s for s in Spell.objects.all()}
        for it in _load("spells.json")["spell"]:
            names = [n.strip().lower() for n in it.get("savingThrow", [])]
            spell_by_id[_slug(it["name"])].saving_throw_abilities.set(
                ability_by_name[n] for n in names if n in ability_by_name
            )
        self.stdout.write(f"  Spell: {Spell.objects.count()}")

    def _import_backgrounds(self):
        feat_by_name = {f.name.lower(): f for f in Feat.objects.all()}

        rows = []
        for it in _load("backgrounds.json")["background"]:
            feat_obj = None
            feat_variant = ""
            for entry in it.get("feats", []):
                for key, val in entry.items():
                    if val:
                        feat_obj = feat_by_name.get(_feat_ref_base_name(key))
                        feat_variant = _feat_ref_variant(key)
                        break
                if feat_obj:
                    break
            rows.append(
                Background(
                    id=_slug(it["name"]),
                    name=it["name"],
                    short_description=BACKGROUND_SHORT_DESCRIPTIONS.get(_slug(it["name"]), ""),
                    page=it["page"],
                    srd=bool(it.get("srd52", False)),
                    ability_scores=it.get("ability", []),
                    tools=it.get("toolProficiencies", []),
                    feat=feat_obj,
                    feat_variant=feat_variant,
                    entries=it.get("entries", []),
                )
            )
        self._check_unique(Background, rows)
        Background.objects.bulk_create(rows)

        skill_by_id = {s.id: s for s in Skill.objects.all()}
        background_by_id = {b.id: b for b in Background.objects.all()}
        for it in _load("backgrounds.json")["background"]:
            background = background_by_id[_slug(it["name"])]
            skill_ids = [
                _slug(key)  # source keys are names ("sleight of hand"), ids are slugs
                for entry in it.get("skillProficiencies", [])
                for key, val in entry.items()
                if val is True
            ]
            missing = [i for i in skill_ids if i not in skill_by_id]
            if missing:  # was silently dropped before - never again
                raise CommandError(f"Background {it['name']}: unknown skill(s) {missing}")
            background.skills.set(skill_by_id[i] for i in skill_ids)
        self.stdout.write(f"  Background: {Background.objects.count()}")

    def _import_background_starting_equipment(self):
        equipment_by_name = {e.name.lower(): e for e in Equipment.objects.all()}
        group_by_name = {g.name.lower(): g for g in EquipmentGroup.objects.all()}
        rows = []
        for it in _load("backgrounds.json")["background"]:
            background = Background.objects.get(id=_slug(it["name"]))
            for option, item, group, qty, gold in _starting_equipment_rows(
                it.get("startingEquipment"), equipment_by_name, group_by_name
            ):
                rows.append(
                    BackgroundStartingEquipmentOption(
                        background=background,
                        option=option,
                        item=item,
                        group=group,
                        quantity=qty,
                        gold_value=gold,
                    )
                )
        BackgroundStartingEquipmentOption.objects.bulk_create(rows)
        count = BackgroundStartingEquipmentOption.objects.count()
        self.stdout.write(f"  BackgroundStartingEquipmentOption: {count}")

    def _import_class_starting_equipment(self):
        equipment_by_name = {e.name.lower(): e for e in Equipment.objects.all()}
        group_by_name = {g.name.lower(): g for g in EquipmentGroup.objects.all()}
        rows = []
        for it in _load("classes.json")["class"]:
            klass = Class.objects.get(id=_slug(it["name"]))
            raw_list = (it.get("startingEquipment") or {}).get("defaultData", [])
            for option, item, group, qty, gold in _starting_equipment_rows(
                raw_list, equipment_by_name, group_by_name
            ):
                rows.append(
                    ClassStartingEquipmentOption(
                        klass=klass,
                        option=option,
                        item=item,
                        group=group,
                        quantity=qty,
                        gold_value=gold,
                    )
                )
        ClassStartingEquipmentOption.objects.bulk_create(rows)
        self.stdout.write(
            f"  ClassStartingEquipmentOption: {ClassStartingEquipmentOption.objects.count()}"
        )

    def _import_proficiencies(self):
        rows = []
        for klass in Class.objects.all():
            for field, category in [
                ("armor_proficiencies", "armor"),
                ("weapon_proficiencies", "weapon"),
            ]:
                for name, extra in _flag_items(getattr(klass, field)):
                    rows.append(
                        Proficiency(
                            klass=klass, category=category, name=name, choice_data=extra or {}
                        )
                    )
            for entry in klass.tool_proficiencies or []:
                for key, val in entry.items():
                    if val is True:
                        rows.append(Proficiency(klass=klass, category="tool", name=key))
                    else:
                        rows.append(
                            Proficiency(
                                klass=klass, category="tool", name="", choice_data={key: val}
                            )
                        )
        for background in Background.objects.all():
            for entry in background.tools or []:
                for key, val in entry.items():
                    if val is True:
                        rows.append(Proficiency(background=background, category="tool", name=key))
                    else:
                        rows.append(
                            Proficiency(
                                background=background,
                                category="tool",
                                name="",
                                choice_data={key: val},
                            )
                        )
        Proficiency.objects.bulk_create(rows)
        self.stdout.write(f"  Proficiency: {Proficiency.objects.count()}")

    def _import_features(self):
        """Returns {feature.pk: entries} so `_import_effects` can re-walk each Feature's text
        without a second pass over `db/`. Class and subclass features are created earlier,
        directly in `_import_classes` - this only handles the two sources that still keep their
        features/entries JSON verbatim on the parent model (`Species`/`Feat`).
        """
        rows = []
        for species in Species.objects.all():
            for d in _named_dicts(species.entries):
                rows.append(Feature(species=species, name=d["name"], entries=d.get("entries", [])))
            for lineage in species.lineages:
                cut = lineage_feature(species.entries, None, lineage)
                if cut:
                    rows.append(
                        Feature(species=species, name=cut[0], entries=cut[1], choice_option=True)
                    )
        for feat in Feat.objects.all():
            for d in _named_dicts(feat.entries):
                rows.append(Feature(feat=feat, name=d["name"], entries=d.get("entries", [])))

        Feature.objects.bulk_create(rows)
        self.stdout.write(f"  Feature: {Feature.objects.count()}")
        return {feature.pk: feature.entries for feature in Feature.objects.all()}

    def _import_effects(self, features_by_source: dict):
        rows = [
            Effect(feature_id=feature_id, tag=tag, raw=raw)
            for feature_id, entries in features_by_source.items()
            for tag, raw in _walk_tags(entries)
        ]
        Effect.objects.bulk_create(rows)
        self.stdout.write(f"  Effect: {Effect.objects.count()}")

    def _import_choice_definitions(self):
        rows = []

        for background in Background.objects.all():
            if background.ability_scores:
                rows.append(
                    ChoiceDefinition(
                        background=background,
                        kind="ability_scores",
                        options=background.ability_scores,
                        count=None,
                    )
                )

        class_raw_by_id = {_slug(it["name"]): it for it in _load("classes.json")["class"]}
        for klass in Class.objects.all():
            raw = class_raw_by_id.get(klass.id, {})
            skills = (raw.get("startingProficiencies") or {}).get("skills", [])
            rows.extend(_iter_choice_rows("skills", skills, klass=klass))

        species_raw_by_id = {_slug(it["name"]): it for it in _load("species.json")["race"]}
        for species in Species.objects.all():
            raw = species_raw_by_id.get(species.id, {})
            rows.extend(_iter_choice_rows("skills", raw.get("skillProficiencies"), species=species))
            rows.extend(_iter_choice_rows("resistances", raw.get("resist"), species=species))
            rows.extend(_iter_feat_category_choice_rows(raw.get("feats"), species=species))

        feat_raw_by_id = {_slug(it["name"]): it for it in _load("feats.json")["feat"]}
        for feat in Feat.objects.all():
            raw = feat_raw_by_id.get(feat.id, {})
            rows.extend(_iter_choice_rows("ability_scores", raw.get("ability"), feat=feat))
            rows.extend(
                _iter_choice_rows("saving_throws", raw.get("savingThrowProficiencies"), feat=feat)
            )
            rows.extend(_iter_choice_rows("skills", raw.get("skillProficiencies"), feat=feat))
            rows.extend(_iter_choice_rows("resistances", raw.get("resist"), feat=feat))

        ChoiceDefinition.objects.bulk_create(rows)
        self.stdout.write(f"  ChoiceDefinition: {ChoiceDefinition.objects.count()}")

    def _import_handbook(self):
        # The source's shape (chapters, each flattened into one row per named section), the
        # Italian overlay merge and the parts dropped for having no Italian text all live in
        # `apps.rules.handbook_source`, shared with `import_translations`.
        try:
            chapters, english, italian = load_handbook()
        except TranslationDataError as exc:
            raise CommandError(str(exc)) from exc

        HandbookChapter.objects.bulk_create(
            HandbookChapter(id=chapter["id"], name_en=chapter["name"], name_it=chapter["name_it"])
            for chapter in chapters
        )
        rows = [
            HandbookSection(
                id=row["id"],
                chapter_id=row["chapter"],
                name_en=row["name"],
                entries_en=row["entries"],
                name_it=italian.get(row["id"], {}).get("name"),
                entries_it=italian.get(row["id"], {}).get("entries"),
                self_translated_fields=italian.get(row["id"], {}).get("self_translated_fields", []),
                page=row["page"],
            )
            for row in english
        ]
        HandbookSection.objects.bulk_create(rows)
        self.stdout.write(
            f"  HandbookChapter: {HandbookChapter.objects.count()}; "
            f"HandbookSection: {HandbookSection.objects.count()} "
            f"({len(italian)} with Italian text)"
        )

    def _import_lore(self):
        """Populates `Species.lore`/`Background.lore`/`Class.lore` from `db/fluff-*.json`, once
        those ship (see `_load_if_exists`) - the extension point flagged in
        `docs/data_migration_2025.md` §3.7 when this project's `db/` drop had no fluff data at
        all. Each fluff entry's `entries` value is stored verbatim, unchanged in shape from every
        other `entries`-shaped field this project already renders generically via
        `render_entries()` - no unwrapping needed even though it's more deeply nested here (e.g.
        species fluff wraps its prose two `{"type": "entries", "entries": [...]}` levels deep)
        than a flat `Background.entries` list.

        Checked and skipped, not silently missing: `db/fluff-feats.json` and
        `db/fluff-equipment.json` carry only `images` (art credits), no `entries` at all, for
        every single row - `Feat`/`Equipment` have no `lore` field to populate anyway, consistent
        with this project's standing choice to drop art-asset fields everywhere (see the
        `apps/rules/` README section). `db/fluff-classes.json`'s `subclassFluff` (48 rows) is the
        same story - zero of them carry `entries` - so `Subclass` (which has no `lore` field
        either, only `description`, already sourced from the primary `db/classes.json`) is
        untouched here too.
        """
        species_fluff = _load_if_exists("fluff-species.json")
        if species_fluff:
            entries_by_name = {
                it["name"].lower(): it["entries"]
                for it in species_fluff["raceFluff"]
                if it.get("entries")
            }
            for species in Species.objects.all():
                entries = entries_by_name.get(species.name.lower())
                if entries:
                    species.lore = entries
                    species.save(update_fields=["lore"])

        background_fluff = _load_if_exists("fluff-backgrounds.json")
        if background_fluff:
            entries_by_name = {
                it["name"].lower(): it["entries"]
                for it in background_fluff["backgroundFluff"]
                if it.get("entries")
            }
            for background in Background.objects.all():
                entries = entries_by_name.get(background.name.lower())
                if entries:
                    background.lore = entries
                    background.save(update_fields=["lore"])

        class_fluff = _load_if_exists("fluff-classes.json")
        if class_fluff:
            entries_by_name = {
                it["name"].lower(): it["entries"]
                for it in class_fluff["classFluff"]
                if it.get("entries")
            }
            for klass in Class.objects.all():
                entries = entries_by_name.get(klass.name.lower())
                if entries:
                    klass.lore = entries
                    klass.save(update_fields=["lore"])

        self.stdout.write(
            f"  Lore: {Species.objects.exclude(lore=[]).count()} species, "
            f"{Background.objects.exclude(lore=[]).count()} backgrounds, "
            f"{Class.objects.exclude(lore=[]).count()} classes"
        )
