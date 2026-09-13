"""Read-only listing of a character's senses."""

from apps.characters.models import CharacterSense
from apps.characters.services.character import get_character


def list_character_senses(character_id: int):
    get_character(character_id)
    return CharacterSense.objects.filter(character_id=character_id)
