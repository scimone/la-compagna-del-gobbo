"""Placeholder for POST /{character_id}/builder/level-up/preview."""

from apps.builder.api.progression import router


@router.post("/{character_id}/builder/level-up/preview")
def preview_level_up(request, character_id: int):
    """Preview a level-up with pending choices applied. TODO: implement via services."""
