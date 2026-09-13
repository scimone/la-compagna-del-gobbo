from apps.rules.api.rules import router
from apps.rules.schemas import SubclassSchema
from apps.rules.services import subclass


@router.get("/subclasses", response=list[SubclassSchema])
def list_subclasses(request):
    return subclass.list_subclasses()
