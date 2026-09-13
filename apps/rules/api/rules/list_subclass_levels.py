from apps.rules.api.rules import router
from apps.rules.schemas import SubclassLevelSchema
from apps.rules.services import subclass


@router.get("/subclasses/{subclass_id}/levels", response=list[SubclassLevelSchema])
def list_subclass_levels(request, subclass_id: int):
    return subclass.list_subclass_levels(subclass_id)
