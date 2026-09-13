"""Placeholder for GET /backgrounds/{background_id}."""

from apps.rules.api.rules import router


@router.get("/backgrounds/{background_id}")
def get_background(request, background_id: str):
    """Retrieve a background. TODO: implement via services."""
