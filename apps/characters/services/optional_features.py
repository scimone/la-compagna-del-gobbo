"""Read-only listing of a character's chosen invocations/maneuvers/metamagic."""

from apps.characters.models import CharacterOptionalFeature
from apps.characters.services.character import get_character


def list_character_optional_features(character_id: int):
    get_character(character_id)
    return CharacterOptionalFeature.objects.filter(character_id=character_id)
