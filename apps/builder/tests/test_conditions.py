import pytest

from apps.builder.services import derived_stats
from apps.characters import conditions
from apps.characters.services import play

from .conftest import build_character

pytestmark = pytest.mark.usefixtures("imported_rules")


def test_a_condition_applies_the_ones_it_implies(owner):
    character = build_character(owner, "fighter")
    play.set_condition(character, "paralyzed", True)
    assert conditions.active(character) == {"paralyzed", "incapacitated"}
    play.set_condition(character, "unconscious", True)
    assert conditions.active(character) == {"paralyzed", "unconscious", "prone", "incapacitated"}
    play.set_condition(character, "paralyzed", False)
    play.set_condition(character, "unconscious", False)
    assert conditions.active(character) == {"prone"}  # Unconscious left Prone behind
    play.set_condition(character, "prone", False)
    assert conditions.active(character) == set()
    with pytest.raises(ValueError):
        play.set_condition(character, "nonsense", True)


def test_the_code_and_the_imported_text_cover_the_same_conditions(db):
    from apps.rules.models import Condition

    rows = Condition.objects.filter(kind="condition").values_list("pk", flat=True)
    assert set(rows) == {*conditions.BY_ID, conditions.EXHAUSTION_ID}
    assert set(Condition.objects.filter(kind="status").values_list("pk", flat=True)) == {
        "bloodied",
        "concentration",
        "surprised",
    }


def test_dropping_to_zero_hit_points_stores_unconscious_and_healing_ends_it_but_not_prone(owner):
    character = build_character(owner, "fighter")
    play.set_hit_points(character, 0)
    assert {"unconscious", "prone"} <= set(character.conditions)
    assert {"unconscious", "prone", "incapacitated"} <= conditions.active(character)

    play.adjust_hit_points(character, 3)
    assert "unconscious" not in character.conditions
    assert "prone" in character.conditions  # "When this condition ends, you remain Prone."
    assert conditions.active(character) == {"prone"}


def test_putting_unconscious_on_by_hand_also_keeps_prone_when_it_ends(owner):
    character = build_character(owner, "fighter")
    play.set_condition(character, "unconscious", True)
    play.set_condition(character, "unconscious", False)
    assert character.conditions == ["prone"]


def test_bloodied_is_half_the_hit_points_or_fewer(owner):
    character = build_character(owner, "fighter")
    assert not conditions.bloodied(character)
    play.set_hit_points(character, character.hit_point_maximum // 2)
    assert conditions.bloodied(character)
    play.set_hit_points(character, 0)
    assert not conditions.bloodied(character)  # down, not Bloodied


def test_conditions_set_the_speed_and_exhaustion_lowers_everything_it_touches(owner):
    character = build_character(owner, "fighter")
    plain = derived_stats.compute(character)
    play.set_exhaustion(character, 2)
    tired = derived_stats.compute(character)
    assert tired.speed == plain.speed - 10
    assert tired.initiative == plain.initiative - 4
    assert tired.saving_throws["dex"]["modifier"] == plain.saving_throws["dex"]["modifier"] - 4
    assert tired.skills["stealth"]["modifier"] == plain.skills["stealth"]["modifier"] - 4
    play.set_condition(character, "restrained", True)
    assert derived_stats.compute(character).speed == 0
    play.set_exhaustion(character, 9)
    assert character.exhaustion == conditions.EXHAUSTION_MAX


def test_a_long_rest_removes_one_level_of_exhaustion(owner):
    character = build_character(owner, "fighter")
    play.set_exhaustion(character, 3)
    play.long_rest(character)
    assert character.exhaustion == 2


def test_the_summary_says_advantage_and_disadvantage_cancel(owner):
    character = build_character(owner, "fighter")
    play.set_condition(character, "invisible", True)
    play.set_condition(character, "poisoned", True)
    lines = [str(line) for line in conditions.summary(character)]
    assert "Your attack rolls: Advantage and Disadvantage cancel out" in lines
    assert "Disadvantage on ability checks" in lines
