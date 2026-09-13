from apps.characters.api.spells import router
from apps.characters.schemas import CharacterSpellSchema
from apps.characters.services import spells


@router.get("/{character_id}/spells", response=list[CharacterSpellSchema])
def list_character_spells(request, character_id: int):
    return spells.list_character_spells(character_id)
