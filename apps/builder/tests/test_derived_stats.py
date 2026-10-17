"""Derived numbers, against the SRD's own formulas and worked examples."""

import pytest

from apps.builder.services import class_choices, creation, derived_stats, origins
from apps.builder.services.store import Draft
from apps.characters.models import CharacterInventoryItem
from apps.rules.models import Equipment, Feat

from .conftest import build_character

pytestmark = pytest.mark.usefixtures("imported_rules")


def wear(character, *equipment_ids):
    """Replace the inventory with exactly these items, worn."""
    character.inventory_items.all().delete()
    for eq in equipment_ids:
        CharacterInventoryItem.objects.create(
            character=character, equipment=Equipment.objects.get(id=eq), equipped=True
        )


def set_scores(character, **scores):
    creation.set_manual_abilities(character, scores)
    character.refresh_from_db()


def test_srd_passive_perception_example(owner):
    """SRD: Wisdom 15 and proficiency in Perception -> passive Perception 14."""
    c = build_character(owner, "wizard")
    set_scores(c, wis=15)
    creation.set_manual_skills(c, {"perception": "proficient"})

    stats = derived_stats.compute(c)

    assert stats.abilities["wis"] == {"score": 15, "modifier": 2}
    assert stats.skills["perception"]["modifier"] == 4  # +2 Wis +2 proficiency
    assert stats.passive_perception == 14


def test_expertise_doubles_the_proficiency_bonus(owner):
    c = build_character(owner, "wizard")
    set_scores(c, dex=14)
    creation.set_manual_skills(c, {"stealth": "expertise", "acrobatics": "proficient"})

    stats = derived_stats.compute(c)

    assert stats.skills["stealth"]["modifier"] == 2 + 4  # Dex +2, expertise 2 x PB 2
    assert stats.skills["acrobatics"]["modifier"] == 2 + 2
    assert stats.skills["arcana"]["modifier"] == stats.abilities["int"]["modifier"] + (
        2 if stats.skills["arcana"]["state"] != "none" else 0
    )


def test_saving_throws_and_proficiency_bonus(owner):
    c = no_feats(build_character(owner, "fighter"))
    stats = derived_stats.compute(c)

    assert stats.proficiency_bonus == 2 and stats.level == 1
    assert stats.saving_throws["str"] == {
        "modifier": stats.abilities["str"]["modifier"] + 2,
        "proficient": True,
    }
    assert stats.saving_throws["dex"]["proficient"] is False
    assert stats.saving_throws["dex"]["modifier"] == stats.abilities["dex"]["modifier"]
    assert stats.initiative == stats.abilities["dex"]["modifier"]
    assert stats.hit_dice == {"d10": {"total": 1, "spent": 0}}


@pytest.mark.parametrize(
    ("worn", "dex", "expected"),
    [
        ((), 14, 12),  # 10 + Dex
        (("leather-armor",), 14, 13),  # 11 + Dex
        (("studded-leather-armor",), 14, 14),  # 12 + Dex
        (("chain-shirt",), 18, 15),  # 13 + Dex, capped at +2
        (("chain-shirt",), 8, 12),  # a Dex penalty still applies to light/medium armor
        (("chain-shirt", "shield"), 14, 17),  # ... + 2 for the shield
        (("chain-mail",), 18, 16),  # heavy: flat 16, Dexterity ignored
        (("chain-mail", "shield"), 8, 18),  # ...even a negative modifier
    ],
)
def test_armor_class_by_armor(owner, worn, dex, expected):
    c = build_character(owner, "fighter")
    set_scores(c, dex=dex)
    wear(c, *worn)

    assert derived_stats.compute(c).armor_class["value"] == expected


def test_unarmored_defense_barbarian_allows_a_shield_monk_does_not(owner):
    barbarian = build_character(owner, "barbarian")
    set_scores(barbarian, dex=14, con=16)
    wear(barbarian)
    assert derived_stats.compute(barbarian).armor_class["value"] == 10 + 2 + 3
    wear(barbarian, "shield")
    assert derived_stats.compute(barbarian).armor_class["value"] == 10 + 2 + 3 + 2

    monk = build_character(owner, "monk")
    set_scores(monk, dex=16, wis=14, con=10)
    wear(monk)
    assert derived_stats.compute(monk).armor_class["value"] == 10 + 3 + 2
    wear(monk, "shield")  # Unarmored Defense needs no armor *and* no shield: normal formula
    ac = derived_stats.compute(monk).armor_class
    assert (ac["value"], ac["formula"]) == (10 + 3 + 2, "unarmored")  # 10 + Dex + shield


def test_one_ac_calculation_at_a_time_takes_the_best(owner):
    barbarian = build_character(owner, "barbarian")
    set_scores(barbarian, dex=10, con=10)
    wear(barbarian, "leather-armor")  # 11 + 0 beats nothing: armor worn, so no Unarmored Defense
    assert derived_stats.compute(barbarian).armor_class["value"] == 11


def test_armor_warnings(owner):
    fighter = build_character(owner, "fighter")
    set_scores(fighter, str=10)
    wear(fighter, "chain-mail")
    stats = derived_stats.compute(fighter)
    assert "strength_requirement" in stats.warnings and stats.speed == 30 - 10
    assert "stealth_disadvantage" in stats.warnings

    wizard = build_character(owner, "wizard")  # no armor training at all
    wear(wizard, "chain-mail")
    assert "not_proficient:heavy" in derived_stats.compute(wizard).warnings


def test_weapon_attacks_use_the_right_ability_and_proficiency(owner):
    fighter = build_character(owner, "fighter")
    set_scores(fighter, str=16, dex=12)
    no_feats(fighter)  # set_scores re-derives the rows, so strip the feats after it
    wear(fighter, "greatsword", "longbow", "dagger")
    attacks = {a["equipment_id"]: a for a in derived_stats.compute(fighter).attacks}

    assert attacks["greatsword"]["attack_bonus"] == 3 + 2  # Str +3, proficient
    assert attacks["greatsword"]["damage"] == "2d6+3"
    assert attacks["longbow"]["ability"] == "dex" and attacks["longbow"]["attack_bonus"] == 1 + 2
    assert attacks["dagger"]["ability"] == "str"  # finesse picks the better one: Str +3 > Dex +1

    set_scores(fighter, str=8, dex=16)  # (recomputes the draft, so wear the items again)
    wear(fighter, "dagger")
    dagger = derived_stats.compute(fighter).attacks[0]
    assert dagger["ability"] == "dex"


def test_a_weapon_without_proficiency_gets_no_proficiency_bonus(owner):
    wizard = build_character(owner, "wizard")
    wear(wizard, "longsword", "dagger")  # a Wizard knows Simple weapons only
    attacks = {a["equipment_id"]: a for a in derived_stats.compute(wizard).attacks}
    assert attacks["longsword"]["proficient"] is False and attacks["dagger"]["proficient"] is True


def test_rogue_filtered_weapon_proficiency(owner):
    rogue = build_character(owner, "rogue")
    wear(rogue, "rapier", "longsword", "shortsword")
    attacks = {a["equipment_id"]: a for a in derived_stats.compute(rogue).attacks}
    # Martial weapons with Finesse or Light: rapier (finesse) and shortsword (finesse, light).
    assert attacks["rapier"]["proficient"] and attacks["shortsword"]["proficient"]
    assert not attacks["longsword"]["proficient"]


def test_spellcasting_save_dc_and_attack_bonus(owner):
    wizard = build_character(owner, "wizard")
    stats = derived_stats.compute(wizard)
    (casting,) = stats.spellcasting
    mod = stats.abilities["int"]["modifier"]

    assert casting["ability"] == "int"
    assert casting["save_dc"] == 8 + mod + 2 and casting["attack_bonus"] == mod + 2
    assert casting["slots"][:2] == [2, 0] and casting["cantrips"] == 3 and casting["prepared"] == 4

    warlock = derived_stats.compute(build_character(owner, "warlock"))
    assert warlock.spellcasting[0]["pact"] == {"slots": 1, "level": 1}
    assert not derived_stats.compute(build_character(owner, "fighter")).spellcasting


def test_thaumaturge_adds_wisdom_to_arcana_and_religion_but_protector_does_not(owner):
    cleric = build_character(owner, "cleric")
    set_scores(cleric, wis=16, int=10)
    class_choices.save(cleric, order="thaumaturge")
    stats = derived_stats.compute(cleric)
    assert stats.skills["arcana"]["bonus"] == 3 and stats.skills["religion"]["bonus"] == 3
    assert stats.skills["history"]["bonus"] == 0

    class_choices.save(cleric, order="protector")
    assert derived_stats.compute(cleric).skills["arcana"]["bonus"] == 0


def test_the_bonus_is_at_least_one(owner):
    druid = build_character(owner, "druid")
    class_choices.save(druid, order="magician")
    set_scores(druid, wis=8)
    assert derived_stats.compute(druid).skills["nature"]["bonus"] == 1


def test_lineage_speed_and_species_spell_ability(owner):
    elf = build_character(owner, "fighter", "soldier", "elf")
    origins.save_species_choices(elf, lineage="wood-elf", skill="perception")
    assert derived_stats.compute(elf).speed == 35

    sources = [s["source"] for s in derived_stats.compute(elf).spellcasting]
    assert "species" in sources  # the lineage's cantrip is cast with the ability the player chose
    assert Draft(elf).get("species.spell_ability") in ("int", "wis", "cha")


def test_manual_overrides_flow_through_to_the_numbers(owner):
    c = build_character(owner, "fighter")
    before = derived_stats.compute(c).armor_class["value"]
    set_scores(c, dex=30)
    no_feats(c)
    assert derived_stats.compute(c).initiative == 10
    creation.reset_manual(c)
    c.refresh_from_db()
    assert derived_stats.compute(c).armor_class["value"] == before


def no_feats(character):
    """The fixture fighter has a background feat and a Fighting Style; strip them so a test sees
    the bare formulas."""
    character.feats.all().delete()
    return character


def give_feat(character, name):
    character.feats.create(feat=Feat.objects.get(name_en=name), granted_at_level=1)


def test_defense_adds_one_ac_only_while_armored(owner):
    c = no_feats(build_character(owner, "fighter"))
    set_scores(c, dex=14)
    give_feat(c, "Defense")
    wear(c, "chain-shirt")
    assert derived_stats.compute(c).armor_class["value"] == 16  # 13 + Dex +2, + 1 Defense
    wear(c)
    assert derived_stats.compute(c).armor_class["value"] == 12  # no armor, no bonus


def test_medium_armor_master_raises_the_dex_cap(owner):
    c = no_feats(build_character(owner, "fighter"))
    set_scores(c, dex=18)
    give_feat(c, "Medium Armor Master")
    wear(c, "chain-shirt")
    assert derived_stats.compute(c).armor_class["value"] == 16  # 13 + Dex capped at +3


def test_archery_dueling_alert_and_speedy(owner):
    c = no_feats(build_character(owner, "fighter"))
    set_scores(c, str=16, dex=12)
    for feat in ("Archery", "Dueling", "Alert", "Speedy"):
        give_feat(c, feat)
    wear(c, "longsword", "greatsword", "longbow")
    stats = derived_stats.compute(c)
    attacks = {a["equipment_id"]: a for a in stats.attacks}
    assert attacks["longbow"]["attack_bonus"] == 1 + 2 + 2
    assert attacks["longsword"]["damage"] == "1d8+5"
    assert attacks["greatsword"]["damage"] == "2d6+3"  # two-handed: no Dueling
    assert stats.initiative == 1 + 2
    assert (
        stats.speed == derived_stats.compute(no_feats(build_character(owner, "fighter"))).speed + 10
    )


def test_armor_warnings_are_kept_per_worn_item(owner):
    c = no_feats(build_character(owner, "wizard"))
    wear(c, "chain-mail")
    stats = derived_stats.compute(c)
    assert "not_proficient:heavy" in stats.item_warnings["chain-mail"]
    assert "stealth_disadvantage" in stats.item_warnings["chain-mail"]


def test_boon_of_speed_adds_thirty_feet(owner):
    c = no_feats(build_character(owner, "fighter"))
    before = derived_stats.compute(c).speed
    give_feat(c, "Boon of Speed")
    assert derived_stats.compute(c).speed == before + 30


def test_a_worn_custom_armor_and_shield_count_for_armor_class(owner):
    from apps.characters.models import CharacterCustomItem

    fighter = build_character(owner, "fighter")
    set_scores(fighter, str=10, dex=14)
    no_feats(fighter)
    wear(fighter)  # nothing from the catalog
    CharacterCustomItem.objects.create(
        character=fighter,
        name="Dragonscale",
        section="armor",
        armor_kind="medium",
        ac=15,
        equipped=True,
    )
    CharacterCustomItem.objects.create(
        character=fighter,
        name="Oak buckler",
        section="armor",
        armor_kind="shield",
        ac=1,
        equipped=True,
    )
    ac = derived_stats.compute(fighter).armor_class
    assert ac["value"] == 15 + 2 + 1  # medium caps Dex at +2, plus the shield's bonus
    assert ac["armor_name"] == "Dragonscale" and ac["shield"]


def test_a_custom_weapon_attacks_and_a_versatile_one_has_two_damages(owner):
    from apps.characters.models import CharacterCustomItem

    fighter = build_character(owner, "fighter")
    set_scores(fighter, str=16, dex=12)
    no_feats(fighter)
    wear(fighter, "longsword")
    CharacterCustomItem.objects.create(
        character=fighter,
        name="Moonblade",
        section="weapons",
        weapon_category="martial",
        damage_dice="1d6",
        damage_type="slashing",
        finesse=True,
        equipped=True,
    )
    attacks = {a["equipment_id"]: a for a in derived_stats.compute(fighter).attacks}
    moon = next(a for k, a in attacks.items() if k.startswith("custom:"))
    assert moon["custom_name"] == "Moonblade" and moon["damage"] == "1d6+3"
    longsword = attacks["longsword"]
    assert longsword["damage"] == "1d8+3" and longsword["damage_two_handed"] == "1d10+3"
    assert not longsword["two_hands_free"]  # the Moonblade is wielded too


def test_versatile_two_hands_need_a_free_off_hand(owner):
    fighter = build_character(owner, "fighter")
    set_scores(fighter, str=16)
    no_feats(fighter)
    wear(fighter, "longsword")
    assert derived_stats.compute(fighter).attacks[0]["two_hands_free"]
    wear(fighter, "longsword", "shield")
    assert not derived_stats.compute(fighter).attacks[0]["two_hands_free"]
    wear(fighter, "mace")
    assert derived_stats.compute(fighter).attacks[0]["damage_two_handed"] == ""


def test_effects_of_worn_custom_items_and_custom_features_change_the_numbers(owner):
    from apps.characters.models import CharacterCustomFeature, CharacterCustomItem

    fighter = no_feats(build_character(owner, "fighter"))
    wear(fighter)
    set_scores(fighter, str=14, dex=10, wis=10)
    before = derived_stats.compute(fighter)
    ring = CharacterCustomItem.objects.create(
        character=fighter,
        name="Ring of the Fox",
        section="misc",
        effects=[
            {"target": "ac", "value": 1},
            {"target": "speed", "value": 10},
            {"target": "initiative", "value": 2},
            {"target": "passive_perception", "value": 5},
            {"target": "ability_min:str", "value": 19},
            {"target": "prof_skill:stealth", "value": 1},
            {"target": "save:wis", "value": 1},
            {"target": "skill_all", "value": 1},
        ],
    )
    # Not worn yet: nothing changes.
    assert derived_stats.compute(fighter).armor_class["value"] == before.armor_class["value"]
    ring.equipped = True
    ring.save()
    after = derived_stats.compute(fighter)
    assert after.armor_class["value"] == before.armor_class["value"] + 1
    assert after.speed == before.speed + 10
    assert after.initiative == before.initiative + 2
    assert after.abilities["str"]["score"] == 19 and after.abilities["str"]["modifier"] == 4
    stealth = after.skills["stealth"]
    assert stealth["state"] == "proficient"
    assert stealth["modifier"] == before.skills["stealth"]["modifier"] + after.proficiency_bonus + 1
    assert after.saving_throws["wis"]["modifier"] == before.saving_throws["wis"]["modifier"] + 1
    assert after.passive_perception == before.passive_perception + 5 + 1
    CharacterCustomFeature.objects.create(
        character=fighter, name="Blessed", effects=[{"target": "attack", "value": 1}]
    )
    assert derived_stats.compute(fighter).speed == before.speed + 10  # the feature adds, too


def test_a_custom_weapons_own_bonuses_apply_to_that_weapon_only(owner):
    from apps.characters.models import CharacterCustomItem

    fighter = no_feats(build_character(owner, "fighter"))
    set_scores(fighter, str=16)
    wear(fighter, "longsword")
    CharacterCustomItem.objects.create(
        character=fighter,
        name="Moonblade",
        section="weapons",
        weapon_category="martial",
        damage_dice="1d6",
        damage_type="slashing",
        equipped=True,
        effects=[
            {"target": "weapon_attack", "value": 2},
            {"target": "weapon_damage", "value": 2},
            {"target": "damage", "value": 1},
        ],
    )
    attacks = {a["equipment_id"]: a for a in derived_stats.compute(fighter).attacks}
    moon = next(a for k, a in attacks.items() if k.startswith("custom:"))
    assert moon["damage"] == "1d6+6"  # Str +3, its own +2 and the +1 to every damage roll
    assert attacks["longsword"]["damage"] == "1d8+4"  # only the general +1
