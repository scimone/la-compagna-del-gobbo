"""Placeholder for GET /{character_id}/languages."""

from apps.characters.api.details import router


@router.get("/{character_id}/languages")
def list_character_languages(request, character_id: int):
    """List a character's known languages. TODO: implement via services."""
