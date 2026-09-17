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
        size=["M"],
        speed=30,
        creature_types=["humanoid"],
    )


@pytest.fixture
def background(db):
    return Background.objects.create(
        id="soldier",
        name="Soldier",
        page=1,
        srd=True,
        ability_scores=[
            {"choose": {"weighted": {"from": ["str", "dex", "con"], "weights": [2, 1]}}}
        ],
    )


@pytest.fixture
def equipment_item(db):
    return Equipment.objects.create(id="longsword", name="Longsword", page=1, srd=True)


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
