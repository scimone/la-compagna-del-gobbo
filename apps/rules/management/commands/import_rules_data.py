import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.rules.models import (
    Ability,
    Background,
    ChoiceDefinition,
    Class,
    ClassLevel,
    Effect,
    Equipment,
    EquipmentProperty,
    Feat,
    Feature,
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

DB_DIR = Path(settings.BASE_DIR) / "db"


def _load(filename: str) -> list[dict]:
    with open(DB_DIR / filename, encoding="utf-8") as f:
        return json.load(f)["items"]


def _load_handbook() -> list[dict]:
    # db/handbook.json uses a top-level "data" key (one item per chapter), unlike every other
    # db/*.json file's "items" - a different dump format from a different source pass.
    with open(DB_DIR / "handbook.json", encoding="utf-8") as f:
        return json.load(f)["data"]


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


def _flat_proficiency_items(text: str) -> list[str]:
    """Split a comma-separated proficiency field, excluding items phrased as a choice - see
    Proficiency's docstring.
    """
    items = [x.strip() for x in text.split(",") if x.strip()]
    return [x for x in items if not x.lower().startswith("choose")]


def _find_named_table(node, caption: str) -> dict | None:
    """Depth-first search for a `type: "table"` node with this exact `caption`, anywhere in a
    JSON tree - used to pull `Ability` out of db/handbook.json's "Ability Descriptions" table
    (Chapter 1 -> The Six Abilities) directly, without needing the whole chapter imported first.
    """
    if isinstance(node, dict):
        if node.get("type") == "table" and node.get("caption") == caption:
            return node
        for value in node.values():
            found = _find_named_table(value, caption)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_named_table(item, caption)
            if found:
                return found
    return None


def _parse_ability_list(text: str) -> tuple[list[str], str]:
    """Parse a `Class.primaryAbility`-style string - "Strength", "Strength or Dexterity",
    "Dexterity and Wisdom" - into (ability names, conjunction). Conjunction is "" when there's
    only one name; verified every class's `primaryAbility` matches one of these three shapes
    before relying on it (a bare name, or exactly two joined by " or " or " and ", never three+
    or some other separator).
    """
    if " or " in text:
        return [x.strip() for x in text.split(" or ")], "or"
    if " and " in text:
        return [x.strip() for x in text.split(" and ")], "and"
    return [text.strip()], ""


def _split_subclass_features(
    subclass_name: str, raw_features: list
) -> tuple[list, dict[int, list[dict]]]:
    """Undo a data-modeling error in the source: at a subclass's granting level, `db/classes.json`
    bundles the subclass's own flavor text together with that level's real named features under
    one block titled after the subclass itself, rather than listing the features directly like
    every other level does - so e.g. Monk's Warrior of Mercy previously imported as a single
    "Warrior of Mercy" feature containing "Hand of Harm"/"Hand of Healing"/"Implements of Mercy"
    inline, when those are three separate features that merely happen to all be gained at the
    same level. Verified across all 48 XPHB subclasses before relying on the pattern: every one
    has exactly one such block, always at its granting level, always with at least one nested
    named feature - see the README's "Model status" section for the write-up of this bug and
    the cleanup.

    Returns (description, by_level): `description` is the flavor text (the block's own
    plain-string entries) for `Subclass.description`; `by_level` is every real feature - the
    nested ones promoted to top-level {name, entries} blocks, plus every other level's
    already-correctly-shaped features - grouped by level, ready to become `Feature` rows
    directly (see the caller, `_import_classes`).
    """
    description: list = []
    by_level: dict[int, list[dict]] = {}
    for feat in raw_features:
        if feat["name"] == subclass_name:
            for entry in feat["entries"]:
                if isinstance(entry, dict) and entry.get("name"):
                    by_level.setdefault(feat["level"], []).append(
                        {"name": entry["name"], "entries": entry.get("entries", [])}
                    )
                else:
                    description.append(entry)
        else:
            by_level.setdefault(feat["level"], []).append(
                {"name": feat["name"], "entries": feat["entries"]}
            )
    return description, by_level


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

SPECIES_SHORT_DESCRIPTIONS = {
    "aasimar": "Mortals touched by celestial power.",
    "dragonborn": "Proud, draconic folk with elemental breath.",
    "dwarf": "Sturdy folk of mountain and stone.",
    "elf-xphb": "Graceful, long-lived, attuned to magic.",
    "gnome": "Small, inventive folk full of curiosity.",
    "goliath": "Towering folk from harsh mountain peaks.",
    "grung": "Small, poisonous frog-folk of the jungle.",
    "halfling": "Small, nimble folk known for luck and cheer.",
    "human": "Adaptable, ambitious, and endlessly diverse.",
    "orc": "Strong, resilient folk of fierce endurance.",
    "tiefling": "Mortals marked by an infernal bloodline.",
}


class Command(BaseCommand):
    help = "Wipe and reload every rules model from the XPHB data dumped in db/."

    @transaction.atomic
    def handle(self, *args, **options):
        self._delete_existing()

        self._import_rules()
        self._import_ability()
        self._import_skills()
        self._import_senses()
        self._import_masteries()
        self._import_equipment_properties()
        self._import_equipment()
        self._import_species()
        self._import_backgrounds()
        self._import_feats()
        self._import_languages()
        self._import_optional_features()
        self._import_spells()
        self._import_classes()
        self._import_proficiencies()
        features_by_source = self._import_features()
        self._import_effects(features_by_source)
        self._import_choice_definitions()
        self._import_handbook()

        self.stdout.write(self.style.SUCCESS("Rules data imported."))

    def _delete_existing(self):
        # Feature is deleted explicitly, not left to cascade from the catalogs below: it has no
        # single parent (klass/subclass_level/species/feat are all optional), so if a future
        # migration ever drops one of those FKs, rows that only had *that* one set would survive
        # as orphans with every FK null - the way 260 stale class-feature rows briefly did the
        # one time `Feature.klass` was actually dropped for `class_level`, since nothing else
        # cascades to them without a parent to cascade from.
        Feature.objects.all().delete()

        # Deleting these top-level catalogs cascades onto everything else derived from them
        # (ClassLevel/Subclass/SubclassLevel/Effect/Proficiency/ChoiceDefinition). `Ability`
        # cascades onto `Skill` (FK) and clears the `Class` M2M rows too - safe to delete before
        # or after `Class`/`Skill` either way, but named first since they depend on it.
        for model in [
            Ability,
            Class,
            Species,
            Background,
            Feat,
            Rule,
            Skill,
            Sense,
            Mastery,
            EquipmentProperty,
            Equipment,
            Language,
            OptionalFeature,
            Spell,
            HandbookSection,
        ]:
            model.objects.all().delete()

    def _import_rules(self):
        Rule.objects.bulk_create(
            Rule(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                rule_type=it["ruleType"],
                entries=it.get("entries", []),
            )
            for it in _load("rules.json")
        )
        self.stdout.write(f"  Rule: {Rule.objects.count()}")

    def _import_ability(self):
        chapter = _load_handbook()[0]
        table = _find_named_table(chapter, "Ability Descriptions")
        Ability.objects.bulk_create(
            Ability(id=name.lower(), name=name, description=description)
            for name, description in table["rows"]
        )
        self.stdout.write(f"  Ability: {Ability.objects.count()}")

    def _import_skills(self):
        Skill.objects.bulk_create(
            Skill(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                ability_id=it["ability"].lower(),
                entries=it.get("entries", []),
            )
            for it in _load("skills.json")
        )
        self.stdout.write(f"  Skill: {Skill.objects.count()}")

    def _import_senses(self):
        Sense.objects.bulk_create(
            Sense(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                entries=it.get("entries", []),
            )
            for it in _load("senses.json")
        )
        self.stdout.write(f"  Sense: {Sense.objects.count()}")

    def _import_masteries(self):
        Mastery.objects.bulk_create(
            Mastery(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                entries=it.get("entries", []),
            )
            for it in _load("masteries.json")
        )
        self.stdout.write(f"  Mastery: {Mastery.objects.count()}")

    def _import_equipment_properties(self):
        EquipmentProperty.objects.bulk_create(
            EquipmentProperty(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                abbreviation=it["abbreviation"],
                hidden=it.get("hidden", False),
                entries=it.get("entries", []),
            )
            for it in _load("equipment_properties.json")
        )
        self.stdout.write(f"  EquipmentProperty: {EquipmentProperty.objects.count()}")

    def _import_equipment(self):
        Equipment.objects.bulk_create(
            Equipment(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                category=it["type"],
                weapon_category=it.get("weaponCategory", ""),
                weight=it.get("weight", ""),
                value=it.get("value", ""),
                damage=it.get("damage", ""),
                ac=it.get("ac", ""),
                range=it.get("range", ""),
                attunement=it.get("attunement", ""),
                properties=it.get("properties", ""),
                property_refs=it.get("propertyRefs", []),
                mastery=it.get("mastery", ""),
                mastery_refs=it.get("masteryRefs", []),
                entries=it.get("entries", []),
            )
            for it in _load("equipments.json")
        )
        self.stdout.write(f"  Equipment: {Equipment.objects.count()}")

    def _import_species(self):
        Species.objects.bulk_create(
            Species(
                id=it["id"],
                name=it["name"],
                short_description=SPECIES_SHORT_DESCRIPTIONS.get(it["id"], ""),
                page=it["page"],
                srd=it["srd"],
                hidden=it.get("hidden", False),
                size=it["size"],
                speed=it["speed"],
                walk_speed=it.get("walkSpeed", 0),
                fly_speed=it.get("flySpeed", 0),
                swim_speed=it.get("swimSpeed", 0),
                climb_speed=it.get("climbSpeed", 0),
                creature_type=it["creatureType"],
                parent_race=it.get("parentRace", ""),
                lore=it.get("lore", []),
                entries=it.get("entries", []),
            )
            for it in _load("species.json")
        )
        self.stdout.write(f"  Species: {Species.objects.count()}")

    def _import_backgrounds(self):
        Background.objects.bulk_create(
            Background(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                ability_scores=it["abilityScores"],
                skills=it["skills"],
                tools=it.get("tools", ""),
                feat=it.get("feat", ""),
                lore=it.get("lore", []),
                entries=it.get("entries", []),
            )
            for it in _load("backgrounds.json")
        )
        self.stdout.write(f"  Background: {Background.objects.count()}")

    def _import_feats(self):
        Feat.objects.bulk_create(
            Feat(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                category=it["category"],
                prerequisite=it.get("prerequisite", ""),
                entries=it.get("entries", []),
            )
            for it in _load("feats.json")
        )
        self.stdout.write(f"  Feat: {Feat.objects.count()}")

    def _import_languages(self):
        Language.objects.bulk_create(
            Language(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                language_type=it["languageType"],
                script=it.get("script", ""),
                typical_speakers=it.get("typicalSpeakers", ""),
                entries=it.get("entries", []),
            )
            for it in _load("languages.json")
        )
        self.stdout.write(f"  Language: {Language.objects.count()}")

    def _import_optional_features(self):
        OptionalFeature.objects.bulk_create(
            OptionalFeature(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                feature_type=it["featureType"],
                prerequisite=it.get("prerequisite", ""),
                entries=it.get("entries", []),
            )
            for it in _load("optional_features.json")
        )
        self.stdout.write(f"  OptionalFeature: {OptionalFeature.objects.count()}")

    def _import_spells(self):
        Spell.objects.bulk_create(
            Spell(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                level=it["level"],
                school=it["school"],
                casting_time=it["castingTime"],
                range=it["range"],
                components=it["components"],
                duration=it["duration"],
                concentration=it["concentration"],
                ritual=it["ritual"],
                classes=it.get("classes", []),
                subclasses=it.get("subclasses", []),
                entries=it.get("entries", []),
                entries_higher_level=it.get("entriesHigherLevel", []),
            )
            for it in _load("spells.json")
        )
        self.stdout.write(f"  Spell: {Spell.objects.count()}")

    def _import_classes(self):
        ability_by_name = {a.name.lower(): a for a in Ability.objects.all()}
        class_features = []
        subclass_features = []
        for it in _load("classes.json"):
            primary_names, conjunction = _parse_ability_list(it["primaryAbility"])
            saving_names = [x.strip() for x in it["savingThrows"].split(",")]

            klass = Class.objects.create(
                id=it["id"],
                name=it["name"],
                short_description=CLASS_SHORT_DESCRIPTIONS.get(it["id"], ""),
                page=it["page"],
                srd=it["srd"],
                hit_die=it["hitDie"],
                primary_ability_conjunction=conjunction,
                proficiencies=it.get("proficiencies", ""),
                armor_proficiencies=it.get("armorProficiencies", ""),
                weapon_proficiencies=it.get("weaponProficiencies", ""),
                tool_proficiencies=it.get("toolProficiencies", ""),
                subclass_title=it.get("subclassTitle", ""),
                lore=it.get("lore", []),
            )
            klass.primary_abilities.set(ability_by_name[n.lower()] for n in primary_names)
            klass.saving_throw_abilities.set(ability_by_name[n.lower()] for n in saving_names)

            headers = it["table"]["headers"]
            class_levels = ClassLevel.objects.bulk_create(
                ClassLevel(
                    klass=klass, level=int(row[0]), columns=dict(zip(headers, row, strict=True))
                )
                for row in it["table"]["rows"]
            )
            class_level_by_number = {cl.level: cl for cl in class_levels}

            # Unlike Species/Feat below (imported later, in `_import_features`, from a JSON field
            # still held on the parent), a class's features have nowhere else to live - `Class`
            # keeps no `features` field of its own (see its docstring) - so these rows are built
            # here, directly, FK'd to the matching `ClassLevel` instead of duplicated as JSON.
            class_features.extend(
                Feature(
                    class_level=class_level_by_number[d["level"]],
                    name=d["name"],
                    entries=d["entries"],
                )
                for d in _named_dicts(it.get("features", []))
            )

            for sc in it.get("subclasses", []):
                if sc.get("source") != "XPHB":
                    continue
                description, by_level = _split_subclass_features(sc["name"], sc.get("features", []))
                subclass = Subclass.objects.create(
                    klass=klass, name=sc["name"], description=description
                )
                levels = SubclassLevel.objects.bulk_create(
                    SubclassLevel(subclass=subclass, level=level) for level in by_level
                )
                level_by_number = {sl.level: sl for sl in levels}
                for level, feats in by_level.items():
                    subclass_level = level_by_number[level]
                    subclass_features.extend(
                        Feature(subclass_level=subclass_level, name=f["name"], entries=f["entries"])
                        for f in feats
                    )

        Feature.objects.bulk_create(class_features + subclass_features)

        self.stdout.write(
            f"  Class: {Class.objects.count()}, ClassLevel: {ClassLevel.objects.count()}, "
            f"Subclass: {Subclass.objects.count()}, "
            f"SubclassLevel: {SubclassLevel.objects.count()}"
        )

    def _import_proficiencies(self):
        rows = []
        for klass in Class.objects.all():
            for field, category in [
                ("armor_proficiencies", "armor"),
                ("weapon_proficiencies", "weapon"),
                ("tool_proficiencies", "tool"),
            ]:
                for name in _flat_proficiency_items(getattr(klass, field)):
                    rows.append(Proficiency(klass=klass, category=category, name=name))
        for background in Background.objects.all():
            for field, category in [("skills", "skill"), ("tools", "tool")]:
                for name in _flat_proficiency_items(getattr(background, field)):
                    rows.append(Proficiency(background=background, category=category, name=name))
        Proficiency.objects.bulk_create(rows)
        self.stdout.write(f"  Proficiency: {Proficiency.objects.count()}")

    def _import_features(self):
        """Returns {feature.pk: entries} so `_import_effects` can re-walk each Feature's text
        without a second pass over `db/`. Class and subclass features are created earlier,
        directly in `_import_classes` (there's no `ClassLevel.features`/`SubclassLevel.features`
        JSON field to walk here - see those models' docstrings) - this only handles the two
        sources that still keep their features/entries JSON verbatim on the parent model.
        """
        rows = []
        for species in Species.objects.all():
            for d in _named_dicts(species.entries):
                rows.append(Feature(species=species, name=d["name"], entries=d["entries"]))
        for feat in Feat.objects.all():
            for d in _named_dicts(feat.entries):
                rows.append(Feature(feat=feat, name=d["name"], entries=d["entries"]))

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
            m = re.match(r"Choose from (.+)", background.ability_scores)
            if m:
                rows.append(
                    ChoiceDefinition(
                        background=background,
                        kind="ability_scores",
                        count=None,
                        options=[x.strip() for x in m.group(1).split(",")],
                        source_text=background.ability_scores,
                    )
                )
        for klass in Class.objects.all():
            m = re.search(r"Skills: choose (\d+) from ([^·]+)", klass.proficiencies)
            if m:
                rows.append(
                    ChoiceDefinition(
                        klass=klass,
                        kind="skills",
                        count=int(m.group(1)),
                        options=[x.strip() for x in m.group(2).split(",")],
                        source_text=m.group(0),
                    )
                )
        ChoiceDefinition.objects.bulk_create(rows)
        self.stdout.write(f"  ChoiceDefinition: {ChoiceDefinition.objects.count()}")

    def _import_handbook(self):
        # There's only one chapter in the source - flatten it one level rather than modeling
        # chapters as their own grouping (see HandbookSection's docstring): the chapter's own
        # root block becomes one row (its `entries` trimmed to just its own leading content, not
        # the nested sections' content too, which becomes their own rows below), and each of its
        # direct named children ("Rules Glossary", "Player or DM?", "Dice", ...) becomes one more.
        chapter = _load_handbook()[0]
        leading_entries = [
            e for e in chapter["entries"] if not (isinstance(e, dict) and e.get("name"))
        ]
        named_children = [e for e in chapter["entries"] if isinstance(e, dict) and e.get("name")]

        rows = [
            HandbookSection(
                id=chapter["id"],
                name=chapter["name"],
                page=chapter["page"],
                entries=leading_entries,
            )
        ]
        rows.extend(
            HandbookSection(
                id=child["id"], name=child["name"], page=child["page"], entries=child["entries"]
            )
            for child in named_children
        )
        HandbookSection.objects.bulk_create(rows)
        self.stdout.write(f"  HandbookSection: {HandbookSection.objects.count()}")
