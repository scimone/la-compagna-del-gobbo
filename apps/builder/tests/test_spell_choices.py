"""Features that hand out spells to choose must ask for them when the level is gained."""

import pytest
from django.utils import translation

from apps.builder.services import progression
from apps.builder.tests.test_progression import autofill, finished, level_up
from apps.characters.models import CharacterSpell
from apps.rules.models import Subclass

pytestmark = pytest.mark.usefixtures("imported_rules")


def _to_level(character, class_id, target, **kwargs):
    while progression.total_level(character) < target:
        level_up(character, class_id, **kwargs)


def _lore(character):
    lore = Subclass.objects.get(klass_id="bard", name_en="College of Lore")
    return {"prefer": {"lu.subclass": [str(lore.pk)]}}


@pytest.mark.parametrize("language", ["en", "it"])
def test_magical_discoveries_asks_for_two_spells_from_three_lists(owner, language):
    character = finished(owner, "bard")
    with translation.override(language):
        _to_level(character, "bard", 5, prefer={"lu.subclass": [str(_lore_pk())]})
        plan = progression.plan(character, "bard")
        picks = [p for p in plan.pickers if p.key.startswith("lu.savant.")]
        assert [p.count for p in picks] == [2] and not plan.ready
        first = picks[0]
        assert {c[0] for c in first.candidates} & {"cure-wounds", "fireball", "entangle"}
        values = autofill(character, "bard")
        progression.commit(character, "bard", values)
    chosen = character.spells.filter(source__startswith="subclass:", always_prepared=True)
    assert chosen.count() == 2 and all(s.prepared for s in chosen)


def _lore_pk():
    return Subclass.objects.get(klass_id="bard", name_en="College of Lore").pk


def test_magical_discoveries_spells_can_be_replaced_on_a_later_level(owner):
    character = finished(owner, "bard")
    _to_level(character, "bard", 6, prefer={"lu.subclass": [str(_lore_pk())]})
    plan = progression.plan(character, "bard")
    keys = {p.key for p in plan.pickers}
    assert {"lu.discovery_out", "lu.discovery_in"} <= keys
    old = character.spells.filter(source__startswith="subclass:", always_prepared=True).first()
    new = next(
        c[0]
        for p in plan.pickers
        if p.key == "lu.discovery_in"
        for c in p.candidates
        if c[0] != old.spell_id
    )
    values = autofill(character, "bard")
    values |= {"lu.discovery_out": [old.spell_id], "lu.discovery_in": [new]}
    progression.commit(character, "bard", values)
    assert not CharacterSpell.objects.filter(character=character, spell_id=old.spell_id).exists()
    assert CharacterSpell.objects.filter(
        character=character, spell_id=new, always_prepared=True
    ).exists()


def test_magical_secrets_widens_the_bards_prepared_spell_lists(owner):
    character = finished(owner, "bard")
    _to_level(character, "bard", 8, prefer={"lu.subclass": [str(_lore_pk())]})
    before = progression.plan(character, "bard", autofill(character, "bard"))
    assert not any(
        c[0] == "entangle" for p in before.pickers if p.key == "lu.spells" for c in p.candidates
    )  # not yet (this is the plan for level 9)
    level_up(character, "bard")
    ten = progression.plan(character, "bard")
    spells = next(p for p in ten.pickers if p.key == "lu.spells")
    assert any(c[0] == "spirit-guardians" for c in spells.candidates)  # Cleric
    assert any(c[0] == "entangle" for c in spells.candidates)  # Druid
    assert any(c[0] == "fireball" for c in spells.candidates)  # Wizard


@pytest.mark.parametrize(("level", "key"), [(18, "lu.mastery.1"), (20, "lu.signature")])
def test_wizard_mastery_and_signature_spells_are_chosen(owner, level, key):
    character = finished(owner, "wizard")
    _to_level(character, "wizard", level - 1)
    plan = progression.plan(character, "wizard", autofill(character, "wizard"))
    assert key in {p.key for p in plan.pickers}
    values = autofill(character, "wizard")
    progression.commit(character, "wizard", values)
    if level == 18:
        assert character.spells.filter(free_cast_unlimited=True).count() == 2
    else:
        assert character.spells.filter(always_prepared=True, free_cast=True).count() == 2


def test_every_subclass_spell_pick_is_asked_when_its_level_is_reached(owner):
    """Whatever `{"choose": ...}` a subclass lists in `additionalSpells` has a picker."""
    for subclass in Subclass.objects.all():
        blocks = [
            (key, item)
            for entry in subclass.additional_spells
            for block in ("known", "prepared")
            for key, items in (entry.get(block) or {}).items()
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict) and "choose" in item
        ]
        if not blocks or subclass.klass_id not in {"bard", "wizard"}:
            continue
        character = finished(owner, subclass.klass_id)
        level = min(int(key) for key, _ in blocks)
        picked = {"prefer": {"lu.subclass": [str(subclass.pk)]}}
        _to_level(character, subclass.klass_id, max(level - 1, 2), **picked)
        plan = progression.plan(character, subclass.klass_id, {"lu.subclass": [str(subclass.pk)]})
        assert any(p.key.startswith("lu.savant.") for p in plan.pickers), subclass.name_en
