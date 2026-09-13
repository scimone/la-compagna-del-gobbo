"""Placeholder for POST /{character_id}/builder/starting-equipment."""

from apps.builder.api.builder import router


@router.post("/{character_id}/builder/starting-equipment")
def choose_starting_equipment(request, character_id: int):
    """Choose starting equipment for a character. TODO: implement via services."""
