"""Placeholder for GET /{character_id}/resources."""

from apps.characters.api.details import router


@router.get("/{character_id}/resources")
def list_character_resources(request, character_id: int):
    """List a character's limited-use resources. TODO: implement via services."""
