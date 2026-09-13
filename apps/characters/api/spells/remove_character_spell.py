from apps.characters.api.spells import router
from apps.characters.services import spells


@router.delete("/{character_id}/spells/{spell_id}")
def remove_character_spell(request, character_id: int, spell_id: str):
    spells.remove_character_spell(character_id, spell_id)
    return {"success": True}
