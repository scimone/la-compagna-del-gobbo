from apps.characters.api.details import router
from apps.characters.schemas import CharacterClassSchema
from apps.characters.services import classes


@router.get("/{character_id}/classes", response=list[CharacterClassSchema])
def list_character_classes(request, character_id: int):
    return classes.list_character_classes(character_id)
