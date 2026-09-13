from apps.characters.api.spells import router
from apps.characters.schemas import CharacterSpellSchema
from apps.characters.services import spells


@router.post("/{character_id}/spells/{spell_id}/unprepare", response=CharacterSpellSchema)
def unprepare_character_spell(request, character_id: int, spell_id: str):
    return spells.unprepare_character_spell(character_id, spell_id)
