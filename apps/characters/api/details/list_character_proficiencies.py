from apps.characters.api.details import router
from apps.characters.schemas import CharacterProficiencySchema
from apps.characters.services import proficiencies


@router.get("/{character_id}/proficiencies", response=list[CharacterProficiencySchema])
def list_character_proficiencies(request, character_id: int):
    return proficiencies.list_character_proficiencies(character_id)
