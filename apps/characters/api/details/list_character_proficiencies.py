"""Placeholder for GET /{character_id}/proficiencies."""

from apps.characters.api.details import router


@router.get("/{character_id}/proficiencies")
def list_character_proficiencies(request, character_id: int):
    """List a character's proficiencies. TODO: implement via services."""
