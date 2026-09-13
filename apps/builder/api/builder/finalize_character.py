"""Placeholder for POST /{character_id}/builder/finalize."""

from apps.builder.api.builder import router


@router.post("/{character_id}/builder/finalize")
def finalize_character(request, character_id: int):
    """Finalize character creation. TODO: implement via services."""
