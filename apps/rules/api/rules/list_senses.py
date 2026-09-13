"""Placeholder for GET /senses."""

from apps.rules.api.rules import router


@router.get("/senses")
def list_senses(request):
    """List all senses. TODO: implement via services."""
