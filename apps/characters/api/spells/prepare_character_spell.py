"""Placeholder for POST /{character_id}/spells/{spell_id}/prepare."""

from apps.characters.api.spells import router


@router.post("/{character_id}/spells/{spell_id}/prepare")
def prepare_character_spell(request, character_id: int, spell_id: int):
    """Prepare a known spell. TODO: implement via services."""
