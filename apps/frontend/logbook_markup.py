"""The Logbook's text format: a small Markdown subset, stored as plain text.

`**bold**`, `*italic*`, `[text](/page-or-https://address)`, `## heading`, `- bullet` and
`1. numbered` lines, `> quote` lines; a blank line separates paragraphs and a single line
break stays a line break (so entries written before the editor existed still read the same).
A backslash makes the next character literal.

The editor (`static/js/logbook_editor.js`) writes this format, but what is stored may come from
anyone, so `render` never trusts it: everything is escaped, and the only tags it can produce are
the ones below.
"""

import re

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from apps.frontend.handbook_search import highlight

_INLINE = re.compile(r"\\(\S)|\[(.+?)\]\((\S+?)\)|\*\*(.+?)\*\*|\*(.+?)\*", re.S)
#: A link goes to a page of this site (`/...`) or to a web address; nothing else (no `javascript:`).
_SAFE_URL = re.compile(r"/(?!/)\S*|https?://\S+")
_BULLET = re.compile(r"- (.*)")
_NUMBER = re.compile(r"\d+\. (.*)")
_HEADING = re.compile(r"##+ (.*)")
_QUOTE = re.compile(r">\s?(.*)")


def _plain(text: str, pattern) -> str:
    return highlight(text, pattern) if pattern else escape(text)


def _inline(text: str, pattern) -> str:
    out = []
    last = 0
    for match in _INLINE.finditer(text):
        out.append(_plain(text[last : match.start()], pattern))
        if match.group(1):
            out.append(_plain(match.group(1), pattern))
        elif match.group(2) is not None:
            url = match.group(3)
            if _SAFE_URL.fullmatch(url):
                external = ' target="_blank" rel="noopener noreferrer"' if url[0] != "/" else ""
                out.append(
                    f'<a href="{escape(url)}"{external}>{_inline(match.group(2), pattern)}</a>'
                )
            else:
                out.append(_plain(match.group(0), pattern))
        elif match.group(4) is not None:
            out.append(f"<strong>{_inline(match.group(4), pattern)}</strong>")
        else:
            out.append(f"<em>{_inline(match.group(5), pattern)}</em>")
        last = match.end()
    out.append(_plain(text[last:], pattern))
    return "".join(out)


def render(text: str, pattern=None) -> SafeString:
    """`text` as HTML. With `pattern` (a compiled search regex), its matches are wrapped in
    `<mark>` - inside each piece of plain text, so one spanning a bold edge is not marked."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        for regex, tag in ((_BULLET, "ul"), (_NUMBER, "ol"), (_QUOTE, "blockquote")):
            if not regex.fullmatch(line):
                continue
            items = []
            while i < len(lines) and (m := regex.fullmatch(lines[i])):
                items.append(_inline(m.group(1), pattern))
                i += 1
            if tag == "blockquote":
                blocks.append(f"<blockquote>{'<br>'.join(items)}</blockquote>")
            else:
                blocks.append(f"<{tag}>{''.join(f'<li>{x}</li>' for x in items)}</{tag}>")
            break
        else:
            if m := _HEADING.fullmatch(line):
                blocks.append(f"<h3>{_inline(m.group(1), pattern)}</h3>")
                i += 1
                continue
            para = []
            while (
                i < len(lines)
                and lines[i].strip()
                and not any(r.fullmatch(lines[i]) for r in (_BULLET, _NUMBER, _QUOTE, _HEADING))
            ):
                para.append(_inline(lines[i], pattern))
                i += 1
            blocks.append(f"<p>{'<br>'.join(para)}</p>")
    return mark_safe("".join(blocks))  # noqa: S308 - every piece is escaped above
