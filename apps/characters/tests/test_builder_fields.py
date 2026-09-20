"""The `characters` fields added for the creation wizard (docs/character_creation_plan.md, 3.5)."""

import pytest
from django.contrib.auth import get_user_model

from apps.characters.models import Character, CharacterInventoryItem
from apps.rules.models import Equipment


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user("alice")


def test_plain_characters_default_to_complete_and_ownerless(db):
    character = Character.objects.create(name="Bob")

    assert character.status == Character.STATUS_COMPLETE
    assert character.owner is None
    assert character.experience_points == 0


def test_deleting_an_account_keeps_its_characters(owner):
    character = Character.objects.create(name="Mira", owner=owner, status=Character.STATUS_DRAFT)

    owner.delete()

    character.refresh_from_db()
    assert character.owner is None and character.status == Character.STATUS_DRAFT


def test_pack_contents_are_traceable_and_die_with_their_pack(db):
    character = Character.objects.create(name="Mira")
    pack = Equipment.objects.create(id="burglars-pack", name="Burglar's Pack", page=1)
    candle = Equipment.objects.create(id="candle", name="Candle", page=1)
    pack_row = CharacterInventoryItem.objects.create(character=character, equipment=pack)
    CharacterInventoryItem.objects.create(
        character=character, equipment=candle, quantity=5, parent=pack_row
    )
    CharacterInventoryItem.objects.create(character=character, equipment=candle)  # a loose one

    assert [i.equipment_id for i in pack_row.contents.all()] == ["candle"]

    pack_row.delete()

    remaining = CharacterInventoryItem.objects.filter(character=character)
    assert remaining.count() == 1 and remaining.get().parent is None


def test_the_api_list_leaves_out_unfinished_drafts(db):
    from apps.characters.services import character as character_service

    Character.objects.create(name="Done")
    Character.objects.create(name="Wip", status=Character.STATUS_DRAFT)

    assert [c.name for c in character_service.list_characters()] == ["Done"]
