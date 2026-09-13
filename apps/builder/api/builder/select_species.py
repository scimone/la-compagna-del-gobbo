"""Placeholder for POST /{character_id}/builder/species."""

from apps.builder.api.builder import router


@router.post("/{character_id}/builder/species")
def select_species(request, character_id: int):
    """Select the species for a character. TODO: implement via services."""
