"""Placeholder for PATCH /{character_id}."""

from apps.characters.api.characters import router


@router.patch("/{character_id}")
def update_character(request, character_id: int):
    """Update a character. TODO: implement via services."""
