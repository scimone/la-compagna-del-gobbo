"""Placeholder for GET /spells/{spell_id}."""

from apps.rules.api.rules import router


@router.get("/spells/{spell_id}")
def get_spell(request, spell_id: str):
    """Retrieve a spell. TODO: implement via services."""
