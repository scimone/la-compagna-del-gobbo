"""Placeholder for GET /subclasses/{subclass_id}/levels."""

from apps.rules.api.rules import router


@router.get("/subclasses/{subclass_id}/levels")
def list_subclass_levels(request, subclass_id: int):
    """List the level progression rows for a subclass. TODO: implement via services."""
