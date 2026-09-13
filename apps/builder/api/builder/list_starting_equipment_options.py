"""Placeholder for GET /{character_id}/builder/starting-equipment."""

from apps.builder.api.builder import router


@router.get("/{character_id}/builder/starting-equipment")
def list_starting_equipment_options(request, character_id: int):
    """List the available starting equipment options. TODO: implement via services."""
