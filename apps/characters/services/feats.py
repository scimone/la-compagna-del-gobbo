"""Read-only listing of a character's chosen feats."""

from apps.characters.models import CharacterFeat
from apps.characters.services.character import get_character


def list_character_feats(character_id: int):
    get_character(character_id)
    return CharacterFeat.objects.filter(character_id=character_id)
