from apps.rules.api.rules import router
from apps.rules.schemas import SpellSchema
from apps.rules.services import spell


@router.get("/spells/{spell_id}", response=SpellSchema)
def get_spell(request, spell_id: str):
    return spell.get_spell(spell_id)
