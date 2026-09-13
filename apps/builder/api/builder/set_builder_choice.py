"""Placeholder for PUT /{character_id}/builder/choices/{choice_key}."""

from apps.builder.api.builder import router


@router.put("/{character_id}/builder/choices/{choice_key}")
def set_builder_choice(request, character_id: int, choice_key: str):
    """Resolve one builder choice. TODO: implement via services."""
