import pytest

from apps.characters.models import Character
from apps.rules.models import Background, Equipment, Species, Spell


@pytest.fixture
def species(db):
    return Species.objects.create(
        id="human",
        name="Human",
        page=1,
        srd=True,
        size="Medium",
        speed="30 ft.",
        creature_type="Humanoid",
    )


@pytest.fixture
def background(db):
    return Background.objects.create(
        id="soldier",
        name="Soldier",
        page=1,
        srd=True,
        ability_scores="Choose from Strength, Constitution",
        skills="Athletics, Intimidation",
    )


@pytest.fixture
def equipment_item(db):
    return Equipment.objects.create(
        id="longsword", name="Longsword", page=1, srd=True, category="Melee Weapon"
    )


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
    )


@pytest.fixture
def character(species, background):
    return Character.objects.create(
        name="Aragorn",
        species=species,
        background=background,
        strength=16,
        dexterity=14,
        constitution=14,
        intelligence=10,
        wisdom=12,
        charisma=13,
        max_hit_points=44,
        current_hit_points=44,
    )
