"""Placeholder for GET /equipment-properties."""

from apps.rules.api.rules import router


@router.get("/equipment-properties")
def list_equipment_properties(request):
    """List all equipment properties. TODO: implement via services."""
