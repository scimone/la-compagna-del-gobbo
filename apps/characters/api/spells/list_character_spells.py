"""Placeholder for GET /{character_id}/spells."""

from apps.characters.api.spells import router


@router.get("/{character_id}/spells")
def list_character_spells(request, character_id: int):
    """List a character's spells. TODO: implement via services."""
