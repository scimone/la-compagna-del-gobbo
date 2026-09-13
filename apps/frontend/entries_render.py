"""Render the 5etools-style `entries` JSON blobs (used across most `rules` models - Background,
Species, Class, Feat, Spell, ...) as safe, readable HTML.

The shapes handled here were enumerated directly from db/*.json (every distinct `type` value
that actually occurs across `features`/`lore`/`entries`/`entriesHigherLevel` fields), not
guessed: entries/section/inset (a heading + nested entries), list/item, table, options (a
"choose N" group), and refFeat/refOptionalfeature (a bare cross-reference to another catalog
entry, rendered as a plain mention - not a hyperlink, since resolving that link is a separate,
not-yet-built concern).
"""

import re

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

TAG_PATTERN = re.compile(r"\{@(\w+)\s+([^}]*)\}")


def _tag_display_text(tag: str, body: str) -> str:
    """Pick the human-readable portion out of a `{@tag ...}` body.

    5etools tags are `{@tag display|arg1|arg2|...}`. Observed convention in this data: `@filter`
    tags always want the first segment (the rest are query/filter parameters, not text); tags
    with 3+ segments generally want the *last* one (an explicit display-text override, e.g.
    `{@variantrule Cover|XPHB|Total Cover}` should read "Total Cover"); anything else wants the
    first segment.
    """
    segments = body.split("|")
    if tag == "filter":
        return segments[0]
    if len(segments) >= 3:
        return segments[-1]
    return segments[0]


def clean_text(text: str) -> str:
    """Strip `{@tag ...}` markup down to plain text. Safe to call on text with no tags at all."""
    return TAG_PATTERN.sub(lambda m: _tag_display_text(m.group(1), m.group(2)), text)


def render_entries(entries) -> SafeString:
    """Render an `entries`-shaped value (or a bare string/list) as safe HTML."""
    return mark_safe(_render_node(entries))


def _render_node(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return f"<p>{escape(clean_text(node))}</p>"
    if isinstance(node, list):
        return "".join(_render_node(item) for item in node)
    if isinstance(node, dict):
        return _render_dict(node)
    return f"<p>{escape(str(node))}</p>"


def _render_dict(node: dict) -> str:
    node_type = node.get("type")

    if node_type in ("entries", "section", "inset"):
        heading = node.get("name")
        heading_html = f"<h3>{escape(clean_text(heading))}</h3>" if heading else ""
        css_class = ' class="inset"' if node_type == "inset" else ""
        return f"<div{css_class}>{heading_html}{_render_node(node.get('entries', []))}</div>"

    if node_type == "list":
        items_html = "".join(_render_list_item(item) for item in node.get("items", []))
        return f"<ul>{items_html}</ul>"

    if node_type == "item":
        return _render_list_item(node)

    if node_type == "table":
        return _render_table(node)

    if node_type == "options":
        count = node.get("count")
        note = f"<p><em>{escape(_choose_note(count))}</em></p>" if count else ""
        return note + _render_node(node.get("entries", []))

    if node_type == "refFeat":
        name = _tag_display_text("refFeat", node.get("feat", ""))
        return f"<p>&rarr; {escape(name)}</p>"

    if node_type == "refOptionalfeature":
        name = _tag_display_text("refOptionalfeature", node.get("optionalfeature", ""))
        return f"<p>&rarr; {escape(name)}</p>"

    # Unknown shape - if it has nested entries, render those rather than dropping the content
    # silently; otherwise there's nothing safe to do with it.
    if "entries" in node:
        return _render_node(node["entries"])
    return ""


def _choose_note(count: int) -> str:
    return f"Choose {count}:" if count != 1 else "Choose one:"


def _render_list_item(item) -> str:
    if isinstance(item, str):
        return f"<li>{escape(clean_text(item))}</li>"
    if not isinstance(item, dict):
        return ""

    name = item.get("name")
    name_html = f"<strong>{escape(clean_text(name))}</strong> " if name else ""

    if "entry" in item:
        entry_val = item["entry"]
        if isinstance(entry_val, str):
            body = escape(clean_text(entry_val))
        else:
            body = _render_node(entry_val)
    else:
        body = _render_node(item.get("entries", []))

    return f"<li>{name_html}{body}</li>"


def render_key_value_table(rows, headers) -> SafeString:
    """Render a list of {header: value} dicts as an HTML table with the given header order -
    used for `rules.ClassLevel.columns`, which is already stored as one such dict per level.
    """
    header_html = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{escape(str(row.get(h, '')))}</td>" for h in headers) + "</tr>"
        for row in rows
    )
    return mark_safe(
        f"<table><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>"
    )


def _render_table(node: dict) -> str:
    caption = node.get("caption")
    caption_html = f"<caption>{escape(clean_text(caption))}</caption>" if caption else ""

    headers = node.get("colLabels", [])
    header_html = "".join(f"<th>{escape(clean_text(str(h)))}</th>" for h in headers)
    thead_html = f"<thead><tr>{header_html}</tr></thead>" if headers else ""

    body_html = "".join(
        "<tr>" + "".join(f"<td>{escape(clean_text(str(cell)))}</td>" for cell in row) + "</tr>"
        for row in node.get("rows", [])
    )

    return f"<table>{caption_html}{thead_html}<tbody>{body_html}</tbody></table>"
