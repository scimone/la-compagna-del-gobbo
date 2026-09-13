"""Placeholder for POST /{character_id}/builder/class."""

from apps.builder.api.builder import router


@router.post("/{character_id}/builder/class")
def select_class(request, character_id: int):
    """Select a class for a character.

    Also the multiclassing entry point: `characters.CharacterClass` allows multiple rows per
    character, so calling this again with a different class adds a second class rather than
    replacing the first. TODO: implement via services.
    """
