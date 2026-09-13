from apps.rules.api.rules import router
from apps.rules.schemas import SubclassSchema
from apps.rules.services import class_


@router.get("/classes/{class_id}/subclasses", response=list[SubclassSchema])
def list_class_subclasses(request, class_id: str):
    return class_.list_class_subclasses(class_id)
