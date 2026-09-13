from apps.characters.api.characters import router
from apps.characters.schemas import CharacterCreateSchema, CharacterOutSchema
from apps.characters.services import character


@router.post("/", response=CharacterOutSchema)
def create_character(request, payload: CharacterCreateSchema):
    return character.create_character(**payload.dict(by_alias=True))
