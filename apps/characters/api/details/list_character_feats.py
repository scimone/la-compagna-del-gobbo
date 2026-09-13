from apps.characters.api.details import router
from apps.characters.schemas import CharacterFeatSchema
from apps.characters.services import feats


@router.get("/{character_id}/feats", response=list[CharacterFeatSchema])
def list_character_feats(request, character_id: int):
    return feats.list_character_feats(character_id)
