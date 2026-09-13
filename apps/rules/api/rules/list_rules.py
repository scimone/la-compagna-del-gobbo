from apps.rules.api.rules import router
from apps.rules.schemas import RuleSchema
from apps.rules.services import rule


@router.get("/rules", response=list[RuleSchema])
def list_rules(request):
    return rule.list_rules()
