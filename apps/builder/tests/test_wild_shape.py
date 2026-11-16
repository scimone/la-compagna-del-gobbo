"""The Druid's Wild Shape forms: chosen at the level, replaced after a Long Rest."""

import pytest
from django.contrib.auth import get_user_model

from apps.builder.services import creation, progression, wild_shape
from apps.builder.tests.conftest import build_character
from apps.characters.services import play
from apps.rules.models import Creature

pytestmark = pytest.mark.usefixtures("imported_rules")

FOUR = ["wolf", "rat", "spider", "riding-horse"]


@pytest.fixture
def druid(db):
    owner = get_user_model().objects.create_user("dru")
    character = build_character(owner, "druid", "soldier")
    creation.finalize(character)
    character.refresh_from_db()
    return character


def filled(character, **values):
    """`values` plus the first candidates for every other pick the level asks for."""
    for _round in range(3):
        for picker in progression.plan(character, "druid", values).pickers:
            if picker.key not in values and not picker.optional:
                values[picker.key] = [c[0] for c in picker.candidates[: picker.count]]
    return values


def test_the_creatures_were_imported(db):
    assert Creature.objects.count() == 51
    wolf = Creature.objects.get(pk="wolf")
    assert (wolf.cr, wolf.ac, wolf.hp_average, wolf.speed) == ("1/4", 12, 11, {"walk": 40})
    assert wolf.abilities["dex"] == {"score": 15, "mod": 2}
    assert [a["name"] for a in wolf.traits] == ["Pack Tactics"]


def test_eligible_forms_follow_the_beast_shapes_table(db):
    at2 = {c.pk for c in wild_shape.eligible(2)}
    assert {"wolf", "rat", "spider", "riding-horse"} <= at2
    assert "bat" not in at2 and "giant-spider" not in at2  # a Fly Speed / above CR 1/4
    assert "imp" not in at2 and "zombie" not in at2  # not Beasts
    at4 = {c.pk for c in wild_shape.eligible(4)}
    assert "black-bear" in at4 and "bat" not in at4  # CR 1/2, still no flying
    at8 = {c.pk for c in wild_shape.eligible(8)}
    assert {"bat", "hawk", "giant-spider", "lion"} <= at8 and "imp" not in at8
    assert wild_shape.shapes_at(1) is None
    assert [wild_shape.shapes_at(n)[0] for n in (2, 3, 4, 7, 8, 20)] == [4, 4, 6, 6, 8, 8]


def test_levelling_to_two_asks_for_four_beasts(druid):
    druid.experience_points = 300
    druid.save()
    plan = progression.plan(druid, "druid", {})
    picker = next(p for p in plan.pickers if p.key == "lu.wild_shape")
    assert picker.count == 4 and picker.kind == "creature"
    assert "wolf" in picker.candidate_ids and "bat" not in picker.candidate_ids
    assert not plan.ready

    values = filled(druid, **{"lu.wild_shape": FOUR})
    plan = progression.plan(druid, "druid", values)
    assert not [i for i in plan.issues if i.path == "lu.wild_shape"]
    # Not Beasts, flyers and too-strong ones are refused.
    bad = progression.plan(
        druid, "druid", {**values, "lu.wild_shape": ["wolf", "rat", "spider", "imp"]}
    )
    assert any(i.path == "lu.wild_shape" for i in bad.issues)

    progression.commit(druid, "druid", {**values})
    assert wild_shape.known_ids(druid) == FOUR
    assert wild_shape.needed(druid) == 0


def test_a_long_rest_lets_one_form_be_replaced(druid):
    druid.classes.update(level=2)
    wild_shape.add_forms(druid, FOUR)
    assert wild_shape.swap_options(druid) is None

    play.long_rest(druid)
    druid.refresh_from_db()
    options = wild_shape.swap_options(druid)
    assert {c.pk for c in options["known"]} == set(FOUR)
    assert "wolf" not in {c.pk for c in options["candidates"]} and "boar" in {
        c.pk for c in options["candidates"]
    }

    with pytest.raises(ValueError):
        wild_shape.swap_form(druid, "wolf", "bat")  # flies: not before level 8
    with pytest.raises(ValueError):
        wild_shape.swap_form(druid, "boar", "cat")  # boar is not known
    wild_shape.swap_form(druid, "wolf", "boar")
    assert set(wild_shape.known_ids(druid)) == {"boar", "rat", "spider", "riding-horse"}
    druid.refresh_from_db()
    assert wild_shape.swap_options(druid) is None  # one replacement per Long Rest
    with pytest.raises(ValueError):
        wild_shape.swap_form(druid, "rat", "cat")


def test_a_druid_who_levelled_before_forms_were_tracked_can_catch_up(druid):
    druid.classes.update(level=4)
    assert wild_shape.needed(druid) == 6
    with pytest.raises(ValueError):
        wild_shape.add_forms(druid, FOUR + ["boar", "black-bear", "ape"])  # one too many
    wild_shape.add_forms(druid, FOUR + ["black-bear"])
    assert wild_shape.needed(druid) == 1
    with pytest.raises(ValueError):
        wild_shape.add_forms(druid, ["wolf"])  # already known
