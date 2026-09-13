"""Placeholder for GET /classes/{class_id}/levels."""

from apps.rules.api.rules import router


@router.get("/classes/{class_id}/levels")
def list_class_levels(request, class_id: str):
    """List the level progression rows for a class. TODO: implement via services."""
