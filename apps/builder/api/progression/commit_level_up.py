"""Placeholder for POST /{character_id}/builder/level-up/commit."""

from apps.builder.api.progression import router


@router.post("/{character_id}/builder/level-up/commit")
def commit_level_up(request, character_id: int):
    """Commit a level-up. TODO: implement via services."""
