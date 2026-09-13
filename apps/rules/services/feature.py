"""Feature lookups (list_features, get_feature)."""

from django.db.models import Q
from django.shortcuts import get_object_or_404

from apps.rules.models import Effect, Feature


def list_features():
    return Feature.objects.all()


def list_class_features():
    """Features granted by a Class or Subclass - excludes species traits and feat benefits,
    which are also `Feature` rows but not what "Class Features" means in the 2024 rules.
    """
    return Feature.objects.filter(
        Q(klass__isnull=False) | Q(subclass_level__isnull=False)
    ).select_related("klass", "subclass_level__subclass__klass")


def get_feature(feature_id: int) -> Feature:
    return get_object_or_404(Feature, pk=feature_id)


def list_feature_effects(feature_id: int):
    get_feature(feature_id)
    return Effect.objects.filter(feature_id=feature_id)
