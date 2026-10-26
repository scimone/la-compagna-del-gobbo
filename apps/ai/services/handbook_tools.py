"""The tools the model may call to look things up in the rules (OpenAI-style function calling):
`search_handbook` finds pages, `read_page` returns one page's text. Both return plain text with
the app's own page addresses, which the model is told to use as links in its answers."""

import html
import re

from django.urls import Resolver404, resolve, reverse
from django.utils.html import strip_tags

from apps.frontend.handbook_search import text_blocks
from apps.rules import models as rules

MAX_RESULT_CHARS = 7000
MAX_SEARCH_HITS = 6
MAX_UI_HITS = 8

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_handbook",
            "description": (
                "Search the D&D 5.5e (2024) handbook of this app: rules and glossary, conditions, "
                "backgrounds, classes and subclasses, species, feats, class features and options, "
                "spells and equipment. Returns matching pages with their address (path)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Words to look for, 2+ letters"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "rules",
                            "backgrounds",
                            "classes",
                            "species",
                            "features",
                            "spells",
                            "items",
                        ],
                        "description": "Only this category (optional)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_page",
            "description": (
                "Read the full text of one handbook page, given its path from search_handbook "
                "(for example /world/spells/fireball/)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]

#: url name -> (model, extra fields to show, text fields). The page's own `pk` kwarg.
_PAGES = {
    "world-spell-detail": (
        rules.Spell,
        ("level", "school", "concentration", "ritual"),
        ("entries", "entries_higher_level"),
    ),
    "world-feat-detail": (rules.Feat, ("category",), ("entries",)),
    "world-background-detail": (rules.Background, (), ("lore", "entries")),
    "world-species-detail": (rules.Species, ("speed",), ("lore", "entries")),
    "world-class-detail": (rules.Class, ("hit_die", "caster_progression"), ("lore",)),
    "world-item-detail": (
        rules.Equipment,
        (
            "weapon_category",
            "damage_dice",
            "damage_type",
            "versatile_damage_dice",
            "ac",
            "weight",
            "value",
        ),
        ("entries",),
    ),
    "world-rule-detail": (rules.Rule, (), ("entries",)),
    "world-condition-detail": (rules.Condition, (), ("entries",)),
    "world-sense-detail": (rules.Sense, (), ("entries",)),
    "handbook-section-detail": (rules.HandbookSection, (), ("entries",)),
    "world-feature-detail": (rules.Feature, (), ("entries",)),
    "world-option-detail": (rules.OptionalFeature, ("feature_type",), ("entries",)),
}


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(strip_tags(str(text)))).strip()


def _clip(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[…cut]"


def _search(query: str, category: str = "") -> tuple[str, dict]:
    """(text for the model, what the page shows: query, total and the first few hits)."""
    from apps.frontend import views

    query = str(query).strip()
    ui = {"kind": "search", "query": query, "count": 0, "hits": []}
    if len(query) < 2:
        return "Query too short.", {**ui, "error": "too short"}
    groups = views._global_search(query)
    if category:
        groups = [g for g in groups if g["key"] == category]
    if not groups:
        return "No pages found.", ui
    lines, picked = [], []
    for group in groups:
        label = _collapse(group["label"])
        lines.append(f"## {label} ({group['total']} found)")
        ui["count"] += group["total"]
        rows = []
        for item in group["items"][:MAX_SEARCH_HITS]:
            name = _collapse(item["name"])
            lines.append(f"- {name} — {item['url']} — {_collapse(item['detail'])[:260]}")
            rows.append({"name": name, "url": item["url"], "group": label})
        picked.append(rows)
    # The chips on the page: the best row of each category first, then the next best, ...
    for rank in range(MAX_SEARCH_HITS):
        for rows in picked:
            if rank < len(rows) and len(ui["hits"]) < MAX_UI_HITS:
                ui["hits"].append(rows[rank])
    return _clip("\n".join(lines)), ui


def search_handbook(query: str, category: str = "") -> str:
    return _search(query, category)[0]


def _read(path: str) -> tuple[str, dict]:
    ui = {"kind": "read", "title": str(path), "url": ""}
    try:
        match = resolve(str(path).split("?")[0])
    except Resolver404:
        return "No such page.", {**ui, "error": "not found"}
    spec = _PAGES.get(match.url_name)
    if spec is None:
        return "That page cannot be read with this tool.", {**ui, "error": "not readable"}
    model, facts, fields = spec
    obj = model.objects.filter(pk=match.kwargs.get("pk")).first()
    if obj is None:
        return "No such page.", {**ui, "error": "not found"}
    lines = [f"# {_collapse(obj.name)}  ({path})"]
    for name in facts:
        value = getattr(obj, name, None)
        if value not in (None, "", False):
            lines.append(f"{name}: {value}")
    for name in fields:
        blocks = [t for _path, t in text_blocks(getattr(obj, name, None) or []) if t.strip()]
        if blocks:
            lines.append("\n".join(blocks))
    if isinstance(obj, rules.Class):
        features = rules.Feature.objects.filter(class_level__klass=obj).select_related(
            "class_level"
        )
        lines.append("Class features (open each with read_page):")
        for feature in sorted(features, key=lambda f: (f.class_level.level, f.name)):
            lines.append(
                f"- Level {feature.class_level.level}: {feature.name} — "
                f"{reverse('world-feature-detail', args=[feature.pk])}"
            )
    ui.update(title=_collapse(obj.name), url=str(path).split("?")[0])
    return _clip("\n\n".join(lines)), ui


def read_page(path: str) -> str:
    return _read(path)[0]


def run_ui(name: str, arguments: dict) -> tuple[str, dict]:
    """Run a tool: (text for the model, summary of what was looked up for the chat page)."""
    if name == "search_handbook":
        return _search(arguments.get("query", ""), arguments.get("category", ""))
    if name == "read_page":
        return _read(arguments.get("path", ""))
    return f"Unknown tool {name}.", {"kind": "unknown", "error": name}


def run(name: str, arguments: dict) -> str:
    return run_ui(name, arguments)[0]
