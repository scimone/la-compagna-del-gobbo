"""The SRD's level-1 rules, asserted on the rows the engine produces."""

import pytest

from apps.builder.services import abilities, class_choices, creation, effects, origins
from apps.builder.services.store import Draft
from apps.characters.models import CharacterInventoryItem
from apps.conftest import default_campaign

from .conftest import build_character, complete_species

pytestmark = pytest.mark.usefixtures("imported_rules")


def profs(character, category):
    return set(character.proficiencies.filter(category=category).values_list("name", flat=True))


def coins_cp(character):
    c = character.currency
    return c.copper + 10 * c.silver + 100 * c.gold


# --- proficiencies, hit points, gold -----------------------------------------------------------


def test_fighter_soldier_human(owner):
    c = build_character(owner, "fighter", "soldier", "human")

    assert profs(c, "saving_throw") == {"str", "con"}
    assert profs(c, "armor") == {"light", "medium", "heavy", "shield"}
    assert {"simple", "martial"} <= profs(c, "weapon")
    assert {"athletics", "intimidation"} <= profs(c, "skill")  # the Soldier's two
    assert len(profs(c, "skill")) == 2 + 2 + 1  # background + class picks + Human's Skillful
    assert c.max_hit_points == 11  # d10 + Con 13 (+1)
    assert coins_cp(c) == 400 + 1400  # Fighter A (4 gp) + Soldier A (14 gp)
    # Origin feat from the background, Human's extra Origin feat, and a Fighting Style feat.
    sources = dict(c.feats.values_list("source", "feat_id"))
    assert sources["background"] == "savage-attacker" and sources["species"] == "alert"
    assert c.feats.filter(source="class").exists()
    resources = dict(c.resources.values_list("name", "max_uses"))
    assert resources == {"Second Wind": 2}
    assert len(Draft(c).get("class.weapon_mastery")) == 3


def test_armor_is_worn_only_if_proficient_and_only_one_body_armor(owner):
    fighter = build_character(owner, "fighter")
    worn = fighter.inventory_items.filter(equipped=True).values_list("equipment_id", flat=True)
    assert list(worn) == ["chain-mail"]

    wizard = build_character(owner, "wizard")  # no armor at all
    assert not wizard.inventory_items.filter(equipped=True).exists()
    assert profs(wizard, "armor") == set()


def test_cleric_order_changes_proficiencies_and_cantrips(owner):
    cleric = build_character(owner, "cleric")
    # The helper takes the first option: Protector -> Martial weapons and Heavy armor.
    assert Draft(cleric).get("class.order") == "protector"
    assert "martial" in profs(cleric, "weapon") and "heavy" in profs(cleric, "armor")
    assert len(Draft(cleric).get("class.cantrips")) == 3

    assert not class_choices.save(cleric, order="thaumaturge") == []  # cantrips now short by one
    assert "heavy" not in profs(cleric, "armor") and "martial" not in profs(cleric, "weapon")
    picker = next(p for p in class_choices.pickers(Draft(cleric)) if p.key == "class.cantrips")
    assert picker.count == 4  # 3 + the Thaumaturge's extra cantrip
    protector_only = {f.feature.name for f in cleric.features.all()}
    assert "Thaumaturge" in protector_only and "Protector" not in protector_only


def test_wizard_spellbook_holds_six_and_four_are_prepared(owner):
    wizard = build_character(owner, "wizard")

    book = wizard.spells.filter(in_spellbook=True)
    assert book.count() == 6 and book.filter(prepared=True).count() == 4
    assert wizard.spells.filter(spell__level=0).count() == 3
    assert {s.klass_id for s in wizard.spells.all()} == {"wizard"}
    assert dict(wizard.resources.values_list("name", "max_uses")) == {"Arcane Recovery": 1}

    # A prepared spell must come from the book.
    outside = next(
        c[0]
        for c in next(
            p for p in class_choices.pickers(Draft(wizard)) if p.key == "class.spellbook"
        ).candidates
        if c[0] not in {s.spell_id for s in book}
    )
    picked = [*Draft(wizard).get("class.spells")[:3], outside]
    assert class_choices.save(wizard, spells=picked)


def test_ranger_and_druid_always_prepared_spells_dont_count_against_the_limit(owner):
    ranger = build_character(owner, "ranger")
    assert ranger.spells.get(spell_id="hunters-mark").always_prepared
    assert ranger.spells.filter(prepared=True).count() == 2 + 1  # 2 prepared + Hunter's Mark
    druid = build_character(owner, "druid")
    assert druid.spells.get(spell_id="speak-with-animals").always_prepared
    assert "druidic" in set(druid.languages.values_list("language_id", flat=True))


def test_rogue_expertise_only_on_held_skills_and_thieves_cant_plus_a_language(owner):
    rogue = build_character(owner, "rogue")

    expert = set(rogue.proficiencies.filter(level="expertise").values_list("name", flat=True))
    held = profs(rogue, "skill")
    assert len(expert) == 2 and expert <= held
    languages = set(rogue.languages.values_list("language_id", flat=True))
    assert {"common", "thieves-cant", "dwarvish", "elvish"} <= languages
    assert len(languages) == 5  # + the Rogue's one free language
    picker = next(p for p in class_choices.pickers(Draft(rogue)) if p.key == "class.expertise")
    assert picker.candidate_ids == held

    assert class_choices.save(rogue, expertise=["arcana", "history"])  # not proficient in these


def test_warlock_invocation_offers_only_level_one_options(owner):
    warlock = build_character(owner, "warlock")
    picker = next(p for p in class_choices.pickers(Draft(warlock)) if p.key == "class.invocations")

    assert picker.count == 1 and "agonizing-blast" not in picker.candidate_ids  # needs level 2
    assert "pact-of-the-blade" in picker.candidate_ids
    assert warlock.optional_features.count() == 1
    assert warlock.spells.filter(spell__level=0).count() == 2


def test_barbarian_masteries_are_melee_and_rage_uses_come_from_the_table(owner):
    barbarian = build_character(owner, "barbarian")
    masteries = Draft(barbarian).get("class.weapon_mastery")
    from apps.rules.models import Equipment

    assert len(masteries) == 2
    assert {Equipment.objects.get(id=m).type_id for m in masteries} == {"m"}
    assert dict(barbarian.resources.values_list("name", "max_uses")) == {"Rage": 2}
    assert barbarian.max_hit_points == 12 + (barbarian.constitution - 10) // 2


def test_bard_bardic_inspiration_uses_equal_charisma_modifier(owner):
    bard = build_character(owner, "bard")
    modifier = (bard.charisma - 10) // 2
    assert dict(bard.resources.values_list("name", "max_uses")) == {
        "Bardic Inspiration": max(1, modifier)
    }
    assert len(profs(bard, "tool")) >= 3  # three instruments


# --- packs -------------------------------------------------------------------------------------


def test_starting_packs_are_individual_items_traceable_to_their_pack(owner):
    fighter = build_character(owner, "fighter")

    pack = fighter.inventory_items.get(equipment_id="dungeoneers-pack")
    contents = pack.contents.all()
    assert contents.count() == 9
    assert all(i.character_id == fighter.id and i.parent_id == pack.id for i in contents)
    # The contents are ordinary rows: individually usable, findable without going through the pack.
    assert fighter.inventory_items.filter(equipment_id="rope").exists()
    assert CharacterInventoryItem.objects.filter(character=fighter, parent__isnull=True).count() > 1

    # Choosing the gold option instead gives no items and the lump sum.
    origins.save_equipment(fighter, class_option="C", background_option="B")
    fighter.refresh_from_db()
    assert not fighter.inventory_items.exists()
    assert coins_cp(fighter) == 15500 + 5000


# --- species -----------------------------------------------------------------------------------


def test_lineages_change_speed_darkvision_and_spells(owner):
    drow = build_character(owner, "fighter", "soldier", "elf")  # first lineage in the data
    key = Draft(drow).get("species.lineage")
    lineage = next(lin for lin in Draft(drow).species.lineages if lin["key"] == key)
    sense = drow.senses.get(sense_id="darkvision")
    assert sense.range_feet == lineage.get("darkvision", 60)
    assert drow.spells.filter(source="species:elf").exists()  # the lineage's cantrip

    complete_species(drow, "elf")
    assert not origins.save_species_choices(drow, lineage="wood-elf", skill="perception")
    from apps.builder.resolvers import species as species_resolver

    assert species_resolver.speed(Draft(drow)) == 35
    assert drow.senses.get(sense_id="darkvision").range_feet == 60
    # The chosen lineage is its own feature, replacing the generic trait that lists them all.
    names = set(drow.features.values_list("feature__name_en", flat=True))
    assert "Elven Lineage (Wood Elf)" in names
    assert "Elven Lineage" not in names and "Elven Lineage (Drow)" not in names


def test_species_with_two_sizes_must_pick_one(owner):
    c = build_character(owner, "fighter")
    origins.select_species(c, "human")
    assert any(i.path == "species.size" for i in origins.species_issues(Draft(c)))
    origins.save_species_choices(c, size="S")
    c.refresh_from_db()
    assert c.size == "S"


def test_aasimar_gets_light_and_dwarf_resists_poison(owner):
    aasimar = build_character(owner, "fighter", species_id="aasimar")
    assert aasimar.spells.filter(spell_id="light").exists()
    dwarf = build_character(owner, "fighter", species_id="dwarf")
    from apps.builder.resolvers import species as species_resolver

    assert species_resolver.resistances(Draft(dwarf)) == ["poison"]


def test_acolyte_magic_initiate_is_the_cleric_list(owner):
    c = build_character(owner, "fighter", "acolyte")
    cantrips = c.spells.filter(source="feat:magic-initiate", spell__level=0)
    assert cantrips.count() == 2
    for row in c.spells.filter(source="feat:magic-initiate"):
        assert "Cleric" in row.spell.classes
    assert (
        c.spells.filter(source="feat:magic-initiate", spell__level=1, always_prepared=True).count()
        == 1
    )


# --- no duplicates (D6) --------------------------------------------------------------------------


def test_a_skill_the_background_gave_is_not_offered_again(owner):
    c = build_character(owner, "fighter", "soldier")
    picker = next(p for p in class_choices.pickers(Draft(c)) if p.key == "class.skills")
    assert not picker.candidate_ids & {"athletics", "intimidation"}
    assert class_choices.save(c, skills=["athletics", "acrobatics"])  # rejected: already held


def test_changing_the_background_drops_a_class_pick_it_now_duplicates(owner):
    """The class (and its picks) can be answered before the background. When a later background
    already grants a picked skill, the pick is removed - never kept as a duplicate - and the class
    step shows that skill as still to choose."""
    from apps.rules.models import Background

    c = build_character(owner, "fighter", "soldier")
    picked = set(Draft(c).get("class.skills"))
    other = next(b for b in Background.objects.all() if picked & {s.id for s in b.skills.all()})
    clash = picked & {s.id for s in other.skills.all()}

    origins.select_background(c, other.id)

    remaining = set(Draft(c).get("class.skills"))
    assert not remaining & clash and remaining <= picked  # the clashing pick is gone, the rest stay
    assert any(
        i.step == "class" and i.path == "class.skills" for i in class_choices.issues(Draft(c))
    )
    held = set(c.proficiencies.filter(category="skill").values_list("name", flat=True))
    assert clash <= held  # ...and the background still gives it exactly once
    assert c.proficiencies.filter(category="skill").count() == len(held)


def test_a_valid_incomplete_selection_is_left_alone_by_pruning(owner):
    from apps.builder.services import prune

    c = build_character(owner, "wizard")
    class_choices.save(c, cantrips=["fire-bolt"])  # 1 of 3: incomplete but valid

    assert prune.run(c) is False
    assert Draft(c).get("class.cantrips") == ["fire-bolt"]


def test_prepared_spells_are_pruned_when_the_spellbook_no_longer_holds_them(owner):
    wizard = build_character(owner, "wizard")
    book = Draft(wizard).get("class.spellbook")
    prepared = Draft(wizard).get("class.spells")
    dropped = prepared[0]

    class_choices.save(wizard, spellbook=[s for s in book if s != dropped])

    assert dropped not in Draft(wizard).get("class.spells")


def test_languages_are_two_distinct_standard_languages(owner):
    c = creation.start_draft(owner, "x", default_campaign())
    assert origins.save_languages(c, ["elvish"])  # too few
    assert origins.save_languages(c, ["elvish", "elvish"])  # duplicate
    assert origins.save_languages(c, ["elvish", "abyssal"])  # rare, not allowed at creation
    assert not origins.save_languages(c, ["elvish", "goblin"])
    rolled = origins.roll_languages(c)
    assert rolled == ["elvish", "goblin"]  # keeps what was picked, rolls only the missing


def test_roll_languages_fills_two_distinct_standard_languages(owner):
    c = creation.start_draft(owner, "x", default_campaign())
    rolled = origins.roll_languages(c)
    assert len(set(rolled)) == 2 and not origins.languages_issues(Draft(c))


# --- abilities ---------------------------------------------------------------------------------


def _setup(owner):
    c = creation.start_draft(owner, "x", default_campaign())
    origins.select_class(c, "fighter")
    origins.select_background(c, "soldier")  # raises str/dex/con
    return c


def test_standard_array_and_point_buy_and_bonus_rules(owner):
    c = _setup(owner)
    base = {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8}
    assert not abilities.save(c, method="standard", base=base, bonus={"str": 2, "dex": 1})
    assert not abilities.save(c, method="standard", base=base, bonus={"str": 1, "dex": 1, "con": 1})
    assert abilities.save(c, method="standard", base=base, bonus={"int": 2, "wis": 1})  # not listed
    assert abilities.save(c, method="standard", base=base, bonus={"str": 3})  # not a spread
    assert abilities.save(
        c, method="standard", base={**base, "cha": 15}, bonus={"str": 2, "dex": 1}
    )

    points = {"str": 15, "dex": 15, "con": 15, "int": 8, "wis": 8, "cha": 8}  # 27 exactly
    assert not abilities.save(c, method="pointbuy", base=points, bonus={"str": 2, "dex": 1})
    assert abilities.save(
        c, method="pointbuy", base={**points, "int": 9}, bonus={"str": 2, "dex": 1}
    )
    assert abilities.save(
        c, method="pointbuy", base={**points, "str": 16}, bonus={"str": 2, "dex": 1}
    )


def test_a_roll_is_made_once_and_the_cap_of_twenty_is_exactly_reachable(owner):
    c = _setup(owner)
    rolled = abilities.roll_scores(c)
    assert len(rolled) == 6 and all(3 <= r <= 18 for r in rolled)
    assert abilities.roll_scores(c) == rolled  # one roll per character (D7)

    # Pin the roll so the test is deterministic: 18 + 2 = 20 is allowed, 18 + 3 would not be.
    from apps.builder.services.store import set_choice

    set_choice(c, "abilities", {"rolled": [18, 14, 13, 12, 10, 8]})
    base = {"str": 18, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8}
    assert not abilities.save(c, method="roll", base=base, bonus={"str": 2, "dex": 1})
    c.refresh_from_db()
    assert c.strength == 20
    # 19 is not a value any method can produce, but the cap is enforced independently of that.
    problems = abilities.save(
        c, method="roll", base={**base, "str": 19}, bonus={"str": 2, "dex": 1}
    )
    assert {i.code for i in problems} >= {"not_rolled", "over_cap"}


def test_roll_method_rejects_numbers_that_werent_rolled(owner):
    c = _setup(owner)
    abilities.roll_scores(c)
    problems = abilities.save(
        c,
        method="roll",
        base=dict.fromkeys(["str", "dex", "con", "int", "wis", "cha"], 18),
        bonus={"str": 2, "dex": 1},
    )
    assert any(i.code == "not_rolled" for i in problems)


# --- manual override (final layer) ---------------------------------------------------------------


def test_manual_ability_scores_override_everything_and_survive_recomputes(owner):
    c = build_character(owner, "fighter")
    generated_str = c.strength

    # Keys are ability ids (`str`), not `Character` field names.
    assert creation.set_manual_abilities(c, {"strength": 30})
    assert not creation.set_manual_abilities(c, {"str": 30, "cha": 1})
    c.refresh_from_db()
    assert (c.strength, c.charisma) == (30, 1) and generated_str != 30
    effects.apply(c)  # e.g. the player goes back and changes something
    c.refresh_from_db()
    assert (c.strength, c.charisma) == (30, 1)
    totals = {}
    for row in c.ability_score_increases.all():
        totals[row.ability] = totals.get(row.ability, 0) + row.amount
    assert totals["strength"] == 30 and totals["charisma"] == 1  # invariant still holds
    assert c.max_hit_points == 10 + (c.constitution - 10) // 2

    assert creation.set_manual_abilities(c, {"str": 31})  # outside 1-30
    assert creation.set_manual_abilities(c, {"luck": 10})

    creation.reset_manual(c)
    c.refresh_from_db()
    assert c.strength == generated_str


def test_manual_skills_can_add_remove_and_grant_expertise_regardless_of_class(owner):
    c = build_character(owner, "fighter")
    assert "arcana" not in profs(c, "skill")

    assert not creation.set_manual_skills(
        c, {"arcana": "expertise", "athletics": "none", "history": "proficient"}
    )
    proficiencies = dict(c.proficiencies.filter(category="skill").values_list("name", "level"))
    assert proficiencies["arcana"] == "expertise" and proficiencies["history"] == "proficient"
    assert "athletics" not in proficiencies  # the Soldier's skill, removed by hand
    effects.apply(c)
    assert (
        dict(c.proficiencies.filter(category="skill").values_list("name", "level")) == proficiencies
    )

    assert creation.set_manual_skills(c, {"basketweaving": "proficient"})
    assert creation.set_manual_skills(c, {"arcana": "master"})


def test_a_finished_character_is_no_longer_recomputed(owner):
    c = build_character(owner, "fighter")
    creation.finalize(c)
    before = c.proficiencies.count()

    creation.set_manual_skills(c, {"arcana": "expertise"})  # writes the choice...
    effects.apply(c)  # ...but nothing is rebuilt for a complete character

    assert c.proficiencies.count() == before


# --- overrides only where they differ; method switching; access ---


def test_untouched_skills_keep_following_the_rules_only_real_edits_are_overrides(owner):
    c = build_character(owner, "fighter", "soldier")
    # Submit the whole skill list unchanged plus one real edit, exactly as the Review form does.
    from apps.rules.models import Skill

    states = {
        s.id: dict(c.proficiencies.filter(category="skill").values_list("name", "level")).get(
            s.id, "none"
        )
        for s in Skill.objects.all()
    }
    states["arcana"] = "expertise"
    assert not creation.set_manual_skills(c, states)
    assert Draft(c).get("manual.skills") == {"arcana": "expertise"}  # nothing else is "manual"

    # Change the background: the Soldier's skills go away and the new background's come in,
    # while the manual edit stays.
    origins.select_background(c, "criminal")
    skills = dict(c.proficiencies.filter(category="skill").values_list("name", "level"))
    assert "athletics" not in skills or skills["athletics"] == "proficient"  # a class pick maybe
    assert {"sleight-of-hand", "stealth"} <= set(skills)
    assert skills["arcana"] == "expertise"


def test_switching_the_ability_method_keeps_the_roll_and_bonus_but_drops_the_old_numbers(owner):
    c = _setup(owner)
    rolled = abilities.roll_scores(c)
    base = {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8}
    abilities.save(c, method="standard", base=base, bonus={"str": 2, "dex": 1})

    abilities.set_method(c, "pointbuy")
    state = Draft(c).get("abilities")
    assert state["method"] == "pointbuy" and "base" not in state
    assert state["rolled"] == rolled and state["bonus"] == {"str": 2, "dex": 1}

    abilities.set_method(c, "nonsense")  # ignored
    assert Draft(c).get("abilities")["method"] == "pointbuy"


def test_suggested_array_matches_the_srd_table_for_the_class(owner):
    from apps.builder.tables import STANDARD_ARRAY_BY_CLASS

    c = _setup(owner)
    abilities.suggest_standard_array(c)
    assert Draft(c).get("abilities")["base"] == STANDARD_ARRAY_BY_CLASS["fighter"]


def test_who_may_view_and_edit(owner, db):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import AnonymousUser

    from apps.characters.models import Character
    from apps.characters.services import access

    other = get_user_model().objects.create_user("bob")
    mine = Character.objects.create(name="a", owner=owner, status=Character.STATUS_COMPLETE)
    draft = Character.objects.create(name="b", owner=owner, status=Character.STATUS_DRAFT)
    ownerless = Character.objects.create(name="c")

    for viewer in (owner, other):  # every member of the campaign sees every finished character
        assert access.can_view(viewer, mine) and access.can_view(viewer, ownerless)
    assert not access.can_view(AnonymousUser(), mine)
    assert access.can_view(owner, draft) and not access.can_view(other, draft)
    assert not access.can_view(AnonymousUser(), draft)
    assert access.can_edit(owner, mine) and not access.can_edit(other, mine)
    assert not access.can_edit(AnonymousUser(), mine) and not access.can_edit(owner, ownerless)
