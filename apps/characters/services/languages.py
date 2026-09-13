"""Read-only listing of a character's known languages."""

from apps.characters.models import CharacterLanguage
from apps.characters.services.character import get_character


def list_character_languages(character_id: int):
    get_character(character_id)
    return CharacterLanguage.objects.filter(character_id=character_id)
