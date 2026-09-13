from apps.characters.api.characters import router
from apps.characters.schemas import CharacterOutSchema
from apps.characters.services import character


@router.get("/{character_id}", response=CharacterOutSchema)
def get_character(request, character_id: int):
    return character.get_character(character_id)
