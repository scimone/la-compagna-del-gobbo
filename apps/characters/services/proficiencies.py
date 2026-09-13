"""Read-only listing of a character's proficiencies."""

from apps.characters.models import CharacterProficiency
from apps.characters.services.character import get_character


def list_character_proficiencies(character_id: int):
    get_character(character_id)
    return CharacterProficiency.objects.filter(character_id=character_id)
