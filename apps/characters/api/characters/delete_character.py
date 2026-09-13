from apps.characters.api.characters import router
from apps.characters.services import character


@router.delete("/{character_id}")
def delete_character(request, character_id: int):
    character.delete_character(character_id)
    return {"success": True}
