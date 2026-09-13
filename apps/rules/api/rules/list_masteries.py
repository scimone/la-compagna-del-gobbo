"""Placeholder for GET /masteries."""

from apps.rules.api.rules import router


@router.get("/masteries")
def list_masteries(request):
    """List all weapon masteries. TODO: implement via services."""
