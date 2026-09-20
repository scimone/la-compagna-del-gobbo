"""Integrity checks on the imported catalogs that character creation depends on.

Each test pins a gap found while auditing the data for `docs/character_creation_plan.md` (section
3.2) - several of them lost data silently, so a row count would never have caught them.
"""

import pytest

from apps.rules.models import (
    Background,
    BackgroundStartingEquipmentOption,
    ChoiceDefinition,
    Class,
    ClassStartingEquipmentOption,
    Equipment,
    Feat,
    Skill,
    Species,
)

pytestmark = pytest.mark.usefixtures("imported_rules")


def test_every_class_has_a_weapon_proficiency_grant(db):
    grants = {c.id: c.weapon_proficiencies for c in Class.objects.all()}

    assert all(grants.values()), grants  # none left empty
    assert grants["fighter"] == [{"simple": True, "martial": True}]
    assert grants["wizard"] == [{"simple": True}]
    # Monk and Rogue keep their structured, filtered grant.
    assert grants["monk"][0]["simple"] is True and "all" in grants["monk"][0]
    assert "all" in grants["rogue"][0]


def test_every_background_grants_exactly_two_skills(db):
    counts = {b.id: b.skills.count() for b in Background.objects.all()}

    assert set(counts.values()) == {2}, counts
    skills = {s.id for s in Background.objects.get(id="criminal").skills.all()}
    assert skills == {"sleight-of-hand", "stealth"}


def test_skill_choice_options_are_real_skill_ids(db):
    skill_ids = set(Skill.objects.values_list("id", flat=True))

    for choice in ChoiceDefinition.objects.filter(kind="skills"):
        assert set(choice.options) <= skill_ids, (choice, choice.options)
    rogue = ChoiceDefinition.objects.get(klass_id="rogue", kind="skills")
    assert "sleight-of-hand" in rogue.options and rogue.count == 4


def test_every_background_grants_an_origin_feat_and_the_magic_initiate_list(db):
    for background in Background.objects.all():
        assert background.feat_id and background.feat.category == "Origin", background.id

    variants = {b.id: b.feat_variant for b in Background.objects.filter(feat_id="magic-initiate")}
    assert variants == {"acolyte": "cleric", "guide": "druid", "sage": "wizard"}


def test_origin_feats_carry_their_sub_choices(db):
    magic_initiate = Feat.objects.get(id="magic-initiate")
    assert {s["name"] for s in magic_initiate.additional_spells} == {
        "Cleric Spells",
        "Druid Spells",
        "Wizard Spells",
    }
    assert "skillToolLanguageProficiencies" in Feat.objects.get(id="skilled").grants
    assert "toolProficiencies" in Feat.objects.get(id="musician").grants


def test_species_lineages_are_imported_with_their_effects(db):
    elf = Species.objects.get(id="elf")
    lineages = {lin["key"]: lin for lin in elf.lineages}
    assert set(lineages) == {"drow", "high-elf", "wood-elf"}
    assert lineages["drow"]["darkvision"] == 120
    assert lineages["wood-elf"]["speed"] == 35
    assert all(lin["replaces"] == "Elven Lineage" for lin in lineages.values())
    assert all(lin["additional_spells"] for lin in lineages.values())

    counts = {s.id: len(s.lineages) for s in Species.objects.all() if s.lineages}
    assert counts == {"dragonborn": 10, "elf": 3, "gnome": 2, "goliath": 6, "tiefling": 3}
    black = next(
        lin for lin in Species.objects.get(id="dragonborn").lineages if lin["key"] == "black"
    )
    assert black["damage_type"] == "acid" and black["resistances"] == ["acid"]


def test_species_flat_grants_are_imported(db):
    assert Species.objects.get(id="aasimar").resistances == ["necrotic", "radiant"]
    assert Species.objects.get(id="dwarf").resistances == ["poison"]
    aasimar_spells = Species.objects.get(id="aasimar").additional_spells
    assert aasimar_spells[0]["known"] == {"1": ["light|xphb#c"]}
    # Per-lineage spell variants are not duplicated on the species itself.
    assert Species.objects.get(id="elf").additional_spells == []


def test_every_starting_equipment_row_resolves_to_exactly_one_thing(db):
    for row in [
        *ClassStartingEquipmentOption.objects.all(),
        *BackgroundStartingEquipmentOption.objects.all(),
    ]:
        assert [bool(row.item_id), bool(row.group_id), row.gold_value is not None].count(
            True
        ) == 1, row


def test_named_tool_grants_resolve_to_equipment(db):
    names = {e.name.lower() for e in Equipment.objects.all()}
    for background in Background.objects.all():
        for grant in background.tools:
            for key, value in grant.items():
                if value is True:
                    assert key in names, (background.id, key)
