import pytest
from django.http import Http404

from apps.characters.services import character as character_service
from apps.characters.services import currency as currency_service
from apps.characters.services import inventory as inventory_service
from apps.characters.services import spells as spells_service


@pytest.mark.django_db
def test_create_and_get_character(species, background):
    created = character_service.create_character(
        name="Frodo", species=species, background=background, max_hit_points=10
    )

    fetched = character_service.get_character(created.pk)

    assert fetched.name == "Frodo"
    assert fetched.species == species


@pytest.mark.django_db
def test_get_character_missing_raises_404():
    with pytest.raises(Http404):
        character_service.get_character(999999)


@pytest.mark.django_db
def test_update_character(character):
    updated = character_service.update_character(character.pk, alignment="Lawful Good")

    assert updated.alignment == "Lawful Good"
    assert character_service.get_character(character.pk).alignment == "Lawful Good"


@pytest.mark.django_db
def test_delete_character(character):
    character_service.delete_character(character.pk)

    with pytest.raises(Http404):
        character_service.get_character(character.pk)


@pytest.mark.django_db
def test_get_character_sheet_aggregates_collections(character, equipment_item):
    inventory_service.add_inventory_item(character.pk, equipment=equipment_item)

    sheet = character_service.get_character_sheet(character.pk)

    assert sheet["character"] == character
    assert sheet["inventory_items"].count() == 1
    assert sheet["currency"] is None


@pytest.mark.django_db
def test_inventory_add_equip_unequip_delete(character, equipment_item):
    item = inventory_service.add_inventory_item(character.pk, equipment=equipment_item, quantity=2)
    assert item.equipped is False

    equipped = inventory_service.equip_inventory_item(character.pk, item.pk)
    assert equipped.equipped is True

    unequipped = inventory_service.unequip_inventory_item(character.pk, item.pk)
    assert unequipped.equipped is False

    inventory_service.delete_inventory_item(character.pk, item.pk)
    assert inventory_service.list_inventory(character.pk).count() == 0


@pytest.mark.django_db
def test_currency_get_or_create_and_update(character):
    currency = currency_service.get_currency(character.pk)
    assert currency.gold == 0

    updated = currency_service.update_currency(character.pk, gold=15, silver=6)
    assert updated.gold == 15
    assert updated.silver == 6


@pytest.mark.django_db
def test_spells_add_prepare_unprepare_remove(character, spell):
    spells_service.add_character_spell(character.pk, spell=spell, prepared=True)

    prepared = spells_service.prepare_character_spell(character.pk, spell.pk)
    assert prepared.prepared is True

    unprepared = spells_service.unprepare_character_spell(character.pk, spell.pk)
    assert unprepared.prepared is False

    spells_service.remove_character_spell(character.pk, spell.pk)
    assert spells_service.list_character_spells(character.pk).count() == 0
