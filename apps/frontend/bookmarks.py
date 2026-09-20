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


def bookmarked_ids(user, kind: str) -> set[str]:
    if not user.is_authenticated:
        return set()
    return set(Bookmark.objects.filter(user=user, kind=kind).values_list("object_id", flat=True))


def is_bookmarked(user, kind: str, object_id: str) -> bool:
    return (
        user.is_authenticated
        and Bookmark.objects.filter(user=user, kind=kind, object_id=object_id).exists()
    )
