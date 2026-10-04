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
    assert conditions.active(character) == set()
    with pytest.raises(ValueError):
        play.set_condition(character, "nonsense", True)


def test_zero_hit_points_means_unconscious(owner):
    character = build_character(owner, "fighter")
    character.current_hit_points = 0
    assert {"unconscious", "prone", "incapacitated"} <= conditions.active(character)
    fx = conditions.effects(character)
    assert fx.speed_zero and fx.incapacitated and "advantage" in fx.attacks_against


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
