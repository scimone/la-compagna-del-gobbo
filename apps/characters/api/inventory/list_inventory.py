"""Placeholder for GET /{character_id}/inventory."""

from apps.characters.api.inventory import router


@router.get("/{character_id}/inventory")
def list_inventory(request, character_id: int):
    """List a character's inventory. TODO: implement via services."""
