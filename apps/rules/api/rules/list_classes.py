"""Placeholder for GET /classes."""

from apps.rules.api.rules import router


@router.get("/classes")
def list_classes(request):
    """List all classes. TODO: implement via services."""
