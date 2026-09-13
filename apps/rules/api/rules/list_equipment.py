"""Placeholder for GET /equipment."""

from apps.rules.api.rules import router


@router.get("/equipment")
def list_equipment(request):
    """List all equipment. TODO: implement via services."""
