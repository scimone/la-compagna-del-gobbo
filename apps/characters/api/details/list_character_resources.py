from apps.characters.api.details import router
from apps.characters.schemas import CharacterResourceSchema
from apps.characters.services import resources


@router.get("/{character_id}/resources", response=list[CharacterResourceSchema])
def list_character_resources(request, character_id: int):
    return resources.list_character_resources(character_id)
