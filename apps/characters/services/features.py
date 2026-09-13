"""Read-only listing of a character's granted features."""

from apps.characters.models import CharacterFeature
from apps.characters.services.character import get_character


def list_character_features(character_id: int):
    get_character(character_id)
    return CharacterFeature.objects.filter(character_id=character_id)
