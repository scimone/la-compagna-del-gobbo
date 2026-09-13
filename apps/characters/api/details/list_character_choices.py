"""Placeholder for GET /{character_id}/choices."""

from apps.characters.api.details import router


@router.get("/{character_id}/choices")
def list_character_choices(request, character_id: int):
    """List a character's already-resolved builder choices.

    Distinct from `GET /{character_id}/builder/choices` (the builder app's endpoint), which
    lists outstanding/available choices still to be made - this reads what's already been
    decided. TODO: implement via services.
    """
