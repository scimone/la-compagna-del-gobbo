"""`CLASS_SPEC` is hand-written from prose; these tests keep it honest against the imported data."""

import pytest

from apps.builder import tables
from apps.builder.class_spec import CLASS_SPEC
from apps.rules.models import (
    Class,
    ClassLevel,
    Equipment,
    Feature,
    Language,
    OptionalFeature,
    Skill,
    Spell,
)

pytestmark = pytest.mark.usefixtures("imported_rules")


def _level1_features(class_id):
    return set(
        Feature.objects.filter(class_level__klass_id=class_id, class_level__level=1).values_list(
            "name", flat=True
        )
    )


def test_spec_covers_exactly_the_imported_classes_and_their_standard_arrays(db):
    class_ids = set(Class.objects.values_list("id", flat=True))
    assert set(CLASS_SPEC) == class_ids
    assert set(tables.STANDARD_ARRAY_BY_CLASS) == class_ids


def test_standard_array_puts_the_highest_score_on_a_primary_ability(db):
    for klass in Class.objects.all():
        assignment = tables.STANDARD_ARRAY_BY_CLASS[klass.id]
        top = {a for a, score in assignment.items() if score == 15}
        primary = {a.id for a in klass.primary_abilities.all()}
        assert top & primary, (klass.id, top, primary)


@pytest.mark.parametrize("class_id", sorted(CLASS_SPEC))
def test_features_the_spec_relies_on_exist_at_level_one(db, class_id):
    spec, features = CLASS_SPEC[class_id], _level1_features(class_id)

    assert ("Weapon Mastery" in features) == bool(spec.weapon_mastery)
    assert ("Fighting Style" in features) == spec.fighting_style
    assert ("Expertise" in features) == bool(spec.expertise)
    assert ("Eldritch Invocations" in features) == bool(spec.invocations)
    if spec.order_feature:
        assert spec.order_feature in features
        assert {o.feature for o in spec.orders} <= features
    for resource in spec.resources:
        assert resource.name in features or resource.name == "Rage" and "Rage" in features


def test_spec_matches_the_class_tables(db):
    for class_id, spec in CLASS_SPEC.items():
        columns = ClassLevel.objects.get(klass_id=class_id, level=1).columns
        if spec.weapon_mastery and "Weapon Mastery" in columns:
            assert int(columns["Weapon Mastery"]) == spec.weapon_mastery.count, class_id
        if spec.invocations:
            assert columns["Invocations"] == spec.invocations
        for resource in spec.resources:
            if resource.maximum[0] == "column":
                assert resource.maximum[1] in columns, (class_id, resource.name)
        if class_id == "sorcerer":
            assert ClassLevel.objects.get(klass_id="sorcerer", level=1).cantrips_known == 4


def test_spell_ids_languages_and_skills_in_the_spec_exist(db):
    spell_ids = set(Spell.objects.values_list("id", flat=True))
    language_ids = set(Language.objects.values_list("id", flat=True))
    skill_ids = set(Skill.objects.values_list("id", flat=True))
    for spec in CLASS_SPEC.values():
        assert set(spec.always_prepared) <= spell_ids
        assert set(spec.languages) <= language_ids
        for order in spec.orders:
            assert set(order.wisdom_bonus_skills) <= skill_ids
    assert set(tables.LANGUAGE_D12.values()) <= language_ids
    assert tables.COMMON_LANGUAGE_ID in language_ids


def test_tool_picks_exist_exactly_where_the_class_data_has_a_tool_placeholder(db):
    for klass in Class.objects.all():
        placeholders = {
            k for grant in klass.tool_proficiencies for k in grant if k.startswith("any")
        }
        spec = CLASS_SPEC[klass.id]
        assert set(spec.tool_pick.kinds if spec.tool_pick else ()) == placeholders, klass.id


def test_unarmored_defense_matches_the_feature_text(db):
    for class_id, ability in (("barbarian", "con"), ("monk", "wis")):
        assert CLASS_SPEC[class_id].unarmored_defense[0] == ability
        assert "Unarmored Defense" in _level1_features(class_id)
    assert sum(1 for s in CLASS_SPEC.values() if s.unarmored_defense) == 2


def test_the_weapon_pool_for_mastery_is_what_the_spec_assumes(db):
    """Weapons with a Mastery property, as the builder must offer them: melee (type `m`) or
    ranged (`r`) only. "Staff" and "Wooden Staff" are spellcasting-focus rows that duplicate the
    Quarterstaff (same 1d6, same Topple) - offering them would list one weapon three times.
    """
    with_mastery = Equipment.objects.filter(masteries__isnull=False).distinct()
    assert with_mastery.count() == 41
    assert {w.id for w in with_mastery.filter(type_id="scf")} == {"staff", "wooden-staff"}

    pool = with_mastery.filter(type_id__in=["m", "r"])
    assert pool.count() == 39
    assert {w.weapon_category for w in pool} == {"simple", "martial"}
    assert pool.filter(type_id="m").count() == 29  # what Barbarian's "melee" means
    # Every simple/martial weapon in the catalog has a Mastery - none is silently missing.
    assert not Equipment.objects.filter(
        weapon_category__in=["simple", "martial"], type_id__in=["m", "r"], masteries__isnull=True
    ).exists()


def test_eldritch_invocations_offered_at_level_one_exist(db):
    assert OptionalFeature.objects.filter(feature_type="Eldritch Invocation").count() == 28
