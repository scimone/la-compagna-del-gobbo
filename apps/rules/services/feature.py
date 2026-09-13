"""Feature lookups (list_features, get_feature)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Effect, Feature


def list_features():
    return Feature.objects.all()


def get_feature(feature_id: int) -> Feature:
    return get_object_or_404(Feature, pk=feature_id)


def list_feature_effects(feature_id: int):
    get_feature(feature_id)
    return Effect.objects.filter(feature_id=feature_id)
