"""Placeholder for POST /{character_id}/builder/validate."""

from apps.builder.api.validation import router


@router.post("/{character_id}/builder/validate")
def validate_character(request, character_id: int):
    """Re-run validation for a character. TODO: implement via services."""
