"""HandbookChapter/HandbookSection lookups (list_chapters, list_sections, get_section)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import HandbookChapter, HandbookSection


def list_chapters():
    """Every chapter, each with its sections prefetched (in reading order) as `.sections`."""
    return HandbookChapter.objects.prefetch_related("sections")


def list_sections():
    return HandbookSection.objects.all()


def get_section(section_id: str) -> HandbookSection:
    return get_object_or_404(HandbookSection, pk=section_id)
