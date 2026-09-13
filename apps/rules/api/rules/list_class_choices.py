from apps.rules.api.rules import router
from apps.rules.schemas import ChoiceDefinitionSchema
from apps.rules.services import class_


@router.get("/classes/{class_id}/choices", response=list[ChoiceDefinitionSchema])
def list_class_choices(request, class_id: str):
    return class_.list_class_choices(class_id)
