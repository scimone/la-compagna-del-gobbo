"""Placeholder for POST /{character_id}/spells."""

from apps.characters.api.spells import router


@router.post("/{character_id}/spells")
def add_character_spell(request, character_id: int):
    """Add a spell to a character. TODO: implement via services."""
