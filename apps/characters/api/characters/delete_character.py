"""Placeholder for DELETE /{character_id}."""

from apps.characters.api.characters import router


@router.delete("/{character_id}")
def delete_character(request, character_id: int):
    """Delete a character. TODO: implement via services."""
