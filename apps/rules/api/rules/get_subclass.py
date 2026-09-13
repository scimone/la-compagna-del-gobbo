from apps.rules.api.rules import router
from apps.rules.schemas import SubclassSchema
from apps.rules.services import subclass


@router.get("/subclasses/{subclass_id}", response=SubclassSchema)
def get_subclass(request, subclass_id: int):
    return subclass.get_subclass(subclass_id)
