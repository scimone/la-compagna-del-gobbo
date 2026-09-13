from apps.rules.api.rules import router
from apps.rules.schemas import RuleSchema
from apps.rules.services import rule


@router.get("/rules/{rule_key}", response=RuleSchema)
def get_rule(request, rule_key: str):
    return rule.get_rule(rule_key)
