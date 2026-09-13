"""Placeholder for GET /{character_id}/feats."""

from apps.characters.api.details import router


@router.get("/{character_id}/feats")
def list_character_feats(request, character_id: int):
    """List a character's chosen feats. TODO: implement via services."""
