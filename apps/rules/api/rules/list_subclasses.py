"""Placeholder for GET /subclasses."""

from apps.rules.api.rules import router


@router.get("/subclasses")
def list_subclasses(request):
    """List all subclasses. TODO: implement via services."""
