"""Wild Companion (Druid 2): Find Familiar cast with a spell slot or a use of Wild Shape."""

import pytest

from apps.builder.tests.conftest import build_character
from apps.builder.tests.test_progression import finished, level_up
from apps.characters.models import CharacterSpell
from apps.characters.services import play

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture
def druid(owner):
    character = finished(owner, "druid")
    level_up(character, "druid")
    return character


def test_levelling_to_two_gives_find_familiar_without_the_ritual(druid):
    row = druid.spells.get(spell_id="find-familiar")
    assert row.source == play.WILD_COMPANION_SOURCE and row.always_prepared
    with pytest.raises(ValueError):
        play.cast_spell(druid, "find-familiar", ritual=True)


def test_it_is_cast_with_a_slot_or_a_wild_shape_use(druid):
    uses = druid.resources.get(name="Wild Shape")
    before = uses.current_uses
    assert play.cast_spell(druid, "find-familiar", wild_shape=True) == "wild_shape"
    uses.refresh_from_db()
    assert uses.current_uses == before - 1
    assert play.cast_spell(druid, "find-familiar", slot_key="1", slot_max=2, slot_level=1) == "1"
    druid.refresh_from_db()
    assert druid.spell_slots_spent["1"] == 1 and uses.current_uses == before - 1


def test_no_wild_shape_use_left_refuses(druid):
    druid.resources.filter(name="Wild Shape").update(current_uses=0)
    with pytest.raises(ValueError):
        play.cast_spell(druid, "find-familiar", wild_shape=True)


def test_a_spell_the_character_has_from_elsewhere_keeps_its_ritual(owner):
    character = finished(owner, "druid")
    CharacterSpell.objects.create(
        character=character, spell_id="find-familiar", prepared=True, source="feat:magic-initiate"
    )
    level_up(character, "druid")
    row = character.spells.get(spell_id="find-familiar")
    assert row.source == "feat:magic-initiate"
    assert play.cast_spell(character, "find-familiar", ritual=True) == "ritual"
    assert play.cast_spell(character, "find-familiar", wild_shape=True) == "wild_shape"


def test_gaining_the_spell_later_takes_it_over_from_wild_companion(druid):
    from apps.builder.services.progression import _add_spell

    _add_spell(druid, "find-familiar", None, "feat:ritual-caster", prepared=True)
    row = druid.spells.get(spell_id="find-familiar")
    assert row.source == "feat:ritual-caster"
    assert play.cast_spell(druid, "find-familiar", ritual=True) == "ritual"


def test_a_character_without_the_feature_cannot_use_it(owner):
    character = build_character(owner, "druid")
    CharacterSpell.objects.create(character=character, spell_id="find-familiar", prepared=True)
    with pytest.raises(ValueError):
        play.cast_spell(character, "find-familiar", wild_shape=True)
