"""Feat lookups (list_feats, get_feat)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Feat


def list_feats():
    return Feat.objects.all()


def get_feat(feat_id: str) -> Feat:
    return get_object_or_404(Feat, pk=feat_id)


def list_categories() -> list[str]:
    """Every distinct `Feat.category` value, for the World > Feats filter dropdown. Built in
    Python, not `.values_list("category", flat=True).distinct()` - `Feat`'s default `ordering =
    ["name"]` would otherwise get folded into that query too, turning it into a de-facto
    `DISTINCT (category, name)` that doesn't dedupe at all.
    """
    return sorted({category for category in Feat.objects.values_list("category", flat=True)})
