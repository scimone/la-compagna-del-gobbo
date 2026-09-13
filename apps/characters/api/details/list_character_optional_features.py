from apps.characters.api.details import router
from apps.characters.schemas import CharacterOptionalFeatureSchema
from apps.characters.services import optional_features


@router.get("/{character_id}/optional-features", response=list[CharacterOptionalFeatureSchema])
def list_character_optional_features(request, character_id: int):
    return optional_features.list_character_optional_features(character_id)
