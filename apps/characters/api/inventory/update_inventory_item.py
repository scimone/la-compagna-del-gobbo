"""Placeholder for PATCH /{character_id}/inventory/{item_id}."""

from apps.characters.api.inventory import router


@router.patch("/{character_id}/inventory/{item_id}")
def update_inventory_item(request, character_id: int, item_id: int):
    """Update an inventory item. TODO: implement via services."""
