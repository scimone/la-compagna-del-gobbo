"""Placeholder for GET /{character_id}."""

from apps.characters.api.characters import router


@router.get("/{character_id}")
def get_character(request, character_id: int):
    """Retrieve a character. TODO: implement via services."""
