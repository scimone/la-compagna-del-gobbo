"""Placeholder for GET /backgrounds/{background_id}/choices."""

from apps.rules.api.rules import router


@router.get("/backgrounds/{background_id}/choices")
def list_background_choices(request, background_id: str):
    """List the parsed choice definitions for a background. TODO: implement via services."""
