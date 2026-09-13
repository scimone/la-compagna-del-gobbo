"""Placeholder for GET /{character_id}/builder/level-up."""

from apps.builder.api.progression import router


@router.get("/{character_id}/builder/level-up")
def get_level_up_info(request, character_id: int):
    """Preview what the next level grants. TODO: implement via services."""
