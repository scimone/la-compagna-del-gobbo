"""Placeholder for GET /languages."""

from apps.rules.api.rules import router


@router.get("/languages")
def list_languages(request):
    """List all languages. TODO: implement via services."""
