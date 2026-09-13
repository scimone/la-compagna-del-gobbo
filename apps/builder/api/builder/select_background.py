"""Placeholder for POST /{character_id}/builder/background."""

from apps.builder.api.builder import router


@router.post("/{character_id}/builder/background")
def select_background(request, character_id: int):
    """Select the background for a character. TODO: implement via services."""
