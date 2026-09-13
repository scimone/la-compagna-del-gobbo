from apps.characters.api.spells import router
from apps.characters.schemas import CharacterSpellCreateSchema, CharacterSpellSchema
from apps.characters.services import spells


@router.post("/{character_id}/spells", response=CharacterSpellSchema)
def add_character_spell(request, character_id: int, payload: CharacterSpellCreateSchema):
    return spells.add_character_spell(character_id, **payload.dict(by_alias=True))
