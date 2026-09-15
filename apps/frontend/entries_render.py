"""Render the 5etools-style `entries` JSON blobs (used across most `rules` models - Background,
Species, Class, Feat, Spell, ...) as safe, readable HTML.

The shapes handled here were enumerated directly from db/*.json (every distinct `type` value
that actually occurs across `features`/`lore`/`entries`/`entriesHigherLevel` fields), not
guessed: entries/section/inset (a heading + nested entries), list/item, table, options (a
"choose N" group), and refFeat/refOptionalfeature (a bare cross-reference to another catalog
entry, rendered as a plain mention - not a hyperlink, since resolving *those* links would need
a `CharacterFeat`/`CharacterOptionalFeature`-style *choice* context this renderer doesn't have,
not just a name lookup). `{@variantrule ...}`, `{@spell ...}` and `{@feat ...}` references *do*
become real links, since those three catalogs (`rules.Rule`/`Spell`/`Feat`) each already have a
detail page and a name to match against - see `_ReferenceLinker` below. Verified against every
occurrence of all three tags in db/ before relying on the name match: 50/51 variantrule
references, 102/102 spell references, and 19/19 feat references resolve.

`render_trait_cards()`, `render_class_features()` and `render_subclasses()` are separate entry
points (not part of the generic `render_entries()` recursion) for the spots that need a distinct
visual per named block instead of plain stacked headings: a Species' traits, a Class's per-level
features, and a Class's subclasses (each subclass reusing the same per-level card grouping as
`render_class_features()`).
"""

import re

from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext

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


# Which {@tag ...} types become real links, and where to look each one up: (model, url name).
# Matched by name, case-insensitively - there's no reliable way to derive a catalog row's slug
# id from the tag text, but every one of these models already stores its own `name`.
_LINKABLE_TAGS = {
    "variantrule": ("rules.Rule", "world-rule-detail"),
    "spell": ("rules.Spell", "world-spell-detail"),
    "feat": ("rules.Feat", "world-feat-detail"),
}


class _ReferenceLinker:
    """Resolves `{@variantrule/spell/feat ...}` references to their catalog row's detail page.

    Built once per top-level `render_entries()` call and threaded through the recursive render
    functions, rather than querying per tag occurrence - each of these catalogs is small and
    mostly static (114/391/77 rows), so one query per catalog per page render is plenty.
    """

    def __init__(self):
        from django.apps import apps as django_apps

        self._lookups = {}
        for tag, (model_label, url_name) in _LINKABLE_TAGS.items():
            model = django_apps.get_model(model_label)
            pk_by_name = {obj.name.lower(): obj.pk for obj in model.objects.only("pk", "name")}
            self._lookups[tag] = (pk_by_name, url_name)

    def url_for(self, tag: str, ref_name: str) -> str | None:
        lookup = self._lookups.get(tag)
        if not lookup:
            return None
        pk_by_name, url_name = lookup
        pk = pk_by_name.get(ref_name.strip().lower())
        return reverse(url_name, args=[pk]) if pk else None


def _render_text(text: str, linker: _ReferenceLinker) -> str:
    """Render one string: literal text is HTML-escaped as usual, cross-reference tags that
    match a known catalog row become real links, and every other `{@tag ...}` is replaced with
    its (escaped) display text. Returns safe HTML - never call `escape()` on this result.
    """
    pieces = []
    last_end = 0
    for m in TAG_PATTERN.finditer(text):
        pieces.append(escape(text[last_end : m.start()]))
        pieces.append(_render_tag(m.group(1), m.group(2), linker))
        last_end = m.end()
    pieces.append(escape(text[last_end:]))
    return "".join(pieces)


def _render_tag(tag: str, body: str, linker: _ReferenceLinker) -> str:
    display = _tag_display_text(tag, body)
    # The link target is always the tag's *first* segment (the catalog row actually being
    # referenced), even when a later segment overrides what's displayed - e.g.
    # `{@variantrule Cover|XPHB|Total Cover}` links to the "Cover" rule while reading
    # "Total Cover".
    url = linker.url_for(tag, body.split("|")[0])
    if url:
        return f'<a href="{escape(url)}">{escape(display)}</a>'
    return escape(display)


def render_entries(entries) -> SafeString:
    """Render an `entries`-shaped value (or a bare string/list) as safe HTML."""
    linker = _ReferenceLinker()
    return mark_safe(_render_node(entries, linker))


def _render_entry_cards(blocks: list, linker: _ReferenceLinker) -> str:
    """Render a flat list of {name, entries} blocks as one visually separated card per block -
    shared by `render_trait_cards()` and `render_class_features()` below.
    """
    cards = []
    for block in blocks:
        name = block.get("name", "") if isinstance(block, dict) else ""
        body_source = block.get("entries", []) if isinstance(block, dict) else block
        heading_html = f"<h3>{_render_text(name, linker)}</h3>" if name else ""
        body_html = _render_node(body_source, linker)
        cards.append(f'<div class="entry-card">{heading_html}{body_html}</div>')
    return f'<div class="entry-cards">{"".join(cards)}</div>'


def render_trait_cards(entries: list) -> SafeString:
    """Render a flat list of {name, entries} blocks - the shape every XPHB Species' top-level
    `entries` list uses, one block per trait (verified against every species in db/species.json)
    - as one visually separated card per trait, instead of the plain stacked headings
    `render_entries()` would produce for the same shape.
    """
    linker = _ReferenceLinker()
    return mark_safe(_render_entry_cards(entries or [], linker))


def _render_level_groups(by_level: dict[int, list[dict]], linker: _ReferenceLinker) -> str:
    """Render a {level: [{name, entries}, ...]} mapping as one collapsible group per level, each
    holding one card per block gained at that level - shared by `render_class_features()` and
    `render_subclasses()` below. The lowest level starts expanded since it's what a new reader
    most likely wants first.
    """
    groups = []
    for i, level in enumerate(sorted(by_level)):
        open_attr = " open" if i == 0 else ""
        cards_html = _render_entry_cards(by_level[level], linker)
        groups.append(
            f'<details class="level-group"{open_attr}>'
            f"<summary>{escape(gettext('Level'))} {level}</summary>"
            f"{cards_html}"
            f"</details>"
        )
    return "".join(groups)


def render_class_features(features: list) -> SafeString:
    """Render `rules.Class.features` (a flat {level, name, entries} list - multiple features
    commonly share a level, e.g. every class's level 1 has several) as one collapsible group per
    level, each holding one card per feature gained at that level.
    """
    linker = _ReferenceLinker()
    by_level: dict[int, list[dict]] = {}
    for feature in features or []:
        by_level.setdefault(feature["level"], []).append(feature)
    return mark_safe(_render_level_groups(by_level, linker))


def render_subclasses(subclasses) -> SafeString:
    """Render a Class's `rules.Subclass` rows - each with its own `description` (flavor text)
    and `levels` (`SubclassLevel` rows holding {level, features}, features being a
    {name, entries} list since a couple of subclasses grant more than one feature at the same
    level) - as one named block per subclass, reusing the same per-level collapsible card
    grouping as `render_class_features()`. Iterate `subclasses` with `.levels` already
    prefetched (e.g. `klass.subclasses.prefetch_related("levels")`) to avoid one query per
    subclass.

    `SubclassLevel.features` and `Subclass.description` are both already cleanly split at
    import time (see `_split_subclass_features` in
    `apps/rules/management/commands/import_rules_data.py`) - this used to also have to unwrap a
    data error here at render time (a subclass's flavor text and its real first-batch features
    arrived bundled into one block titled after the subclass itself), but that's now fixed at
    the source instead.
    """
    linker = _ReferenceLinker()
    blocks = []
    for subclass in subclasses:
        description_html = (
            _render_node(subclass.description, linker) if subclass.description else ""
        )
        by_level = {sl.level: sl.features for sl in subclass.levels.all()}
        groups_html = _render_level_groups(by_level, linker)
        blocks.append(
            f'<div class="subclass-block">'
            f"<h3>{_render_text(subclass.name, linker)}</h3>"
            f"{description_html}"
            f"{groups_html}"
            f"</div>"
        )
    return mark_safe("".join(blocks))


def _render_node(node, linker: _ReferenceLinker) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return f"<p>{_render_text(node, linker)}</p>"
    if isinstance(node, list):
        return "".join(_render_node(item, linker) for item in node)
    if isinstance(node, dict):
        return _render_dict(node, linker)
    return f"<p>{escape(str(node))}</p>"


def _render_dict(node: dict, linker: _ReferenceLinker) -> str:
    node_type = node.get("type")

    if node_type in ("entries", "section", "inset"):
        heading = node.get("name")
        heading_html = f"<h3>{_render_text(heading, linker)}</h3>" if heading else ""
        css_class = ' class="inset"' if node_type == "inset" else ""
        body = _render_node(node.get("entries", []), linker)
        return f"<div{css_class}>{heading_html}{body}</div>"

    if node_type == "list":
        items_html = "".join(_render_list_item(item, linker) for item in node.get("items", []))
        return f"<ul>{items_html}</ul>"

    if node_type == "item":
        return _render_list_item(node, linker)

    if node_type == "table":
        return _render_table(node, linker)

    if node_type == "options":
        count = node.get("count")
        note = f"<p><em>{escape(_choose_note(count))}</em></p>" if count else ""
        return note + _render_node(node.get("entries", []), linker)

    if node_type == "refFeat":
        name = _tag_display_text("refFeat", node.get("feat", ""))
        return f"<p>&rarr; {escape(name)}</p>"

    if node_type == "refOptionalfeature":
        name = _tag_display_text("refOptionalfeature", node.get("optionalfeature", ""))
        return f"<p>&rarr; {escape(name)}</p>"

    # Unknown shape - if it has nested entries, render those rather than dropping the content
    # silently; otherwise there's nothing safe to do with it.
    if "entries" in node:
        return _render_node(node["entries"], linker)
    return ""


def _choose_note(count: int) -> str:
    return f"Choose {count}:" if count != 1 else "Choose one:"


def _render_list_item(item, linker: _ReferenceLinker) -> str:
    if isinstance(item, str):
        return f"<li>{_render_text(item, linker)}</li>"
    if not isinstance(item, dict):
        return ""

    name = item.get("name")
    name_html = f"<strong>{_render_text(name, linker)}</strong> " if name else ""

    if "entry" in item:
        entry_val = item["entry"]
        body = (
            _render_text(entry_val, linker)
            if isinstance(entry_val, str)
            else _render_node(entry_val, linker)
        )
    else:
        body = _render_node(item.get("entries", []), linker)

    return f"<li>{name_html}{body}</li>"


def render_key_value_table(rows, headers) -> SafeString:
    """Render a list of {header: value} dicts as an HTML table with the given header order -
    used for `rules.ClassLevel.columns`, which is already stored as one such dict per level.
    These are short catalog-table cells (e.g. "Rages", "+2"), not narrative text, and don't
    contain `{@tag ...}` markup in the source data, so no link resolution happens here.
    """
    header_html = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{escape(str(row.get(h, '')))}</td>" for h in headers) + "</tr>"
        for row in rows
    )
    return mark_safe(
        f"<table><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>"
    )


def _render_table(node: dict, linker: _ReferenceLinker) -> str:
    caption = node.get("caption")
    caption_html = f"<caption>{_render_text(caption, linker)}</caption>" if caption else ""

    headers = node.get("colLabels", [])
    header_html = "".join(f"<th>{_render_text(str(h), linker)}</th>" for h in headers)
    thead_html = f"<thead><tr>{header_html}</tr></thead>" if headers else ""

    body_html = "".join(
        "<tr>" + "".join(f"<td>{_render_text(str(cell), linker)}</td>" for cell in row) + "</tr>"
        for row in node.get("rows", [])
    )

    return f"<table>{caption_html}{thead_html}<tbody>{body_html}</tbody></table>"
