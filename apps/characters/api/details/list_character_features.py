"""Placeholder for GET /{character_id}/features."""

from apps.characters.api.details import router


@router.get("/{character_id}/features")
def list_character_features(request, character_id: int):
    """List a character's features. TODO: implement via services."""
