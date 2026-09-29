"""Full-text search over the Handbook: the text of every `HandbookSection` and of every `Rule` (the
Glossary's entries), not just their names.

Both are `entries`-shaped JSON (see `entries_render`), so this walks the same node shapes the
renderer does - but yields plain text (see `plain_text()`) instead of HTML, one block per
paragraph / list item / table row / heading, together with the headings it sits under. A hit is
shown as a short snippet of its block around the match, headed by that path ("Actions › Attack"),
so a long section says where in it the query was found.

The data is small (a couple of dozen sections, ~100 rules), so this is a plain Python scan over
already-loaded rows rather than a database query.
"""

import re
import unicodedata

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from apps.frontend.entries_render import plain_text

# Snippets shown per section/rule; the rest are only counted ("+4 more").
SNIPPETS_PER_ENTRY = 3
# Characters of context kept before / after the first match of a block.
_BEFORE = 50
_AFTER = 110
_PATH_SEPARATOR = " › "


def fold(text: str) -> str:
    """`text` lowercased with its accents removed ("Proprietà" -> "proprieta"), so a search for
    "proprieta" finds it. Unlike `unicodedata.normalize()` + stripping marks it keeps one output
    character per input character, so a match's position in `fold(text)` is also its position in
    `text` - which is what lets `_snippet()` highlight the original, accented wording.
    """
    return "".join(unicodedata.normalize("NFD", char)[0].lower()[:1] for char in text)


def query_pattern(q: str) -> re.Pattern:
    """A pattern for `q`, to be searched in `fold()`ed text (it is folded here too)."""
    return re.compile(re.escape(fold(unicodedata.normalize("NFC", q))))


def text_blocks(node, path: tuple[str, ...] = ()):
    """Yield `(headings, text)` for every piece of text under `node`. `headings` are the names of
    the blocks enclosing it, outermost first (a heading is itself a block, filed under its
    parents).
    """
    if isinstance(node, str):
        yield path, plain_text(node)
    elif isinstance(node, list):
        for child in node:
            yield from text_blocks(child, path)
    elif isinstance(node, dict):
        yield from _dict_blocks(node, path)


def _dict_blocks(node: dict, path: tuple[str, ...]):
    node_type = node.get("type")
    name = plain_text(node["name"]) if node.get("name") else None

    if node_type in ("entries", "section", "inset"):
        if name:
            yield path, name
            path = path + (name,)
        yield from text_blocks(node.get("entries", []), path)
    elif node_type == "list":
        if name:
            yield path, name
        for item in node.get("items", []):
            yield from _list_item_blocks(item, path)
    elif node_type == "item":
        yield from _list_item_blocks(node, path)
    elif node_type == "table":
        if node.get("caption"):
            yield path, plain_text(node["caption"])
        # Same fallback as `_render_table()`: the one table with `colLabelRows` reads its last row.
        headers = node.get("colLabels") or (node.get("colLabelRows") or [[]])[-1]
        cells = [c.get("entry", "") if isinstance(c, dict) else c for c in headers]
        if cells:
            yield path, plain_text(" | ".join(map(str, cells)))
        for row in node.get("rows", []):
            yield path, plain_text(" | ".join(str(cell) for cell in row))
    elif "entries" in node:
        # `options` and any shape the renderer also just descends into.
        yield from text_blocks(node["entries"], path)


def _list_item_blocks(item, path: tuple[str, ...]):
    if isinstance(item, str):
        yield path, plain_text(item)
    elif isinstance(item, dict):
        if item.get("type") not in (None, "item"):
            yield from _dict_blocks(item, path)
            return
        name = plain_text(item["name"]) if item.get("name") else ""
        body = item["entry"] if "entry" in item else item.get("entries", [])
        if isinstance(body, str):
            yield path, f"{name} {plain_text(body)}".strip()
        else:
            if name:
                yield path, name
            yield from text_blocks(body, path)


def _snippet(path: tuple[str, ...], text: str, pattern: re.Pattern) -> SafeString:
    """One hit: `path` in bold as a breadcrumb ("Actions › Attack ›"), then `text` cut down to a
    window around its first match, with every match in that window wrapped in `<mark>`.
    """
    folded = fold(text)
    first = pattern.search(folded)
    start = max(0, first.start() - _BEFORE)
    end = min(len(text), first.end() + _AFTER)
    # Start and stop on a word boundary rather than mid-word.
    if start:
        space = text.find(" ", start, first.start())
        if space != -1:
            start = space + 1
    if end < len(text):
        space = text.rfind(" ", first.end(), end)
        if space != -1:
            end = space
    window = text[start:end]

    pieces = []
    last = 0
    # Matched in the folded text, cut from the original: same positions (see `fold()`).
    for match in pattern.finditer(folded[start:end]):
        pieces.append(escape(window[last : match.start()]))
        pieces.append(f"<mark>{escape(window[match.start() : match.end()])}</mark>")
        last = match.end()
    pieces.append(escape(window[last:]))
    body = ("… " if start else "") + "".join(pieces) + (" …" if end < len(text) else "")

    label = f"<b>{escape(_PATH_SEPARATOR.join(path))} ›</b> " if path else ""
    return mark_safe(f'<span class="hit">{label}{body}</span>')


def highlight(text: str, pattern: re.Pattern) -> SafeString:
    """All of `text`, escaped, with every match of `pattern` wrapped in `<mark>` (positions in
    `fold(text)` are positions in `text`, see `fold()`)."""
    pieces = []
    last = 0
    for match in pattern.finditer(fold(text)):
        pieces.append(escape(text[last : match.start()]))
        pieces.append(f"<mark>{escape(text[match.start() : match.end()])}</mark>")
        last = match.end()
    pieces.append(escape(text[last:]))
    return mark_safe("".join(pieces))


def find_hits(
    entries, pattern: re.Pattern, limit: int = SNIPPETS_PER_ENTRY
) -> tuple[list[SafeString], int]:
    """The first `limit` snippets of the blocks of `entries` matching `pattern`, and how many
    blocks matched in all.
    """
    snippets = []
    total = 0
    for path, text in text_blocks(entries):
        if pattern.search(fold(text)):
            total += 1
            if len(snippets) < limit:
                snippets.append(_snippet(path, text, pattern))
    return snippets, total


def name_matches(obj, pattern: re.Pattern) -> bool:
    """Whether `pattern` is in `obj`'s English *or* Italian name (like `views._by_name()`, so an
    English name is found from the Italian site).
    """
    return any(pattern.search(fold(getattr(obj, field) or "")) for field in ("name_en", "name_it"))
