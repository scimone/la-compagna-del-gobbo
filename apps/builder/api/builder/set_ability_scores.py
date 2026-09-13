"""Placeholder for PUT /{character_id}/builder/ability-scores."""

from apps.builder.api.builder import router


@router.put("/{character_id}/builder/ability-scores")
def set_ability_scores(request, character_id: int):
    """Assign ability scores for a character. TODO: implement via services."""
