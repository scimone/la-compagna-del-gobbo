from apps.characters.api.details import router
from apps.characters.schemas import CharacterSenseSchema
from apps.characters.services import senses


@router.get("/{character_id}/senses", response=list[CharacterSenseSchema])
def list_character_senses(request, character_id: int):
    return senses.list_character_senses(character_id)
