"""Placeholder for POST /{character_id}/spells/{spell_id}/unprepare."""

from apps.characters.api.spells import router


@router.post("/{character_id}/spells/{spell_id}/unprepare")
def unprepare_character_spell(request, character_id: int, spell_id: int):
    """Unprepare a known spell. TODO: implement via services."""
