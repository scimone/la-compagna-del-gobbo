"""The Logbook's rules: who may change an entry, and the list a page shows."""

from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.urls import reverse

from apps.characters.services import access
from apps.frontend import translations
from apps.frontend.handbook_search import fold, query_pattern
from apps.frontend.models import LogEntry


def _order(entry: LogEntry) -> tuple:
    personal = entry.kind == LogEntry.PERSONAL
    written = entry.created_at.timestamp()
    return (entry.date.toordinal(), not personal, written, entry.pk)


def list_entries() -> list[LogEntry]:
    """Oldest first, so the newest is at the bottom like in a chat. Within a day the personal
    messages come first and the objective entries follow under them, each in the order they were
    written."""
    return sorted(LogEntry.objects.select_related("author", "character"), key=_order)


DM_AVATAR = "images/dm-256.png"
DM_FULL = "images/dm-1024.png"


def avatar_url(entry: LogEntry) -> str:
    """The round picture of a personal entry's character, or "" (a silhouette is shown then).
    The DM's is a fixed static picture (`static/images/dm.webp`), shown zoomed in by the page."""
    if entry.as_dm:
        return static(DM_AVATAR) if finders.find(DM_AVATAR) else ""
    character = entry.character
    if character is None or not character.portrait:
        return ""
    version = (
        f"{character.portrait.name}-{character.portrait_cx:.4f}-"
        f"{character.portrait_cy:.4f}-{character.portrait_zoom:.3f}"
    )
    return f"{reverse('character-avatar', args=[character.pk])}?v={version}"


def full_url(entry: LogEntry) -> str:
    """The whole, unzoomed picture behind `avatar_url`, or "" when there is none."""
    if entry.as_dm:
        return static(DM_FULL) if finders.find(DM_FULL) else avatar_url(entry)
    character = entry.character
    if character is None or not character.portrait:
        return ""
    return f"{reverse('character-portrait', args=[character.pk])}?v={character.portrait.name}"


def can_edit(user, entry: LogEntry) -> bool:
    """The author, or an administrator. Anyone else - and a signed-out visitor - only reads."""
    if access.is_admin(user):
        return True
    return bool(
        getattr(user, "is_authenticated", False)
        and entry.author_id is not None
        and entry.author_id == user.id
    )


TEXT_FIELDS = ("title", "text")


def texts(entry: LogEntry) -> dict[str, str]:
    """What of an entry is translated: its title and text (not the date)."""
    return {name: getattr(entry, name) for name in TEXT_FIELDS}


def queue_translation(entry: LogEntry) -> None:
    translations.enqueue("logentry", entry.pk, texts(entry))


def search(entries: list[LogEntry], q: str) -> list[LogEntry]:
    """The entries with `q` in any text - as written or in either language's translation,
    ignoring case and accents."""
    pattern = query_pattern(q)
    haystacks = translations.search_text("logentry", {e.pk: texts(e) for e in entries})
    return [e for e in entries if pattern.search(fold(haystacks[e.pk]))]


def display(entries: list[LogEntry]) -> dict[int, dict[str, tuple[str, bool]]]:
    """`{entry pk: {field: (text to show, is it machine-translated)}}` in the active language."""
    return translations.translated_texts("logentry", {e.pk: texts(e) for e in entries})
