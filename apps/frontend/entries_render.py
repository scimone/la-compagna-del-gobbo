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
points (not part of the generic `render_entries()` recursion) for the spots that need something
other than plain stacked headings: a Species' traits (`render_trait_cards()`) as one card per
trait, and a Class's per-level features and subclasses (`render_class_features()`/
`render_subclasses()`) as one plain-headed group per level holding a clickable link per feature -
to that feature's own detail page (`world_feature_detail()` in `views.py`), rather than its text
shown inline, since every `Feature` row has its own page now.
"""

import re

from django.urls import reverse
from django.utils.html import conditional_escape, escape
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import get_language, gettext

from apps.frontend.units import distance, metricize_text

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
    else wants the first segment. `{@dc 15}` is the one tag whose body is a bare value rather than
    text - it reads "DC 15" ("CD 15" in Italian, via the `.po` file), not just "15".
    """
    segments = body.split("|")
    if tag in ("filter", "area"):
        return segments[0]
    if tag == "dc":
        return f"{gettext('DC')} {segments[0]}"
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
            # Tags carry the *English* catalog name (the Italian wording is only their display
            # text), so look rows up by their `name_en` where the model is translated.
            name_field = "name_en" if hasattr(model, "name_en") else "name"
            pk_by_name = {
                name.lower(): pk for pk, name in model.objects.values_list("pk", name_field) if name
            }
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

    On the Italian site, English measurements ("30 feet") are converted to metric first (see
    `units.metricize_text()`) - a no-op in English, and harmless here since tag syntax never
    contains a bare number-plus-unit for it to mismatch.
    """
    text = metricize_text(text)
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


def plain_text(text: str) -> str:
    """One string as it reads on the page but without any HTML: the same metric conversion and
    `{@tag ...}` display text as `_render_text()`, for matching a search query against what the
    user actually sees (a "{@dc 10}" is searchable as "DC 10", "30 feet" as "9 metri").
    """
    return TAG_PATTERN.sub(
        lambda m: _tag_display_text(m.group(1), m.group(2)), metricize_text(text)
    )


def render_entries(entries) -> SafeString:
    """Render an `entries`-shaped value (or a bare string/list) as safe HTML."""
    linker = _ReferenceLinker()
    return mark_safe(_render_node(entries, linker))


def render_text(text: str) -> SafeString:
    """Render one bare string's `{@tag ...}` markup inline, with no `<p>` wrapper - for a short
    snippet embedded in a larger sentence (e.g. a Spell's casting-time condition, "...or an
    {@variantrule Unarmed Strike|XPHB}") rather than a full `entries` block of its own.
    """
    return mark_safe(_render_text(text, _ReferenceLinker()))


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
    used by `render_trait_cards()` below (a Species' traits still show their full text on its own
    Traits tab). A block's optional `id` (a `Feature` pk) becomes the card's DOM id - browsers open
    an ancestor `<details>` automatically when navigating to a fragment inside it, so no JS is
    needed to expand the right section.
    """
    cards = []
    for block in blocks:
        name = block.get("name", "") if isinstance(block, dict) else ""
        body_source = block.get("entries", []) if isinstance(block, dict) else block
        block_id = block.get("id") if isinstance(block, dict) else None
        id_attr = f' id="feature-{block_id}"' if block_id else ""
        badge_html = (
            self_translated_badge(bool(block.get("self_translated")))
            if isinstance(block, dict)
            else ""
        )
        heading_html = f"<h3>{_render_text(name, linker)}{badge_html}</h3>" if name else badge_html
        body_html = _render_node(body_source, linker)
        cards.append(f'<div class="entry-card"{id_attr}>{heading_html}{body_html}</div>')
    return f'<div class="entry-cards">{"".join(cards)}</div>'


def self_translated_badge(is_self_translated: bool) -> str:
    """A small badge marking a specific heading/card whose Italian text was hand-translated for
    this project rather than lifted from the official Italian SRD - only shown while actually
    browsing in Italian, since the flag says nothing about the English text. Public (not
    underscore-prefixed): `views.py` reuses it for section headings (Lore, Description, ...) that
    aren't built from `_render_entry_cards()`, so the badge always sits on the specific block of
    text it describes rather than blanketing an entire page that may be only partly hand-translated.
    """
    if not is_self_translated or get_language() != "it":
        return ""
    return (
        ' <span class="self-translated-badge" '
        'title="Testo tradotto per questo progetto, non dalla fonte SRD ufficiale">'
        "Traduzione</span>"
    )


def homebrew_badge() -> str:
    """A small "Homebrew" badge for content that isn't part of the official 2024 rules (today only
    the Grung species - see `HOMEBREW_SPECIES` in `views.py`). Shown in every language, unlike
    `self_translated_badge()`, and the two are never shown together on the same heading: a
    homebrew entry's text is by definition not the official SRD's, so "Traduzione" would add
    nothing.
    """
    title = escape(gettext("Not part of the official 2024 rules"))
    return f' <span class="self-translated-badge homebrew-badge" title="{title}">Homebrew</span>'


def render_trait_cards(
    entries: list, *, self_translated: bool = False, feature_ids: dict[str, int] | None = None
) -> SafeString:
    """Render a flat list of {name, entries} blocks - the shape every XPHB Species' top-level
    `entries` list uses, one block per trait (verified against every species in db/species.json)
    - as one visually separated card per trait, instead of the plain stacked headings
    `render_entries()` would produce for the same shape.

    `self_translated` marks every card the same way, since (unlike `Feature` rows) a Species'
    traits all come from the one `entries` field - there's no finer-grained provenance to show
    per trait.

    `feature_ids` (a `{name: pk}` map, e.g. `{f.name: f.pk for f in species.feature_rows.all()}`)
    gives a card its DOM id for a matching named block - lets the World Features list's species-
    trait entries deep-link straight to their card.
    """
    linker = _ReferenceLinker()
    feature_ids = feature_ids or {}
    blocks = []
    for block in entries or []:
        if isinstance(block, dict):
            block = {**block, "self_translated": self_translated}
            feature_id = feature_ids.get(block.get("name"))
            if feature_id:
                block["id"] = feature_id
        blocks.append(block)
    return mark_safe(_render_entry_cards(blocks, linker))


def _render_feature_links(features, linker: _ReferenceLinker) -> str:
    """One `<li>` per feature, linking to its own detail page (`world_feature_detail()`) instead
    of showing its `entries` text inline - shared by `render_class_features()` and
    `render_subclasses()` below, whose Levels/Subclasses tabs used to show that text in a card
    (`_render_entry_cards()`) but now only link out to it, since every `Feature` has its own page.
    """
    items = "".join(
        f'<li><a href="{escape(reverse("world-feature-detail", args=[f.pk]))}">'
        f"{_render_text(f.name, linker)}"
        f"{self_translated_badge(bool(f.self_translated_fields))}</a></li>"
        for f in features
    )
    return f'<ul class="feature-link-list">{items}</ul>'


def _render_level_feature_links(by_level: dict[int, list], linker: _ReferenceLinker) -> str:
    """One group per level, each a plain, non-interactive heading (a `<div>` - see
    `.level-group.static` in detail.html) over one link per feature gained at that level - shared
    by `render_class_features()` and `render_subclasses()` below. Always shown, no toggle: a
    level's worth of links is short enough not to need hiding behind a tap the way a level's worth
    of full feature text used to be.
    """
    groups = []
    for level in sorted(by_level):
        heading = f"{escape(gettext('Level'))} {level}"
        links = _render_feature_links(by_level[level], linker)
        groups.append(
            f'<div class="level-group static"><div class="level-heading">{heading}</div>'
            f"{links}</div>"
        )
    return "".join(groups)


def render_class_features(features) -> SafeString:
    """Render a Class's `Feature` rows (each with `class_level` set - fetch with e.g.
    `Feature.objects.filter(class_level__klass=klass).order_by("pk")`, the `.order_by("pk")`
    needed for the same reason as `render_subclasses()`: `Feature`'s default ordering is
    alphabetical by name, which isn't the source's presentation order) as one plain-headed group
    per level, each holding one clickable link per feature gained at that level (to that feature's
    own detail page, see `world_feature_detail()`) - multiple features commonly share a level,
    e.g. every class's level 1 has several. Used to show each feature's full text inline instead -
    see `_render_level_feature_links()` for why that moved to each `Feature`'s own page.
    """
    linker = _ReferenceLinker()
    by_level: dict[int, list] = {}
    for feature in features:
        by_level.setdefault(feature.class_level.level, []).append(feature)
    return mark_safe(_render_level_feature_links(by_level, linker))


def render_subclasses(subclasses) -> SafeString:
    """Render a Class's `rules.Subclass` rows - each with its own `description` (flavor text)
    and `levels` (`SubclassLevel` rows, each with its features as `Feature` rows reachable via
    `.feature_rows` - `SubclassLevel` keeps no `features` JSON of its own, see its docstring for
    why) - as one collapsed-by-default `<details>` block per subclass (its name is the clickable
    `<summary>`; they share a `name`, so the browser keeps at most one open - opening
    another closes the first, no JS), reusing the same per-level link grouping as
    `render_class_features()`
    for the body - each feature links out to its own detail page instead of the body showing its
    text. Iterate `subclasses` with `.levels` and `.levels__feature_rows` already prefetched (e.g.
    `klass.subclasses.prefetch_related("levels__feature_rows")`) to avoid a query per level.

    `Subclass.description` (flavor text, distinct from any one feature's own `entries`) is already
    cleanly split out of the source's granting-level block at import time (see
    `_split_subclass_features` in `apps/rules/management/commands/import_rules_data.py`) - this
    used to also have to unwrap that same data error here at render time, but that's fixed at the
    source instead now, and it still renders here in full (only feature text moved out).
    """
    linker = _ReferenceLinker()
    blocks = []
    for subclass in subclasses:
        description_html = (
            _render_node(subclass.description, linker) if subclass.description else ""
        )
        by_level = {sl.level: list(sl.feature_rows.all()) for sl in subclass.levels.all()}
        groups_html = _render_level_feature_links(by_level, linker)
        subclass_badge = self_translated_badge(bool(subclass.self_translated_fields))
        blocks.append(
            f'<details class="subclass-block" name="subclass">'
            f"<summary>{_render_text(subclass.name, linker)}{subclass_badge}</summary>"
            f'<div class="subclass-body">{description_html}{groups_html}</div>'
            f"</details>"
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
        # A handbook block whose Italian text was hand-translated carries `self_translated` (see
        # `handbook_source`) - the badge sits on that specific heading, like on a Feature card.
        badge_html = self_translated_badge(bool(node.get("self_translated")))

        if node_type == "entries" and heading and linker.toggle_entries:
            return (
                f'<details class="level-group">'
                f"<summary>{_render_text(heading, linker)}{badge_html}</summary>"
                f'<div class="toggle-body">{body}</div>'
                f"</details>"
            )

        heading_html = f"<h3>{_render_text(heading, linker)}{badge_html}</h3>" if heading else ""
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
    - `{"type": "bonusSpeed", "value": 0}` -> `"+0 ft."` (Monk's Unarmored Movement) - `"+0 m"`
      in Italian, via `units.distance()`.

    `world_class_detail()`'s Features column adds a fourth, view-built shape not sourced from
    `columns` at all - `{"type": "features", "items": [{"href": ..., "name": ...}, ...]}` - one
    `Feature` per grant at that level, rendered as links straight to each feature's own detail
    page (`href` is `reverse("world-feature-detail", args=[f.pk])`) instead of plain text, since
    unlike the other cell types this one carries markup and must come back as a `SafeString` -
    `render_key_value_table()` uses `conditional_escape()` rather than `escape()` for exactly this
    cell type, leaving every other (plain-text) cell escaped as before.
    """
    if not isinstance(value, dict):
        return str(value)
    cell_type = value.get("type")
    if cell_type == "dice":
        return "+".join(f"{d.get('number', 1)}d{d['faces']}" for d in value.get("toRoll", []))
    if cell_type == "bonus":
        return f"+{value.get('value', 0)}"
    if cell_type == "bonusSpeed":
        amount = value.get("value", 0)
        sign = "+" if amount >= 0 else ""
        return f"{sign}{distance(amount)}"
    if cell_type == "features":
        links = ", ".join(
            f'<a href="{escape(item["href"])}">{escape(item["name"])}</a>'
            for item in value.get("items", [])
        )
        return mark_safe(links)
    return str(value)


def render_key_value_table(rows, headers) -> SafeString:
    """Render a list of {header: value} dicts as an HTML table with the given header order -
    used for `rules.ClassLevel.columns`, which is already stored as one such dict per level.
    These are short catalog-table cells (e.g. "Rages", "+2"), not narrative text, and don't
    contain `{@tag ...}` markup in the source data, so no link resolution happens here - only
    `_format_table_cell`'s dice/bonus/features decoding. `conditional_escape()` (not `escape()`)
    lets that decoding return real markup (the Features column's links) for the one cell type
    that needs it, while every plain-text cell is still escaped as before.
    """
    header_html = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_html = "".join(
        "<tr>"
        + "".join(
            f"<td>{conditional_escape(_format_table_cell(row.get(h, '')))}</td>" for h in headers
        )
        + "</tr>"
        for row in rows
    )
    return mark_safe(
        f'<div class="table-scroll"><table><thead><tr>{header_html}</tr></thead>'
        f"<tbody>{body_html}</tbody></table></div>"
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
    lines = [escape(", ".join(pieces)) for _option, pieces in sorted(grouped.items())]
    items_html = "".join(f"<li>{line}</li>" for line in lines)
    if len(lines) > 1:
        # Alternatives (A/B/C on the source): "Choose 1:" above them instead of a letter each.
        return mark_safe(f"<div>{escape(gettext('Choose'))} 1:</div><ul>{items_html}</ul>")
    return mark_safe(f"<ul>{items_html}</ul>")


def _render_table(node: dict, linker: _ReferenceLinker) -> str:
    caption = node.get("caption")
    # A hand-translated table (see `handbook_source`) carries `self_translated` like a named block.
    badge_html = self_translated_badge(bool(node.get("self_translated")))
    caption_html = (
        f"<caption>{_render_text(caption, linker)}{badge_html}</caption>" if caption else ""
    )

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
