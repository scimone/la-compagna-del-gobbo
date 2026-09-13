"""Skill lookups (list_skills)."""

from apps.rules.models import Skill


def list_skills():
    return Skill.objects.all()
