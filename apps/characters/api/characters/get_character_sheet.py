from apps.characters.api.characters import router
from apps.characters.schemas import CharacterSheetSchema
from apps.characters.services import character


@router.get("/{character_id}/sheet", response=CharacterSheetSchema)
def get_character_sheet(request, character_id: int):
    return character.get_character_sheet(character_id)
