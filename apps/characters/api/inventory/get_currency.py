from apps.characters.api.inventory import router
from apps.characters.schemas import CharacterCurrencySchema
from apps.characters.services import currency


@router.get("/{character_id}/currency", response=CharacterCurrencySchema)
def get_currency(request, character_id: int):
    return currency.get_currency(character_id)
