"""OptionalFeature lookups (list_optional_features, get_optional_feature)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import OptionalFeature


def list_optional_features():
    return OptionalFeature.objects.all()


def get_optional_feature(optional_feature_id: str) -> OptionalFeature:
    return get_object_or_404(OptionalFeature, pk=optional_feature_id)
