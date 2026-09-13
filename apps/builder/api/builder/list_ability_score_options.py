"""Placeholder for GET /{character_id}/builder/ability-options."""

from apps.builder.api.builder import router


@router.get("/{character_id}/builder/ability-options")
def list_ability_score_options(request, character_id: int):
    """List the available ability score assignment options. TODO: implement via services."""
