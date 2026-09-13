"""Placeholder for GET /{character_id}/builder/validation."""

from apps.builder.api.validation import router


@router.get("/{character_id}/builder/validation")
def get_builder_validation(request, character_id: int):
    """Retrieve the last validation result for a character. TODO: implement via services."""
