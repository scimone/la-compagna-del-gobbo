import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

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
from apps.rules.models.effect import TAG_PATTERN

DB_DIR = Path(settings.BASE_DIR) / "db"


def _load(filename: str) -> list[dict]:
    with open(DB_DIR / filename, encoding="utf-8") as f:
        return json.load(f)["items"]


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

        self.stdout.write(self.style.SUCCESS("Rules data imported."))

    def _delete_existing(self):
        # Deleting these top-level catalogs cascades onto everything derived from them
        # (ClassLevel/Subclass/SubclassLevel/Feature/Effect/Proficiency/ChoiceDefinition).
        for model in [
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

    def _import_skills(self):
        Skill.objects.bulk_create(
            Skill(
                id=it["id"],
                name=it["name"],
                page=it["page"],
                srd=it["srd"],
                ability=it["ability"],
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
            if it["source"] == "XPHB"
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
        for it in _load("classes.json"):
            klass = Class.objects.create(
                id=it["id"],
                name=it["name"],
                short_description=CLASS_SHORT_DESCRIPTIONS.get(it["id"], ""),
                page=it["page"],
                srd=it["srd"],
                hit_die=it["hitDie"],
                primary_ability=it["primaryAbility"],
                saving_throws=it["savingThrows"],
                proficiencies=it.get("proficiencies", ""),
                armor_proficiencies=it.get("armorProficiencies", ""),
                weapon_proficiencies=it.get("weaponProficiencies", ""),
                tool_proficiencies=it.get("toolProficiencies", ""),
                subclass_title=it.get("subclassTitle", ""),
                lore=it.get("lore", []),
                features=it.get("features", []),
            )

            headers = it["table"]["headers"]
            ClassLevel.objects.bulk_create(
                ClassLevel(
                    klass=klass, level=int(row[0]), columns=dict(zip(headers, row, strict=True))
                )
                for row in it["table"]["rows"]
            )

            for sc in it.get("subclasses", []):
                if sc.get("source") != "XPHB":
                    continue
                subclass = Subclass.objects.create(klass=klass, name=sc["name"])
                by_level: dict[int, list[dict]] = {}
                for feat in sc.get("features", []):
                    by_level.setdefault(feat["level"], []).append(
                        {"name": feat["name"], "entries": feat["entries"]}
                    )
                SubclassLevel.objects.bulk_create(
                    SubclassLevel(subclass=subclass, level=level, features=feats)
                    for level, feats in by_level.items()
                )

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
        without a second pass over `db/`.
        """
        rows = []
        for klass in Class.objects.all():
            for d in _named_dicts(klass.features):
                rows.append(
                    Feature(klass=klass, level=d.get("level"), name=d["name"], entries=d["entries"])
                )
        for subclass_level in SubclassLevel.objects.all():
            for d in _named_dicts(subclass_level.features):
                rows.append(
                    Feature(
                        subclass_level=subclass_level,
                        level=subclass_level.level,
                        name=d["name"],
                        entries=d["entries"],
                    )
                )
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
