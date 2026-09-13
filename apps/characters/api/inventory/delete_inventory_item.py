"""Placeholder for DELETE /{character_id}/inventory/{item_id}."""

from apps.characters.api.inventory import router


@router.delete("/{character_id}/inventory/{item_id}")
def delete_inventory_item(request, character_id: int, item_id: int):
    """Remove an inventory item. TODO: implement via services."""
