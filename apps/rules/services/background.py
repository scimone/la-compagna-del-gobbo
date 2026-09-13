"""Background lookups (list_backgrounds, get_background)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Background, ChoiceDefinition


def list_backgrounds():
    return Background.objects.all()


def get_background(background_id: str) -> Background:
    return get_object_or_404(Background, pk=background_id)


def list_background_choices(background_id: str):
    get_background(background_id)
    return ChoiceDefinition.objects.filter(background_id=background_id)
