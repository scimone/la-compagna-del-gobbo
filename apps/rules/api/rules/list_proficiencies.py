from apps.rules.api.rules import router
from apps.rules.schemas import ProficiencySchema
from apps.rules.services import proficiency


@router.get("/proficiencies", response=list[ProficiencySchema])
def list_proficiencies(request):
    return proficiency.list_proficiencies()
