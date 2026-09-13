from apps.rules.api.rules import router
from apps.rules.schemas import SenseSchema
from apps.rules.services import sense


@router.get("/senses", response=list[SenseSchema])
def list_senses(request):
    return sense.list_senses()
