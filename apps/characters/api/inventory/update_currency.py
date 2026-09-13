from apps.characters.api.inventory import router
from apps.characters.schemas import CharacterCurrencySchema, CharacterCurrencyUpdateSchema
from apps.characters.services import currency


@router.patch("/{character_id}/currency", response=CharacterCurrencySchema)
def update_currency(request, character_id: int, payload: CharacterCurrencyUpdateSchema):
    return currency.update_currency(character_id, **payload.dict(exclude_unset=True, by_alias=True))
