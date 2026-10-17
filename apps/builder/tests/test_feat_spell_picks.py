"""Fey-/Shadow-Touched (a school-filtered pick plus a fixed spell), Ritual Caster, invocations."""

import pytest

from apps.builder.resolvers import feat as feat_resolver
from apps.builder.resolvers.grants import Grants
from apps.builder.resolvers.spell import spell_pool
from apps.rules.models import Feat, Spell

FEY_TOUCHED = [
    {
        "ability": "inherit",
        "innate": {"_": {"daily": {"1e": ["misty step|xphb", {"choose": "level=1|school=E;D"}]}}},
    }
]


@pytest.fixture
def spells(db):
    for slug, level, school in [
        ("charm-person", 1, "Enchantment"),
        ("detect-magic", 1, "Divination"),
        ("magic-missile", 1, "Evocation"),
        ("misty-step", 2, "Conjuration"),
    ]:
        Spell.objects.create(id=slug, name=slug, level=level, school=school, page=1)


@pytest.fixture
def fey_touched(db):
    return Feat.objects.create(
        id="fey-touched",
        name="Fey-Touched",
        page=1,
        category="General",
        additional_spells=FEY_TOUCHED,
    )


def test_the_pick_is_filtered_by_school_not_class(spells, fey_touched):
    (pick,) = [p for p in feat_resolver.picks(fey_touched) if p.kind == "spell"]
    assert pick.class_name == "" and pick.level == 1
    pool = {s.id for s in spell_pool(pick.class_name, pick.level, pick.schools)}
    assert pool == {"charm-person", "detect-magic"}


def test_the_fixed_spell_is_free_to_cast_once_and_so_is_the_chosen_one(spells, fey_touched):
    grants = Grants()
    feat_resolver.apply_feat(grants, fey_touched, {"spell": "charm-person"}, "general")
    rows = {row.spell_id: row for row in grants.spells.values()}
    assert rows["misty-step"].free_cast and rows["misty-step"].always_prepared
    assert rows["charm-person"].free_cast and rows["charm-person"].always_prepared
