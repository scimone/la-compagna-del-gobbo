from apps.characters.api.spells import router
from apps.characters.schemas import CharacterSpellSchema
from apps.characters.services import spells


@router.post("/{character_id}/spells/{spell_id}/prepare", response=CharacterSpellSchema)
def prepare_character_spell(request, character_id: int, spell_id: str):
    return spells.prepare_character_spell(character_id, spell_id)
