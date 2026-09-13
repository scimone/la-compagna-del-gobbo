from apps.rules.api.rules import router
from apps.rules.schemas import ClassSchema
from apps.rules.services import class_


@router.get("/classes/{class_id}", response=ClassSchema)
def get_class(request, class_id: str):
    return class_.get_class(class_id)
