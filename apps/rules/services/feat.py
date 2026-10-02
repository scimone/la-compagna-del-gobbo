"""Feat lookups (list_feats, get_feat)."""

from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404

from apps.rules.models import Feat


def list_feats():
    return Feat.objects.all()


def get_feat(feat_id: str) -> Feat:
    return get_object_or_404(Feat, pk=feat_id)


# The order the World > Feats category pills are offered in - roughly by when a character gets
# them, not alphabetically. A category missing from here (none today) sorts after these, by name.
_CATEGORY_ORDER = ["Origin", "General", "Fighting Style", "Epic Boon"]


def _category_sort_key(category: str) -> tuple:
    if category in _CATEGORY_ORDER:
        return (_CATEGORY_ORDER.index(category), category)
    return (len(_CATEGORY_ORDER), category)


def list_categories() -> list[str]:
    """Every distinct `Feat.category` *group* - a parenthesized sub-variant (`_decode_code()`'s
    `"FS:R"`/`"FS:P"` handling in `import_rules_data.py`, currently only ever "Fighting Style
    (P)"/"Fighting Style (R)") collapses into its base category ("Fighting Style") here, so the
    World > Feats filter offers one "Fighting Style" pill instead of three near-duplicates -
    `matching_category()` below matches a selection back against every sub-variant it stands for.
    Built in Python, not `.values_list("category", flat=True).distinct()` - `Feat`'s default
    `ordering = ["name"]` would otherwise get folded into that query too, turning it into a
    de-facto `DISTINCT (category, name)` that doesn't dedupe at all.
    """
    return sorted(
        {category.split(" (")[0] for category in Feat.objects.values_list("category", flat=True)},
        key=_category_sort_key,
    )


def matching_category(feats: QuerySet[Feat], category: str) -> QuerySet[Feat]:
    """Narrow `feats` to `category` itself or one of its parenthesized sub-variants - see
    `list_categories()`.
    """
    return feats.filter(Q(category=category) | Q(category__startswith=f"{category} ("))


def matching_categories(feats: QuerySet[Feat], categories) -> QuerySet[Feat]:
    """`matching_category()` for several categories at once - feats in any of them."""
    query = Q()
    for category in categories:
        query |= Q(category=category) | Q(category__startswith=f"{category} (")
    return feats.filter(query)
