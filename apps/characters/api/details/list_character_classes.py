"""Placeholder for GET /{character_id}/classes."""

from apps.characters.api.details import router


@router.get("/{character_id}/classes")
def list_character_classes(request, character_id: int):
    """List a character's classes/subclasses and levels. TODO: implement via services."""
