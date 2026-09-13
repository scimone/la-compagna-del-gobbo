"""Read-only listing of a character's classes/subclasses and levels."""

from apps.characters.models import CharacterClass
from apps.characters.services.character import get_character


def list_character_classes(character_id: int):
    get_character(character_id)
    return CharacterClass.objects.filter(character_id=character_id)
