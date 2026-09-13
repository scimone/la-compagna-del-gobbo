"""Placeholder for GET /{character_id}/senses."""

from apps.characters.api.details import router


@router.get("/{character_id}/senses")
def list_character_senses(request, character_id: int):
    """List a character's senses. TODO: implement via services."""
