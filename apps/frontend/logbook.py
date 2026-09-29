"""The Logbook's rules: who may change an entry, and the list a page shows."""

from apps.characters.services import access
from apps.frontend import translations
from apps.frontend.handbook_search import fold, query_pattern
from apps.frontend.models import LogEntry


def list_entries():
    """Newest session first (see `LogEntry.Meta.ordering`)."""
    return LogEntry.objects.select_related("author")


def can_edit(user, entry: LogEntry) -> bool:
    """The author, or an administrator. Anyone else - and a signed-out visitor - only reads."""
    if access.is_admin(user):
        return True
    return bool(
        getattr(user, "is_authenticated", False)
        and entry.author_id is not None
        and entry.author_id == user.id
    )


TEXT_FIELDS = ("title", "location", "characters_met", "fights", "objectives", "insights", "notes")


def texts(entry: LogEntry) -> dict[str, str]:
    """What of an entry is translated: every free-text field (not the date)."""
    return {name: getattr(entry, name) for name in TEXT_FIELDS}


def queue_translation(entry: LogEntry) -> None:
    translations.enqueue("logentry", entry.pk, texts(entry))


def search(entries: list[LogEntry], q: str) -> list[LogEntry]:
    """The entries with `q` in any text - as written or in either language's translation,
    ignoring case and accents - plus the author's name."""
    pattern = query_pattern(q)
    haystacks = translations.search_text("logentry", {e.pk: texts(e) for e in entries})
    return [
        e
        for e in entries
        if pattern.search(
            fold(haystacks[e.pk] + "\n" + (e.author.get_username() if e.author else ""))
        )
    ]


def display(entries: list[LogEntry]) -> dict[int, dict[str, tuple[str, bool]]]:
    """`{entry pk: {field: (text to show, is it machine-translated)}}` in the active language."""
    return translations.translated_texts("logentry", {e.pk: texts(e) for e in entries})
