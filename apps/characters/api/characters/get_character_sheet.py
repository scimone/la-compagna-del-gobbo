"""Placeholder for GET /{character_id}/sheet."""

from apps.characters.api.characters import router


@router.get("/{character_id}/sheet")
def get_character_sheet(request, character_id: int):
    """Retrieve the resolved character sheet. TODO: implement via services."""
