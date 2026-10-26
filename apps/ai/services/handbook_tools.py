"""The tools the model may call to look things up in the rules (OpenAI-style function calling):
`search_handbook` finds pages, `read_page` returns one page's text. Both return plain text with
the app's own page addresses, which the model is told to use as links in its answers."""

import re

from django.urls import Resolver404, resolve, reverse
from django.utils.html import strip_tags

from apps.frontend.handbook_search import text_blocks
from apps.rules import models as rules

MAX_RESULT_CHARS = 7000
MAX_SEARCH_HITS = 6

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
    return re.sub(r"\s+", " ", strip_tags(str(text))).strip()


def _clip(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[…cut]"


def search_handbook(query: str, category: str = "") -> str:
    from apps.frontend import views

    query = str(query).strip()
    if len(query) < 2:
        return "Query too short."
    groups = views._global_search(query)
    if category:
        groups = [g for g in groups if g["key"] == category]
    if not groups:
        return "No pages found."
    lines = []
    for group in groups:
        lines.append(f"## {_collapse(group['label'])} ({group['total']} found)")
        for item in group["items"][:MAX_SEARCH_HITS]:
            lines.append(
                f"- {_collapse(item['name'])} — {item['url']} — {_collapse(item['detail'])[:260]}"
            )
    return _clip("\n".join(lines))


def read_page(path: str) -> str:
    try:
        match = resolve(str(path).split("?")[0])
    except Resolver404:
        return "No such page."
    spec = _PAGES.get(match.url_name)
    if spec is None:
        return "That page cannot be read with this tool."
    model, facts, fields = spec
    obj = model.objects.filter(pk=match.kwargs.get("pk")).first()
    if obj is None:
        return "No such page."
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
    return _clip("\n\n".join(lines))


def run(name: str, arguments: dict) -> str:
    if name == "search_handbook":
        return search_handbook(arguments.get("query", ""), arguments.get("category", ""))
    if name == "read_page":
        return read_page(arguments.get("path", ""))
    return f"Unknown tool {name}."
