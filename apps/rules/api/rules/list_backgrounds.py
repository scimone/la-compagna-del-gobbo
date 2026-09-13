"""Placeholder for GET /backgrounds."""

from apps.rules.api.rules import router


@router.get("/backgrounds")
def list_backgrounds(request):
    """List all backgrounds. TODO: implement via services."""
