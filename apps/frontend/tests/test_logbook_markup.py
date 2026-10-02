"""The Logbook's Markdown subset: rendered safely, whatever is stored."""

from apps.frontend.handbook_search import query_pattern
from apps.frontend.logbook_markup import render


def test_bold_italic_and_nesting():
    assert render("a **b *c* d** *e*") == "<p>a <strong>b <em>c</em> d</strong> <em>e</em></p>"


def test_lists_headings_quotes_and_paragraphs():
    html = render(
        "## Title\n\n- one\n- two\n\n1. first\n2. second\n\n> wise\n> words\n\nplain\nline"
    )
    assert html == (
        "<h3>Title</h3><ul><li>one</li><li>two</li></ul>"
        "<ol><li>first</li><li>second</li></ol>"
        "<blockquote>wise<br>words</blockquote><p>plain<br>line</p>"
    )


def test_old_plain_text_keeps_its_line_breaks():
    assert render("Fights:\nGoblins\n\nNotes:\nNone") == (
        "<p>Fights:<br>Goblins</p><p>Notes:<br>None</p>"
    )


def test_html_is_escaped_and_backslash_makes_literal():
    assert render("<script>x</script> \\*not\\* \\- no") == (
        "<p>&lt;script&gt;x&lt;/script&gt; *not* - no</p>"
    )
    assert render("\\- not a bullet") == "<p>- not a bullet</p>"


def test_search_matches_are_marked_inside_the_formatting():
    html = render("a **Dragon** b", query_pattern("dragon"))
    assert html == "<p>a <strong><mark>Dragon</mark></strong> b</p>"


def test_links_only_to_this_site_or_the_web():
    assert render("[a](/x/?t=1).") == '<p><a href="/x/?t=1">a</a>.</p>'
    assert render("[a](//evil.test)") == "<p>[a](//evil.test)</p>"
    assert render("[a](javascript:1)") == "<p>[a](javascript:1)</p>"
    assert render("\\[a](/x)") == "<p>[a](/x)</p>"
