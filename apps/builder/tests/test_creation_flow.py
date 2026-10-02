"""Every class through the full level-1 flow, checked against the SRD's rules."""

import pytest

from apps.builder.services import creation
from apps.builder.services.store import Draft
from apps.characters.models import Character
from apps.rules.models import Class

from .conftest import build_character

pytestmark = pytest.mark.usefixtures("imported_rules")

CLASS_IDS = [
    "barbarian",
    "bard",
    "cleric",
    "druid",
    "fighter",
    "monk",
    "paladin",
    "ranger",
    "rogue",
    "sorcerer",
    "warlock",
    "wizard",
]


@pytest.mark.parametrize("class_id", CLASS_IDS)
def test_every_class_can_be_created_and_finished(owner, class_id):
    character = build_character(owner, class_id)

    state = creation.get_state(character)
    assert state["ready"], [s for s in state["steps"] if s["issues"]]
    assert creation.finalize(character) == []

    character.refresh_from_db()
    assert character.status == Character.STATUS_COMPLETE and character.owner == owner
    assert character.classes.get().is_starting_class
    # Level 1: max hit die + Constitution modifier.
    klass = Class.objects.get(id=class_id)
    con_mod = (character.constitution - 10) // 2
    assert character.max_hit_points == int(klass.hit_die[1:]) + con_mod
    assert character.current_hit_points == character.max_hit_points
    assert character.experience_points == 0


@pytest.mark.parametrize("class_id", CLASS_IDS)
def test_recomputing_is_idempotent(owner, class_id):
    from apps.builder.services import effects

    character = build_character(owner, class_id)

    def snapshot():
        return {
            "prof": sorted(character.proficiencies.values_list("category", "name", "level")),
            "features": sorted(character.features.values_list("feature_id", flat=True)),
            "spells": sorted(character.spells.values_list("spell_id", "prepared")),
            "items": sorted(character.inventory_items.values_list("equipment_id", "quantity")),
            "abilities": sorted(character.ability_score_increases.values_list("ability", "amount")),
            "languages": sorted(character.languages.values_list("language_id", flat=True)),
        }

    first = snapshot()
    effects.apply(character)
    effects.apply(character)
    assert snapshot() == first


def test_finalize_refuses_an_incomplete_draft(owner):
    character = creation.start_draft(owner, "Nobody")

    problems = creation.finalize(character)

    assert problems
    character.refresh_from_db()
    assert character.status == Character.STATUS_DRAFT
    state = creation.get_state(character)
    assert state["current"] == "background" and not state["ready"]
    assert {s["key"]: s["status"] for s in state["steps"]}["abilities"] == "locked"


def test_the_ability_sum_invariant_holds(owner):
    """Rows per ability sum to the score on `Character` (the documented invariant)."""
    character = build_character(owner, "fighter")
    totals = {}
    for row in character.ability_score_increases.all():
        totals[row.ability] = totals.get(row.ability, 0) + row.amount
    for ability, total in totals.items():
        assert getattr(character, ability) == total


def test_discard_only_deletes_drafts(owner):
    draft = creation.start_draft(owner, "Draft")
    done = build_character(owner, "wizard")
    creation.finalize(done)

    creation.discard(draft)
    creation.discard(done)

    assert not Character.objects.filter(pk=draft.pk).exists()
    assert Character.objects.filter(pk=done.pk).exists()
    assert Draft(done).klass.id == "wizard"
