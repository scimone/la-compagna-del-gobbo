import pytest

from apps.rules.models import (
    Ability,
    Background,
    Class,
    ClassLevel,
    Feat,
    Feature,
    Skill,
    Species,
    Spell,
)


@pytest.fixture
def klass(db):
    return Class.objects.create(
        id="wizard",
        name="Wizard",
        page=1,
        srd=True,
        hit_die="d6",
    )


@pytest.fixture
def species(db):
    return Species.objects.create(
        id="elf",
        name="Elf",
        page=1,
        srd=True,
        size=["M"],
        speed=30,
        creature_types=["humanoid"],
    )


@pytest.fixture
def background(db):
    bg = Background.objects.create(
        id="sage",
        name="Sage",
        page=1,
        srd=True,
        ability_scores=[
            {"choose": {"weighted": {"from": ["int", "wis", "cha"], "weights": [2, 1]}}}
        ],
    )
    intelligence, _created = Ability.objects.get_or_create(
        id="int", defaults={"name": "Intelligence", "description": "Reasoning and memory."}
    )
    arcana = Skill.objects.create(
        id="arcana", name="Arcana", page=1, srd=True, ability=intelligence
    )
    history = Skill.objects.create(
        id="history", name="History", page=1, srd=True, ability=intelligence
    )
    bg.skills.set([arcana, history])
    return bg


@pytest.fixture
def feat(db):
    return Feat.objects.create(id="alert", name="Alert", page=1, srd=True, category="Origin")


@pytest.fixture
def spell(db):
    return Spell.objects.create(
        id="fireball",
        name="Fireball",
        page=1,
        srd=True,
        level=3,
        school="Evocation",
        casting_time=[{"number": 1, "unit": "action"}],
        range={"type": "point", "distance": {"type": "feet", "amount": 150}},
        components={"v": True, "s": True, "m": {"text": "a tiny ball of bat guano and sulfur"}},
        duration=[{"type": "instant"}],
        classes=["Sorcerer", "Wizard"],
    )


@pytest.fixture
def feature(klass):
    class_level = ClassLevel.objects.create(klass=klass, level=1)
    return Feature.objects.create(class_level=class_level, name="Spellcasting", entries=["text"])
