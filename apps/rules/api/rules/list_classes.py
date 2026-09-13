from apps.rules.api.rules import router
from apps.rules.schemas import ClassSchema
from apps.rules.services import class_


@router.get("/classes", response=list[ClassSchema])
def list_classes(request):
    return class_.list_classes()
