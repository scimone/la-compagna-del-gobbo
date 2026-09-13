"""Placeholder for GET /{character_id}/builder/choices/{choice_key}."""

from apps.builder.api.builder import router


@router.get("/{character_id}/builder/choices/{choice_key}")
def get_builder_choice(request, character_id: int, choice_key: str):
    """Retrieve one builder choice and its options. TODO: implement via services."""
