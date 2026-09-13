from apps.characters.api.details import router
from apps.characters.schemas import CharacterLanguageSchema
from apps.characters.services import languages


@router.get("/{character_id}/languages", response=list[CharacterLanguageSchema])
def list_character_languages(request, character_id: int):
    return languages.list_character_languages(character_id)
