"""Placeholder for PATCH /{character_id}/currency."""

from apps.characters.api.inventory import router


@router.patch("/{character_id}/currency")
def update_currency(request, character_id: int):
    """Update a character's currency. TODO: implement via services."""
