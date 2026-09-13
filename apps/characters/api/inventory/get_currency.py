"""Placeholder for GET /{character_id}/currency."""

from apps.characters.api.inventory import router


@router.get("/{character_id}/currency")
def get_currency(request, character_id: int):
    """Retrieve a character's currency. TODO: implement via services."""
