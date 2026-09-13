from apps.rules.api.rules import router
from apps.rules.schemas import MasterySchema
from apps.rules.services import equipment


@router.get("/masteries", response=list[MasterySchema])
def list_masteries(request):
    return equipment.list_masteries()
