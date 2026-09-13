"""Placeholder for GET ."""

from apps.characters.api.characters import router


@router.get("")
def list_characters(request):
    """List all characters. TODO: implement via services."""
