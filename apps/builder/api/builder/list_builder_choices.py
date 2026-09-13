"""Placeholder for GET /{character_id}/builder/choices."""

from apps.builder.api.builder import router


@router.get("/{character_id}/builder/choices")
def list_builder_choices(request, character_id: int):
    """List outstanding builder choices. TODO: implement via services."""
