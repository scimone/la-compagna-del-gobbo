"""Tools that read this campaign's own data on demand - what the prompt leaves out to stay small:
`get_character_details` (backstory, appearance, notes, feature texts, inventory) and the logbook
(`search_logbook`, `read_logbook_entry`). Built per request for one user and campaign, so they
only reach what that user may already see in the app."""

from django.urls import reverse

from apps.ai.services import context
from apps.frontend import logbook
from apps.frontend.character_sheet import shown_backstory
from apps.frontend.handbook_search import text_blocks

MAX_RESULT_CHARS = 7000
MAX_SEARCH_HITS = 8

SECTIONS = ("backstory", "appearance", "notes", "features", "inventory")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_character_details",
            "description": (
                "Details of one character of this campaign that the compact sheets leave out: "
                "backstory, appearance, notes, the full text of their features, their inventory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "character": {"type": "string", "description": "The character's name or id"},
                    "sections": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(SECTIONS)},
                        "description": "Which parts (default: backstory, appearance, notes)",
                    },
                },
                "required": ["character"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_logbook",
            "description": "Search the campaign logbook (all entries, old ones too) for words.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_logbook_entry",
            "description": "Read one logbook entry in full, by its id (the number after #).",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        },
    },
]


def _clip(text: str) -> str:
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS].rstrip() + "\n[…cut]"


def _find_character(user, campaign, wanted) -> object | None:
    wanted = str(wanted).strip().casefold()
    characters = context.characters_for(user, campaign)
    for c in characters:
        if str(c.pk) == wanted or c.name.casefold() == wanted:
            return c
    return next((c for c in characters if wanted and wanted in c.name.casefold()), None)


def _character_details(user, campaign, args) -> tuple[str, dict]:
    ui = {"kind": "character", "query": str(args.get("character", "")), "title": "", "url": ""}
    character = _find_character(user, campaign, args.get("character", ""))
    if character is None:
        return "No such character.", {**ui, "error": "not found"}
    wanted = [s for s in (args.get("sections") or []) if s in SECTIONS] or [
        "backstory",
        "appearance",
        "notes",
    ]
    lines = [f"# {character.name}"]
    if "backstory" in wanted:
        story, _translated = shown_backstory(character)
        lines.append(f"Backstory: {story.strip() or '(none written)'}")
    if "appearance" in wanted:
        lines.append(f"Appearance: {character.appearance.strip() or '(none written)'}")
    if "notes" in wanted:
        lines.append(f"Notes: {character.notes.strip() or '(none written)'}")
    if "features" in wanted:
        lines.append("Features:")
        for row in character.features.select_related("feature"):
            text = " ".join(t for _p, t in text_blocks(row.feature.entries or []))
            lines.append(f"- {row.feature.name}: {text[:600]}")
        for custom in character.custom_features.all():
            lines.append(f"- {custom.name} (custom): {' '.join(custom.description.split())[:600]}")
    if "inventory" in wanted:
        lines.append("Inventory:")
        for item in character.inventory_items.select_related("equipment"):
            note = f" — {item.notes}" if item.notes else ""
            state = " (equipped)" if item.equipped else ""
            lines.append(f"- {item.equipment.name} x{item.quantity}{state}{note}")
        for custom in character.custom_items.all():
            lines.append(f"- {custom.name} x{custom.quantity} (custom)")
    ui.update(
        title=character.name,
        url=reverse("character-detail", args=[character.pk]),
        sections=wanted,
    )
    return _clip("\n".join(lines)), ui


def _entries(campaign):
    entries = logbook.list_entries(campaign)
    return entries, logbook.display(entries)


def _search_logbook(user, campaign, args) -> tuple[str, dict]:
    query = str(args.get("query", "")).strip()
    ui = {"kind": "logbook_search", "query": query, "count": 0, "hits": []}
    if len(query) < 2:
        return "Query too short.", {**ui, "error": "too short"}
    entries, shown = _entries(campaign)
    found = logbook.search(entries, query)
    ui["count"] = len(found)
    if not found:
        return "No logbook entries found.", ui
    lines = []
    for entry in found[-MAX_SEARCH_HITS:]:
        head = context.entry_head(entry, shown[entry.pk])
        text = " ".join(shown[entry.pk]["text"][0].split())
        lines.append(f"{head} {text[:200]}")
        ui["hits"].append(
            {
                "name": head.split("] ", 1)[1],
                "url": reverse("logbook-list"),
                "group": str(entry.date),
            }
        )
    return _clip("\n".join(lines)), ui


def _read_entry(user, campaign, args) -> tuple[str, dict]:
    ui = {"kind": "logbook_read", "query": str(args.get("id", "")), "title": "", "url": ""}
    entries, shown = _entries(campaign)
    wanted = str(args.get("id", "")).strip().lstrip("#")
    entry = next((e for e in entries if str(e.pk) == wanted), None)
    if entry is None:
        return "No such logbook entry.", {**ui, "error": "not found"}
    head = context.entry_head(entry, shown[entry.pk])
    ui.update(title=head.split("] ", 1)[1], url=reverse("logbook-list"))
    return _clip(f"{head}\n{shown[entry.pk]['text'][0].strip()}"), ui


_HANDLERS = {
    "get_character_details": _character_details,
    "search_logbook": _search_logbook,
    "read_logbook_entry": _read_entry,
}


def handles(name: str) -> bool:
    return name in _HANDLERS


def run_ui(user, campaign, name: str, arguments: dict) -> tuple[str, dict]:
    return _HANDLERS[name](user, campaign, arguments)
