"""Named Rule lookups (list_rules, get_rule)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Rule


def list_rules():
    return Rule.objects.all()


def get_rule(rule_key: str) -> Rule:
    return get_object_or_404(Rule, pk=rule_key)
