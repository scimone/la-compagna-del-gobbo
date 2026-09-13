import pytest

from apps.rules.models import Background, Class, Feat, Feature, Species, Spell


@pytest.fixture
def klass(db):
    return Class.objects.create(
        id="wizard",
        name="Wizard",
        page=1,
        srd=True,
        hit_die="d6",
        primary_ability="Intelligence",
        saving_throws="Intelligence, Wisdom",
    )


@pytest.fixture
def species(db):
    return Species.objects.create(
        id="elf",
        name="Elf",
        page=1,
        srd=True,
        size="Medium",
        speed="30 ft.",
        creature_type="Humanoid",
    )


@pytest.fixture
def background(db):
    return Background.objects.create(
        id="sage",
        name="Sage",
        page=1,
        srd=True,
        ability_scores="Choose from Intelligence, Wisdom, Charisma",
        skills="Arcana, History",
    )


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
        casting_time="1 action",
        range="150 feet",
        components="V, S, M",
        duration="Instantaneous",
        classes=["Sorcerer", "Wizard"],
    )


@pytest.fixture
def feature(klass):
    return Feature.objects.create(klass=klass, level=1, name="Spellcasting", entries=["text"])
