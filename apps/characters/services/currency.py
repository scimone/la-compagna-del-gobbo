"""Character currency management (get_currency, update_currency)."""

from apps.characters.models import CharacterCurrency
from apps.characters.services.character import get_character


def get_currency(character_id: int) -> CharacterCurrency:
    character = get_character(character_id)
    currency, _ = CharacterCurrency.objects.get_or_create(character=character)
    return currency


def update_currency(character_id: int, **data) -> CharacterCurrency:
    currency = get_currency(character_id)
    for field, value in data.items():
        setattr(currency, field, value)
    currency.save()
    return currency
