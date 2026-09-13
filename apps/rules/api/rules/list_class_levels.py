from apps.rules.api.rules import router
from apps.rules.schemas import ClassLevelSchema
from apps.rules.services import class_


@router.get("/classes/{class_id}/levels", response=list[ClassLevelSchema])
def list_class_levels(request, class_id: str):
    return class_.list_class_levels(class_id)
