"""An admin rebuilding a levelled character: back to level 1, change a part, replay the levels."""

import pytest

from apps.builder.services import class_choices, creation, origins, progression, rebuild
from apps.builder.services.store import Draft
from apps.builder.tests.conftest import complete_species, pick_first
from apps.builder.tests.test_progression import autofill, finished, level_up
from apps.characters.models import CharacterChoice, CharacterClass, CharacterFeat

pytestmark = pytest.mark.usefixtures("imported_rules")


def leveled(owner, class_id, levels, **kwargs):
    character = finished(owner, class_id, **kwargs)
    for _ in range(levels - 1):
        level_up(character, class_id)
    character.experience_points += 7
    character.save()
    return character


def test_levels_are_recorded_as_they_are_applied(owner):
    character = leveled(owner, "fighter", 3)
    entries = rebuild.history(character)
    assert [e["klass"] for e in entries] == ["fighter", "fighter"]
    assert entries[0]["values"]["lu.hp_mode"] == ["fixed"]


def test_reopen_goes_back_to_level_one(owner):
    character = leveled(owner, "fighter", 4)
    assert not creation.can_reopen(character) and creation.can_reopen(character, any_level=True)
    assert not creation.reopen(character)
    assert creation.reopen(character, any_level=True)

    row = CharacterClass.objects.get(character=character)
    assert (row.level, row.is_starting_class) == (1, True)
    assert progression.total_level(character) == 1
    assert len(rebuild.pending(character)) == 3
    assert not character.feats.filter(granted_at_level__gt=1, source="levelup").exists()
    assert not CharacterChoice.objects.filter(character=character, key="meta.history").exists()
    assert creation.get_state(character)["ready"]


def test_changing_the_species_replays_every_level_unchanged(owner):
    character = leveled(owner, "fighter", 4)
    creation.reopen(character, any_level=True)
    complete_species(character, "dwarf")
    assert not creation.finalize(character)
    assert rebuild.replaying(character) and character.status == "draft"

    assert rebuild.advance(character) is None
    character.refresh_from_db()
    assert character.status == "complete" and not creation.is_editing(character)
    assert character.species_id == "dwarf"
    assert progression.total_level(character) == 4
    assert character.experience_points >= 7
    assert not rebuild.has_pending(character)
    assert len(rebuild.history(character)) == 3
    # the level-4 feat is back
    assert CharacterFeat.objects.filter(character=character, source="levelup").exists()


def test_changing_the_class_asks_for_every_level_again(owner):
    character = leveled(owner, "fighter", 3)
    creation.reopen(character, any_level=True)
    assert not origins.select_class(character, "wizard")
    for _round in range(3):
        for picker in class_choices.pickers(Draft(character)):
            chosen = pick_first(picker)
            class_choices.save(
                character,
                **{picker.key.removeprefix("class."): chosen[0] if picker.single else chosen},
            )
    assert not creation.finalize(character)

    entry = rebuild.advance(character)  # a Wizard level 2 asks for its spells
    assert entry and entry["klass"] == "wizard" and entry["values"] == {}
    assert rebuild.progress(character) == (0, 2)

    values = autofill(character, "wizard")
    progression.commit(character, "wizard", values, rebuilding=True)
    rebuild.drop_first(character)
    assert rebuild.advance(character) is None or rebuild.pending(character)
    values = autofill(character, "wizard")
    progression.commit(character, "wizard", values, rebuilding=True)
    rebuild.drop_first(character)
    assert rebuild.advance(character) is None
    character.refresh_from_db()
    assert character.status == "complete"
    assert [(r.klass_id, r.level) for r in character.classes.all()] == [("wizard", 3)]
    assert not character.features.filter(feature__name_en="Second Wind").exists()
