"""Eldritch Invocations that give spells (Pact of the Chain, Pact of the Tome, ...), and Ritual
Caster's rituals - at creation and when levelling up."""

import pytest

from apps.builder.services import class_choices, progression
from apps.builder.services.store import Draft
from apps.builder.tests.conftest import build_character
from apps.builder.tests.test_progression import autofill, finished, level_up
from apps.characters.services import play

pytestmark = pytest.mark.usefixtures("imported_rules")


def _choose_invocation(character, option_id):
    class_choices.save(character, invocations=[option_id])
    for _round in range(2):
        for picker in class_choices.pickers(Draft(character)):
            if picker.key.startswith("class.opt."):
                class_choices.save(
                    character,
                    **{
                        picker.key.removeprefix("class."): [c[0] for c in picker.candidates][
                            : picker.count
                        ]
                    },
                )
    assert not class_choices.issues(Draft(character))


def test_pact_of_the_chain_adds_find_familiar_cast_without_a_slot(owner):
    warlock = build_character(owner, "warlock")
    _choose_invocation(warlock, "pact-of-the-chain")
    warlock.refresh_from_db()
    row = warlock.spells.get(spell_id="find-familiar")
    assert row.source == "option:pact-of-the-chain" and row.klass_id == "warlock"
    assert row.always_prepared and row.free_cast_unlimited
    # never spent, however often it is cast
    for _cast in range(3):
        assert play.cast_spell(warlock, "find-familiar", free=True) == "free"


def test_pact_of_the_tome_asks_for_cantrips_and_rituals_from_any_list(owner):
    warlock = build_character(owner, "warlock")
    class_choices.save(warlock, invocations=["pact-of-the-tome"])
    pickers = {p.key: p for p in class_choices.pickers(Draft(warlock))}
    cantrips = pickers["class.opt.pact-of-the-tome.cantrips"]
    rituals = pickers["class.opt.pact-of-the-tome.rituals"]
    assert cantrips.count == 3 and rituals.count == 2
    assert len(cantrips.candidates) > 20  # any class's list, not only the Warlock's
    assert rituals.candidates and all(
        s.ritual and s.level == 1
        for s in __import__("apps.rules.models", fromlist=["Spell"]).Spell.objects.filter(
            id__in=rituals.candidate_ids
        )
    )
    _choose_invocation(warlock, "pact-of-the-tome")
    warlock.refresh_from_db()
    tome = warlock.spells.filter(source="option:pact-of-the-tome")
    assert tome.filter(spell__level=0).count() == 3
    assert tome.filter(spell__level=1, always_prepared=True).count() == 2


def test_replacing_an_invocation_swaps_the_spells_it_gave(owner):
    warlock = finished(owner, "warlock")
    (held,) = warlock.optional_features.values_list("optional_feature_id", flat=True)
    assert held != "pact-of-the-chain"
    values = autofill(
        warlock,
        "warlock",
        prefer={"lu.invocation_out": [held], "lu.invocation_in": ["pact-of-the-chain"]},
    )
    progression.commit(warlock, "warlock", values)
    assert not warlock.spells.filter(source=f"option:{held}").exists()
    assert warlock.spells.filter(spell_id="find-familiar", free_cast_unlimited=True).exists()


def test_ritual_caster_picks_rituals_and_gains_one_when_the_proficiency_bonus_rises(owner):
    wizard = finished(owner, "wizard")
    for _level in range(2, 4):
        level_up(wizard, "wizard")
    plan = progression.plan(wizard, "wizard", {"lu.feat": ["ritual-caster"]})
    rituals = next(p for p in plan.pickers if p.key == "lu.feat.rituals")
    assert rituals.count == 2 and rituals.candidates
    level_up(wizard, "wizard", prefer={"lu.feat": ["ritual-caster"]})
    assert wizard.spells.filter(source="feat:ritual-caster", always_prepared=True).count() == 2

    plan = progression.plan(wizard, "wizard", {})
    assert any(p.key == "lu.ritual_caster" for p in plan.pickers)  # level 5: one more
    level_up(wizard, "wizard", values={"lu.ritual_caster": ["identify"]})
    assert wizard.spells.filter(source="feat:ritual-caster").count() == 3
