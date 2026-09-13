"""Placeholder for POST /{character_id}/inventory/{item_id}/unequip."""

from apps.characters.api.inventory import router


@router.post("/{character_id}/inventory/{item_id}/unequip")
def unequip_inventory_item(request, character_id: int, item_id: int):
    """Unequip an inventory item. TODO: implement via services."""
