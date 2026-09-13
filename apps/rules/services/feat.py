"""Feat lookups (list_feats, get_feat)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Feat


def list_feats():
    return Feat.objects.all()


def get_feat(feat_id: str) -> Feat:
    return get_object_or_404(Feat, pk=feat_id)
