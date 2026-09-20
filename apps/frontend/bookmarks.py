"""Which catalog a `Bookmark.kind` refers to, and the two lookups the views need."""

from apps.frontend.models import Bookmark
from apps.rules.models import Background, Class, Feat, Rule, Species, Spell

BOOKMARK_MODELS = {
    "background": Background,
    "class": Class,
    "feat": Feat,
    "species": Species,
    "spell": Spell,
    "rule": Rule,
}


def bookmarked_ids(kind: str) -> set[str]:
    return set(Bookmark.objects.filter(kind=kind).values_list("object_id", flat=True))


def is_bookmarked(kind: str, object_id: str) -> bool:
    return Bookmark.objects.filter(kind=kind, object_id=object_id).exists()
