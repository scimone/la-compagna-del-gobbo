"""Render the 5etools-style `entries` JSON blobs (used across most `rules` models - Background,
Species, Class, Feat, Spell, HandbookSection, ...) as safe, readable HTML.

The shapes handled here were enumerated directly from db/*.json (every distinct `type` value
that actually occurs across `features`/`lore`/`entries`/`entriesHigherLevel` fields), not
guessed: entries/section/inset (a heading + nested entries), list/item (list also handles
`style: "list-decimal"`/`"list-no-bullets"` and a `columns` hint - only db/handbook.json and a
few db/rules.json entries use these), table (colLabels, or db/handbook.json's one table using
`colLabelRows` instead), options (a "choose N" group), and refFeat/refOptionalfeature (a bare
cross-reference to another catalog entry, rendered as a plain mention - not a hyperlink, since
resolving *those* links would need a `CharacterFeat`/`CharacterOptionalFeature`-style *choice*
context this renderer doesn't have, not just a name lookup). `image` and `statblock` (both only
in db/handbook.json) render as nothing - see the comment where they fall through, in
`_render_dict`. `{@variantrule ...}`, `{@spell ...}` and `{@feat ...}` references *do* become
real links, since those three catalogs (`rules.Rule`/`Spell`/`Feat`) each already have a detail
page and a name to match against - see `_ReferenceLinker` below. Verified against every
occurrence of all three tags in db/ before relying on the name match: 50/51 variantrule
references, 102/102 spell references, and 19/19 feat references resolve. Every other `{@tag ...}`
(`{@skill}`, `{@condition}`, `{@dice}`, `{@action}`, ...) falls back to its plain display text
via `_tag_display_text()` - there's no catalog page for those to link to.

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
    tags always want the first segment (the rest are query/filter parameters, not text); `@area`
    tags (`{@area ability checks|020|x}` - db/handbook.json only) always want the first segment
    too - the second is an internal same-document target id, and the third is always the literal
    string "x", a page-number placeholder 5etools' own renderer would normally resolve, which
    this renderer has no use for (verified: all 63 occurrences end in that literal "x"); tags
    with 3+ segments are otherwise assumed to want the *last* one (an explicit display-text
    override, e.g. `{@variantrule Cover|XPHB|Total Cover}` should read "Total Cover"); anything
    else wants the first segment.
    """
    segments = body.split("|")
    if tag in ("filter", "area"):
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
    """Resolves `{@variantrule/spell/feat ...}` references to their catalog row's detail page,
    and (via `toggle_entries`) carries the one per-render-pass rendering option that isn't about
    linking - it's already the single context object threaded through every recursive render
    function, so it's the natural place for that too rather than a second parameter everywhere.

    Built once per top-level `render_entries()` call and threaded through the recursive render
    functions, rather than querying per tag occurrence - each of these catalogs is small and
    mostly static (114/391/77 rows), so one query per catalog per page render is plenty.
    """

    def __init__(self, *, toggle_entries: bool = False):
        from django.apps import apps as django_apps

        self._lookups = {}
        for tag, (model_label, url_name) in _LINKABLE_TAGS.items():
            model = django_apps.get_model(model_label)
            pk_by_name = {obj.name.lower(): obj.pk for obj in model.objects.only("pk", "name")}
            self._lookups[tag] = (pk_by_name, url_name)
        # Only `render_handbook_section()` sets this - a plain `<h3>` heading is still right for
        # every other model's nested `entries` blocks (e.g. a Wizard's Spellcasting feature card
        # has "Cantrips"/"Spellbook" sub-headings that shouldn't suddenly become togglable).
        self.toggle_entries = toggle_entries

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


def render_handbook_section(entries) -> SafeString:
    """Render a `rules.HandbookSection`'s `entries` the same way `render_entries()` does, except
    every named `type: "entries"` block - at any nesting depth - becomes a collapsible toggle
    heading (reusing the `.level-group` look) instead of a plain `<h3>`. A handbook section's
    own text is long and deeply subdivided (see the README's "Model status" table) in a way no
    other model's `entries` field is, so it benefits from the same progressive-disclosure
    treatment `render_class_features()` already gives a Class's per-level features - requested
    specifically for these pages, not applied to `render_entries()`'s shared default behavior.
    """
    linker = _ReferenceLinker(toggle_entries=True)
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


def render_class_features(features) -> SafeString:
    """Render a Class's `Feature` rows (each with `class_level` set - fetch with e.g.
    `Feature.objects.filter(class_level__klass=klass).order_by("pk")`, the `.order_by("pk")`
    needed for the same reason as `render_subclasses()`: `Feature`'s default ordering is
    alphabetical by name, which isn't the source's presentation order) as one collapsible group
    per level, each holding one card per feature gained at that level - multiple features
    commonly share a level, e.g. every class's level 1 has several.
    """
    linker = _ReferenceLinker()
    by_level: dict[int, list[dict]] = {}
    for feature in features:
        by_level.setdefault(feature.class_level.level, []).append(
            {"name": feature.name, "entries": feature.entries}
        )
    return mark_safe(_render_level_groups(by_level, linker))


def render_subclasses(subclasses) -> SafeString:
    """Render a Class's `rules.Subclass` rows - each with its own `description` (flavor text)
    and `levels` (`SubclassLevel` rows, each with its features as `Feature` rows reachable via
    `.feature_rows` - `SubclassLevel` keeps no `features` JSON of its own, see its docstring for
    why) - as one named block per subclass, reusing the same per-level collapsible card grouping
    as `render_class_features()`. Iterate `subclasses` with `.levels` and `.levels__feature_rows`
    already prefetched (e.g.
    `klass.subclasses.prefetch_related("levels__feature_rows")`) to avoid a query per level.

    `Subclass.description` is already cleanly split out of the source's granting-level block at
    import time (see `_split_subclass_features` in
    `apps/rules/management/commands/import_rules_data.py`) - this used to also have to unwrap
    that same data error here at render time, but that's fixed at the source instead now.
    """
    linker = _ReferenceLinker()
    blocks = []
    for subclass in subclasses:
        description_html = (
            _render_node(subclass.description, linker) if subclass.description else ""
        )
        by_level = {
            sl.level: [{"name": f.name, "entries": f.entries} for f in sl.feature_rows.all()]
            for sl in subclass.levels.all()
        }
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
        body = _render_node(node.get("entries", []), linker)

        if node_type == "entries" and heading and linker.toggle_entries:
            return (
                f'<details class="level-group">'
                f"<summary>{_render_text(heading, linker)}</summary>"
                f'<div class="toggle-body">{body}</div>'
                f"</details>"
            )

        heading_html = f"<h3>{_render_text(heading, linker)}</h3>" if heading else ""
        css_class = ' class="inset"' if node_type == "inset" else ""
        return f"<div{css_class}>{heading_html}{body}</div>"

    if node_type == "list":
        return _render_list(node, linker)

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
    # silently; otherwise there's nothing safe to do with it. This is also what happens to
    # `image` (book art we don't have the files for - no `static/` copy of `book/XPHB/*.webp`)
    # and `statblock` (a bare name/tag/source reference to a monster/hazard stat block - there's
    # no Bestiary model to link it to, per the "no combat system" scope decision) - both drop
    # silently rather than showing a caption pointing at nothing or an unresolvable reference.
    if "entries" in node:
        return _render_node(node["entries"], linker)
    return ""


def _choose_note(count: int) -> str:
    return f"Choose {count}:" if count != 1 else "Choose one:"


def _render_list(node: dict, linker: _ReferenceLinker) -> str:
    """Render a `list` node. `style: "list-decimal"` becomes an ordered `<ol>` (numbered steps,
    e.g. the handbook's "Combat Step by Step"); `style: "list-no-bullets"` drops the bullet
    marker (a plain side-by-side grouping, e.g. a list of senses); `columns` (an int) lays the
    list out in that many CSS columns, for short items meant to sit side by side rather than in
    one long column. A list can carry its own `name` alongside its items' individual names -
    rare (a handful of numbered "(1)"-style callouts in the handbook, cross-referencing an inset
    elsewhere) but rendered as a small heading above the list when present, the same as every
    other named block in this renderer.
    """
    heading_html = f"<h4>{_render_text(node['name'], linker)}</h4>" if node.get("name") else ""
    items_html = "".join(_render_list_item(item, linker) for item in node.get("items", []))
    tag = "ol" if node.get("style") == "list-decimal" else "ul"
    class_attr = ' class="no-bullets"' if node.get("style") == "list-no-bullets" else ""
    style_attr = f' style="column-count: {int(node["columns"])}"' if node.get("columns") else ""
    return f"{heading_html}<{tag}{class_attr}{style_attr}>{items_html}</{tag}>"


def _render_list_item(item, linker: _ReferenceLinker) -> str:
    if isinstance(item, str):
        return f"<li>{_render_text(item, linker)}</li>"
    if not isinstance(item, dict):
        return ""

    # A list's `items` can itself hold a differently-typed node - not wrapped in an `item` - e.g.
    # a nested `list` (the handbook's "Add Modifiers" step has a sub-list of modifier types as
    # its third `list-decimal` entry, not a fourth named item). Delegate to the general dict
    # renderer for anything typed but not "item", rather than assuming the {name, entry} shape,
    # which would otherwise silently produce an empty <li> (verified: this is the only such
    # occurrence across every db/*.json file, but the fallback is general, not a special case).
    item_type = item.get("type")
    if item_type and item_type != "item":
        return f"<li>{_render_dict(item, linker)}</li>"

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


def _format_table_cell(value) -> str:
    """A `rules.ClassLevel.columns` cell value - either a plain int/str (e.g. "2", "3") or one of
    three typed dicts the source uses for dice/bonus progressions (verified: no other `type`
    occurs anywhere in `db/classes.json`), stored on the model verbatim rather than pre-flattened
    so no information is lost - see `ClassLevel`'s docstring. Rendering them is this function's
    job, not the importer's:

    - `{"type": "dice", "toRoll": [{"number": 1, "faces": 6}]}` -> `"1d6"` (Monk's Martial Arts
      die) - multiple `toRoll` entries (not seen in practice, but the source allows it) join with
      `"+"`.
    - `{"type": "bonus", "value": 2}` -> `"+2"` (Barbarian's Rage Damage).
    - `{"type": "bonusSpeed", "value": 0}` -> `"+0 ft."` (Monk's Unarmored Movement).
    """
    if not isinstance(value, dict):
        return str(value)
    cell_type = value.get("type")
    if cell_type == "dice":
        return "+".join(f"{d.get('number', 1)}d{d['faces']}" for d in value.get("toRoll", []))
    if cell_type == "bonus":
        return f"+{value.get('value', 0)}"
    if cell_type == "bonusSpeed":
        return f"+{value.get('value', 0)} ft."
    return str(value)


def render_key_value_table(rows, headers) -> SafeString:
    """Render a list of {header: value} dicts as an HTML table with the given header order -
    used for `rules.ClassLevel.columns`, which is already stored as one such dict per level.
    These are short catalog-table cells (e.g. "Rages", "+2"), not narrative text, and don't
    contain `{@tag ...}` markup in the source data, so no link resolution happens here - only
    `_format_table_cell`'s dice/bonus decoding.
    """
    header_html = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_html = "".join(
        "<tr>"
        + "".join(f"<td>{escape(_format_table_cell(row.get(h, '')))}</td>" for h in headers)
        + "</tr>"
        for row in rows
    )
    return mark_safe(
        f"<table><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>"
    )


def render_starting_equipment(options) -> SafeString:
    """Render a Class/Background's starting-equipment choice - `ClassStartingEquipmentOption`/
    `BackgroundStartingEquipmentOption` rows, grouped by their shared `option` letter ("choose A,
    B, or C") into one comma-separated line each. `gold_value` is stored in copper (matching
    `rules.Equipment.value`'s own unit - confirmed against a known real value: Fighter's option C
    is `15500` copper, i.e. exactly the 155 GP the 2024 Player's Handbook gives) so it's divided
    by 100 for display. `group` (e.g. "any Holy Symbol") covers the two picks that name an
    `EquipmentGroup` rather than one concrete `Equipment` row - see that model's docstring.
    """
    grouped: dict[str, list[str]] = {}
    for opt in options:
        if opt.item_id:
            piece = opt.item.name if opt.quantity == 1 else f"{opt.quantity}x {opt.item.name}"
        elif opt.group_id:
            piece = f"{gettext('any')} {opt.group.name}"
        elif opt.gold_value is not None:
            gp = opt.gold_value / 100
            piece = f"{gp:g} GP"
        else:
            continue
        grouped.setdefault(opt.option, []).append(piece)
    items_html = "".join(
        f"<li><strong>{escape(option)}:</strong> {escape(', '.join(pieces))}</li>"
        for option, pieces in sorted(grouped.items())
    )
    return mark_safe(f"<ul>{items_html}</ul>")


def _render_table(node: dict, linker: _ReferenceLinker) -> str:
    caption = node.get("caption")
    caption_html = f"<caption>{_render_text(caption, linker)}</caption>" if caption else ""

    # Every table has a flat `colLabels` except one (so far): the handbook's "Travel Pace" table
    # instead uses `colLabelRows` (multiple header rows, for a spanning super-header above
    # sub-columns - e.g. "Distance Traveled Per..." over "Minute"/"Hour"/"Day") - falling back to
    # just its last row gets the real per-column labels without needing full rowspan/colspan
    # support for what's currently a single occurrence. A `cellHeader` cell (also currently only
    # in that one table) is a dict wrapping its label text in `entry` rather than being the bare
    # string every other header cell is.
    headers = node.get("colLabels")
    if not headers:
        label_rows = node.get("colLabelRows") or []
        last_row = label_rows[-1] if label_rows else []
        headers = [cell.get("entry", "") if isinstance(cell, dict) else cell for cell in last_row]
    header_html = "".join(f"<th>{_render_text(str(h), linker)}</th>" for h in headers)
    thead_html = f"<thead><tr>{header_html}</tr></thead>" if headers else ""

    body_html = "".join(
        "<tr>" + "".join(f"<td>{_render_text(str(cell), linker)}</td>" for cell in row) + "</tr>"
        for row in node.get("rows", [])
    )

    return f"<table>{caption_html}{thead_html}<tbody>{body_html}</tbody></table>"
