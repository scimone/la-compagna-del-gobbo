"""Named Rule lookups (list_rules, get_rule) and the glossary's conditions."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Condition, Rule


def list_rules():
    return Rule.objects.all()


def get_rule(rule_key: str) -> Rule:
    return get_object_or_404(Rule, pk=rule_key)


def list_conditions():
    return Condition.objects.all()


def get_condition(condition_id: str) -> Condition:
    return get_object_or_404(Condition, pk=condition_id)
