from apps.characters.api.details import router
from apps.characters.schemas import CharacterFeatureSchema
from apps.characters.services import features


@router.get("/{character_id}/features", response=list[CharacterFeatureSchema])
def list_character_features(request, character_id: int):
    return features.list_character_features(character_id)
