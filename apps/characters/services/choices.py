"""Read-only listing of a character's already-resolved builder choices."""

from apps.characters.models import CharacterChoice
from apps.characters.services.character import get_character


def list_character_choices(character_id: int):
    get_character(character_id)
    return CharacterChoice.objects.filter(character_id=character_id)
