"""Placeholder for POST /{character_id}/inventory."""

from apps.characters.api.inventory import router


@router.post("/{character_id}/inventory")
def add_inventory_item(request, character_id: int):
    """Add an item to a character's inventory. TODO: implement via services."""
