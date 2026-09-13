from apps.characters.api.characters import router
from apps.characters.schemas import CharacterOutSchema
from apps.characters.services import character


@router.get("/", response=list[CharacterOutSchema])
def list_characters(request):
    return character.list_characters()
