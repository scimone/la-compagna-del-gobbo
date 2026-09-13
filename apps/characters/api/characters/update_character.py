from apps.characters.api.characters import router
from apps.characters.schemas import CharacterOutSchema, CharacterUpdateSchema
from apps.characters.services import character


@router.patch("/{character_id}", response=CharacterOutSchema)
def update_character(request, character_id: int, payload: CharacterUpdateSchema):
    return character.update_character(
        character_id, **payload.dict(exclude_unset=True, by_alias=True)
    )
