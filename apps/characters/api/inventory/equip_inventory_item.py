"""Placeholder for POST /{character_id}/inventory/{item_id}/equip."""

from apps.characters.api.inventory import router


@router.post("/{character_id}/inventory/{item_id}/equip")
def equip_inventory_item(request, character_id: int, item_id: int):
    """Equip an inventory item. TODO: implement via services."""
