"""Levelling up: every class from level 1 to 20, multiclassing, and the individual rules."""

import pytest

from apps.builder.services import creation, derived_stats, progression
from apps.builder.tests.conftest import build_character
from apps.characters.models import Character, CharacterClass, CharacterFeat, CharacterResource

pytestmark = pytest.mark.usefixtures("imported_rules")

CLASS_IDS = (
    "barbarian bard cleric druid fighter monk paladin ranger rogue sorcerer warlock wizard".split()
)


def finished(owner, class_id, **kwargs):
    character = build_character(owner, class_id, **kwargs)
    creation.finalize(character)
    character.refresh_from_db()
    return character


def autofill(character, class_id, values=None, *, prefer=None):
    """Fill every picker of the next level with its first valid candidates, until the plan is
    ready. `prefer` maps picker key -> the value to use (e.g. a subclass)."""
    values = dict(values or {})
    prefer = prefer or {}
    for _round in range(8):
        plan = progression.plan(character, class_id, values)
        for picker in plan.pickers:
            if picker.key in prefer:
                values[picker.key] = list(prefer[picker.key])
            elif picker.optional:
                continue
            else:
                values[picker.key] = [c[0] for c in picker.candidates][: picker.count]
        values.setdefault("lu.hp_mode", ["fixed"])
        plan = progression.plan(character, class_id, values)
        if plan.ready:
            return values
    raise AssertionError([i.message for i in plan.issues])


def level_up(character, class_id, **kwargs):
    values = autofill(character, class_id, **kwargs)
    progression.commit(character, class_id, values)
    character.refresh_from_db()
    return values


@pytest.mark.parametrize("class_id", CLASS_IDS)
def test_every_class_levels_from_1_to_20(owner, class_id):
    character = finished(owner, class_id)
    first_hp = character.max_hit_points
    for target in range(2, 21):
        level_up(character, class_id)
        assert progression.total_level(character) == target
    row = CharacterClass.objects.get(character=character, klass_id=class_id)
    assert row.level == 20 and row.subclass_id is not None
    assert character.max_hit_points > first_hp + 19  # every level added at least 1
    assert character.experience_points >= 355_000
    assert not progression.can_level_up(character)
    derived_stats.compute(character)  # the sheet's numbers still compute


def test_a_subclass_is_asked_for_at_level_3_and_its_features_arrive(owner):
    character = finished(owner, "cleric")
    level_up(character, "cleric")
    plan = progression.plan(character, "cleric")
    assert "lu.subclass" in [p.key for p in plan.pickers]
    assert not plan.ready
    values = autofill(character, "cleric")
    progression.commit(character, "cleric", values)
    names = set(character.features.values_list("feature__name", flat=True))
    assert "Life Domain Spells" in names or any("Domain Spells" in n for n in names)
    assert character.spells.filter(always_prepared=True, source__startswith="subclass:").exists()


def test_hit_points_average_or_roll_with_constitution(owner):
    character = finished(owner, "fighter")  # d10, Con 13 (+1)
    before = character.max_hit_points
    values = autofill(character, "fighter")
    plan = progression.plan(character, "fighter", values)
    assert plan.hp["fixed"] == 6 and plan.hp["gain"] == 7  # 6 + Con 1
    progression.commit(character, "fighter", values)
    character.refresh_from_db()
    assert character.max_hit_points == before + 7
    assert character.current_hit_points >= before + 7 - 1

    values = autofill(character, "fighter", {"lu.hp_mode": ["roll"], "lu.hp_roll": ["3"]})
    assert progression.plan(character, "fighter", values).hp["gain"] == 4
    values["lu.hp_roll"] = ["11"]  # above the d10
    assert not progression.plan(character, "fighter", values).ready


def test_ability_score_improvement_at_level_4_is_capped_and_raises_hit_points(owner):
    character = finished(owner, "barbarian")  # Con 13
    character.constitution = 15
    character.save()
    for _ in range(2):  # now level 3: the next one is the Ability Score Improvement
        level_up(character, "barbarian")
    plan = progression.plan(character, "barbarian")
    assert "lu.feat" in [p.key for p in plan.pickers]
    con_before, hp_before = character.constitution, character.max_hit_points
    values = autofill(
        character,
        "barbarian",
        prefer={
            "lu.feat": ["ability-score-improvement"],
            "lu.feat.asi_mode": ["plus2"],
            "lu.feat.asi_plus2": ["con"],
        },
    )
    progression.commit(character, "barbarian", values)
    character.refresh_from_db()
    assert character.constitution == con_before + 2 == 17
    # Con 15 -> 17: +1 per earlier level (3) on top of the new level's own gain
    assert character.max_hit_points > hp_before + 3
    assert character.feats.filter(feat_id="ability-score-improvement").exists()
    assert character.ability_score_increases.filter(ability="constitution", amount=2).exists()


def test_a_score_never_passes_20(owner):
    character = finished(owner, "fighter")
    character.strength = 19
    character.save()
    for _ in range(2):
        level_up(character, "fighter")
    plan = progression.plan(
        character,
        "fighter",
        {"lu.feat": ["ability-score-improvement"], "lu.feat.asi_mode": ["plus2"]},
    )
    asi = next(p for p in plan.pickers if p.key == "lu.feat.asi_plus2")
    assert "str" not in [c[0] for c in asi.candidates]  # 19 + 2 would be 21


def test_a_feat_needs_its_prerequisites(owner):
    character = finished(owner, "wizard")  # Str 8: no Great Weapon Master
    for _ in range(2):
        level_up(character, "wizard")
    plan = progression.plan(character, "wizard")
    feats = next(p for p in plan.pickers if p.key == "lu.feat")
    ids = [c[0] for c in feats.candidates]
    assert "ability-score-improvement" in ids and "great-weapon-master" not in ids


def test_multiclassing_needs_13_in_both_primary_abilities(owner):
    character = finished(owner, "fighter")  # Str 15 or Dex 14 - Int 8, Wis 10
    options = {o["klass"].id: o for o in progression.class_options(character)}
    assert options["barbarian"]["allowed"]  # Str 15
    assert not options["wizard"]["allowed"] and "Wizard" in options["wizard"]["reason"]
    with pytest.raises(ValueError):
        progression.plan(character, "wizard")


def test_multiclass_entry_gives_the_multiclass_proficiencies_and_hit_die(owner):
    character = finished(owner, "fighter")
    character.constitution = 13
    character.save()
    level_up(character, "barbarian")
    assert progression.total_level(character) == 2
    row = CharacterClass.objects.get(character=character, klass_id="barbarian")
    assert row.level == 1 and not row.is_starting_class
    held = set(character.proficiencies.values_list("category", "name"))
    assert ("armor", "shield") in held and ("weapon", "martial") in held
    assert "Rage" in set(character.resources.values_list("name", flat=True))
    dice = derived_stats.compute(character).hit_dice
    assert dice["d10"]["total"] == 1 and dice["d12"]["total"] == 1


def test_multiclass_caster_slots_combine(owner):
    character = finished(owner, "cleric")
    character.charisma = 14
    character.save()
    # Cleric primary Wis 15 (+bg) and Paladin Str/Cha 13
    character.strength = 14
    character.save()
    level_up(character, "paladin")
    from apps.frontend import character_sheet

    classes = list(character.classes.select_related("klass"))
    stats = derived_stats.compute(character)
    slots, _pact = character_sheet._slot_maximums(stats, classes)
    assert slots[0] >= 2


def test_class_resources_grow_with_the_level(owner):
    character = finished(owner, "fighter")
    level_up(character, "fighter")  # level 2: Action Surge
    names = {r.name: r for r in character.resources.all()}
    assert names["Action Surge"].max_uses == 1 and names["Second Wind"].max_uses == 2
    for _ in range(15):
        level_up(character, "fighter")
    names = {r.name: r for r in character.resources.all()}
    assert names["Action Surge"].max_uses == 2 and names["Indomitable"].max_uses == 3


def test_wizard_gains_two_spellbook_spells_and_cantrips_by_the_table(owner):
    character = finished(owner, "wizard")
    book_before = character.spells.filter(in_spellbook=True).count()
    level_up(character, "wizard")
    assert character.spells.filter(in_spellbook=True).count() == book_before + 2


def test_a_level_up_that_is_not_ready_changes_nothing(owner):
    character = finished(owner, "fighter")
    with pytest.raises(ValueError):
        progression.commit(character, "fighter", {"lu.hp_mode": ["roll"]})
    character.refresh_from_db()
    assert progression.total_level(character) == 1


def test_only_a_finished_character_below_20_can_level_up(owner):
    draft = creation.start_draft(owner, "Draft")
    assert not progression.can_level_up(draft)
    rogue = finished(owner, "rogue")
    assert not progression.can_level_up(rogue)  # the XP are not full
    rogue.experience_points = 300
    assert progression.can_level_up(rogue)
    rogue.experience_points = 10**6
    rogue.classes.update(level=20)
    assert not progression.can_level_up(rogue)


def test_tough_adds_two_hit_points_a_level(owner):
    character = finished(owner, "fighter")
    CharacterFeat.objects.create(character=character, feat_id="tough", granted_at_level=1)
    values = autofill(character, "fighter")
    assert progression.plan(character, "fighter", values).hp["gain"] == 6 + 1 + 2
    assert Character.objects.filter(pk=character.pk).exists() and CharacterResource is not None
