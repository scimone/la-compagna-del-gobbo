"""Placeholder for POST ."""

from apps.characters.api.characters import router


@router.post("")
def create_character(request):
    """Create a character. TODO: implement via services."""
