"""HandbookSection lookups (list_sections, get_section)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import HandbookSection


def list_sections():
    return HandbookSection.objects.all()


def get_section(section_id: str) -> HandbookSection:
    return get_object_or_404(HandbookSection, pk=section_id)
