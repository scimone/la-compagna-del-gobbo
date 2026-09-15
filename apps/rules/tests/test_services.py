import pytest
from django.http import Http404

from apps.rules.models import (
    ChoiceDefinition,
    Class,
    ClassLevel,
    Effect,
    Equipment,
    Rule,
    Spell,
    Subclass,
    SubclassLevel,
)
from apps.rules.services import background as background_service
from apps.rules.services import class_ as class_service
from apps.rules.services import equipment as equipment_service
from apps.rules.services import feature as feature_service
from apps.rules.services import rule as rule_service
from apps.rules.services import spell as spell_service
from apps.rules.services import subclass as subclass_service


@pytest.mark.django_db
def test_list_and_get_rule():
    Rule.objects.create(id="grappling", name="Grappling", page=1, srd=True, rule_type="Core")

    assert list(rule_service.list_rules()) == list(Rule.objects.all())
    assert rule_service.get_rule("grappling").name == "Grappling"


@pytest.mark.django_db
def test_get_rule_missing_raises_404():
    with pytest.raises(Http404):
        rule_service.get_rule("does-not-exist")


@pytest.mark.django_db
def test_get_class(klass):
    assert class_service.get_class("wizard") == klass


@pytest.mark.django_db
def test_list_class_levels(klass):
    ClassLevel.objects.create(klass=klass, level=1, columns={"Level": "1"})
    ClassLevel.objects.create(klass=klass, level=2, columns={"Level": "2"})

    levels = list(class_service.list_class_levels("wizard"))

    assert [lvl.level for lvl in levels] == [1, 2]


@pytest.mark.django_db
def test_list_class_levels_missing_class_raises_404():
    with pytest.raises(Http404):
        class_service.list_class_levels("does-not-exist")


@pytest.mark.django_db
def test_list_class_subclasses(klass):
    Subclass.objects.create(klass=klass, name="Evoker")
    fighter = Class.objects.create(
        id="fighter",
        name="Fighter",
        page=1,
        srd=True,
        hit_die="d10",
        primary_ability="Strength",
        saving_throws="Strength, Constitution",
    )
    Subclass.objects.create(klass=fighter, name="Champion")

    subclasses = class_service.list_class_subclasses("wizard")

    assert [s.name for s in subclasses] == ["Evoker"]


@pytest.mark.django_db
def test_list_class_choices(klass):
    ChoiceDefinition.objects.create(
        klass=klass, kind="skills", count=2, options=["Arcana", "History"], source_text="..."
    )

    choices = class_service.list_class_choices("wizard")

    assert choices.count() == 1


@pytest.mark.django_db
def test_list_background_choices(background):
    ChoiceDefinition.objects.create(
        background=background,
        kind="ability_scores",
        options=["Intelligence", "Wisdom", "Charisma"],
        source_text="Choose from Intelligence, Wisdom, Charisma",
    )

    choices = background_service.list_background_choices("sage")

    assert choices.count() == 1


@pytest.mark.django_db
def test_list_subclass_levels(klass):
    evoker = Subclass.objects.create(klass=klass, name="Evoker")
    SubclassLevel.objects.create(subclass=evoker, level=2)

    levels = subclass_service.list_subclass_levels(evoker.pk)

    assert levels.count() == 1


@pytest.mark.django_db
def test_list_equipment_filters_by_category():
    Equipment.objects.create(id="dagger", name="Dagger", page=1, srd=True, category="Melee Weapon")
    Equipment.objects.create(id="rope", name="Rope", page=1, srd=True, category="Adventuring Gear")

    weapons = equipment_service.list_equipment(category="Melee Weapon")

    assert [e.id for e in weapons] == ["dagger"]


@pytest.mark.django_db
def test_list_spells_filters_by_class_and_level(spell):
    Spell.objects.create(
        id="mage-armor",
        name="Mage Armor",
        page=1,
        srd=True,
        level=1,
        school="Abjuration",
        casting_time="1 action",
        range="Touch",
        components="V, S, M",
        duration="8 hours",
        classes=["Sorcerer", "Wizard"],
    )

    by_class = spell_service.list_spells(klass="Wizard")
    by_level = spell_service.list_spells(level=1)

    assert {s.id for s in by_class} == {"fireball", "mage-armor"}
    assert [s.id for s in by_level] == ["mage-armor"]


@pytest.mark.django_db
def test_list_feature_effects(feature):
    Effect.objects.create(feature=feature, tag="dc", raw="{@dc 8}")

    effects = feature_service.list_feature_effects(feature.pk)

    assert effects.count() == 1
