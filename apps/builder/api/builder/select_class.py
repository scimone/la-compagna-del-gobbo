"""Placeholder for POST /{character_id}/builder/class."""

from apps.builder.api.builder import router


@router.post("/{character_id}/builder/class")
def select_class(request, character_id: int):
    """Select the class for a character. TODO: implement via services."""
