"""Inventory item management (list_inventory, add_inventory_item, equip/unequip, ...)."""

from django.shortcuts import get_object_or_404

from apps.characters.models import CharacterInventoryItem
from apps.characters.services.character import get_character


def list_inventory(character_id: int):
    get_character(character_id)
    return CharacterInventoryItem.objects.filter(character_id=character_id)


def add_inventory_item(character_id: int, **data) -> CharacterInventoryItem:
    character = get_character(character_id)
    return CharacterInventoryItem.objects.create(character=character, **data)


def _get_inventory_item(character_id: int, item_id: int) -> CharacterInventoryItem:
    get_character(character_id)
    return get_object_or_404(CharacterInventoryItem, pk=item_id, character_id=character_id)


def update_inventory_item(character_id: int, item_id: int, **data) -> CharacterInventoryItem:
    item = _get_inventory_item(character_id, item_id)
    for field, value in data.items():
        setattr(item, field, value)
    item.save()
    return item


def delete_inventory_item(character_id: int, item_id: int) -> None:
    _get_inventory_item(character_id, item_id).delete()


def equip_inventory_item(character_id: int, item_id: int) -> CharacterInventoryItem:
    item = _get_inventory_item(character_id, item_id)
    item.equipped = True
    item.save(update_fields=["equipped"])
    return item


def unequip_inventory_item(character_id: int, item_id: int) -> CharacterInventoryItem:
    item = _get_inventory_item(character_id, item_id)
    item.equipped = False
    item.save(update_fields=["equipped"])
    return item
