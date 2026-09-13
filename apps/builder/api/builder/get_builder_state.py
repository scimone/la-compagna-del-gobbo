"""Placeholder for GET /{character_id}/builder."""

from apps.builder.api.builder import router


@router.get("/{character_id}/builder")
def get_builder_state(request, character_id: int):
    """Retrieve the overall builder state for a character. TODO: implement via services."""
