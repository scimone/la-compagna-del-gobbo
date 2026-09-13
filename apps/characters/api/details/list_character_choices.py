from apps.characters.api.details import router
from apps.characters.schemas import CharacterChoiceSchema
from apps.characters.services import choices


@router.get("/{character_id}/choices", response=list[CharacterChoiceSchema])
def list_character_choices(request, character_id: int):
    return choices.list_character_choices(character_id)
