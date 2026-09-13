"""Placeholder for DELETE /{character_id}/spells/{spell_id}."""

from apps.characters.api.spells import router


@router.delete("/{character_id}/spells/{spell_id}")
def remove_character_spell(request, character_id: int, spell_id: int):
    """Remove a spell from a character. TODO: implement via services."""
