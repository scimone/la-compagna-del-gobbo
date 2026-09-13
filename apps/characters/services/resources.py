"""Read-only listing of a character's limited-use resources."""

from apps.characters.models import CharacterResource
from apps.characters.services.character import get_character


def list_character_resources(character_id: int):
    get_character(character_id)
    return CharacterResource.objects.filter(character_id=character_id)
