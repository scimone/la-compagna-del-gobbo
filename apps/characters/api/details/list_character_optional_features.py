"""Placeholder for GET /{character_id}/optional-features."""

from apps.characters.api.details import router


@router.get("/{character_id}/optional-features")
def list_character_optional_features(request, character_id: int):
    """List a character's chosen invocations/maneuvers/metamagic. TODO: implement."""
