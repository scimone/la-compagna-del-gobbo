import re

import pytest

from apps.frontend.handbook_search import find_hits, fold, name_matches, query_pattern, text_blocks
from apps.rules.management.commands.import_rules_data import Command as ImportCommand
from apps.rules.models import Rule


@pytest.fixture
def handbook(db):
    ImportCommand()._import_handbook()


def _search(client, q, language="en"):
    client.cookies["django_language"] = language
    response = client.get("/handbook/", {"q": q})
    assert response.status_code == 200
    return response.content.decode()


def _results(html):
    """The rendered `#search-results` node, i.e. what live search swaps in."""
    return html.split('id="search-results"', 1)[1]


def test_text_blocks_walk_every_shape_with_their_headings():
    entries = [
        "Intro with {@dc 10} in it.",
        {
            "type": "entries",
            "name": "Actions",
            "entries": [
                "Take one.",
                {
                    "type": "list",
                    "items": ["Attack", {"type": "item", "name": "Dash", "entry": "Go."}],
                },
                {
                    "type": "table",
                    "caption": "Speeds",
                    "colLabels": ["Kind", "Feet"],
                    "rows": [["Walk", 30]],
                },
            ],
        },
    ]

    assert list(text_blocks(entries)) == [
        ((), "Intro with DC 10 in it."),
        ((), "Actions"),
        (("Actions",), "Take one."),
        (("Actions",), "Attack"),
        (("Actions",), "Dash Go."),
        (("Actions",), "Speeds"),
        (("Actions",), "Kind | Feet"),
        (("Actions",), "Walk | 30"),
    ]


def test_find_hits_highlights_and_escapes_and_counts_the_rest():
    entries = [f"<b>Bold</b> move {n}" for n in range(5)]

    snippets, total = find_hits(entries, query_pattern("MOVE"))

    assert total == 5 and len(snippets) == 3
    assert "&lt;b&gt;Bold&lt;/b&gt; <mark>move</mark> 0" in snippets[0]
    assert "<b>Bold</b>" not in snippets[0]


def test_a_long_block_is_cut_down_around_the_match():
    text = "word " * 60 + "needle " + "word " * 60

    (snippet,), _ = find_hits([text], query_pattern("needle"))

    assert "<mark>needle</mark>" in snippet and snippet.startswith('<span class="hit">… ')
    assert len(snippet) < len(text) / 2


def test_search_finds_a_section_by_text_that_is_not_in_its_name(client, handbook):
    html = _results(_search(client, "death saving"))

    assert 'href="/handbook/095/"' in html  # Damage and Healing
    assert "<mark>Death Saving</mark>" in html
    assert 'href="/handbook/136/"' not in html  # Weapons doesn't mention it
    # the search box keeps the query
    assert 'value="death saving"' in _search(client, "death saving")


def test_search_matches_the_section_name_alone(client, handbook):
    html = _results(_search(client, "Casting Spells"))

    assert 'href="/handbook/158/"' in html


def test_search_is_grouped_under_the_chapters_and_the_glossary(client, handbook):
    Rule.objects.create(
        id="grappled", name="Grappled", page=1, rule_type="V", entries=["Held in a death grip."]
    )
    html = _results(_search(client, "death"))

    groups = re.findall(
        r'<details class="chapter-group" data-chapter="([\w-]+)" open>\s*<summary>(.*?)</summary>',
        html,
        re.S,
    )
    assert groups[0] == ("search-007", "Playing the Game")
    assert groups[-1] == ("search-glossary", "Glossary")
    assert 'href="/world/rules/grappled/"' in html and "<mark>death</mark> grip" in html


def test_search_reads_the_active_language_but_finds_english_section_names(client, handbook):
    italian = _results(_search(client, "morte", "it"))
    assert 'href="/handbook/095/"' in italian
    assert "<mark>morte</mark>" in italian

    # "Weapons" is only the English name; the Italian site still finds the section by it
    assert 'href="/handbook/136/"' in _results(_search(client, "Weapons", "it"))


def test_search_without_matches_says_so(client, handbook):
    html = _results(_search(client, "zzzzzz"))

    assert 'No results for "zzzzzz".' in html and "chapter-group" not in html


def test_the_contents_page_has_the_search_box(client, handbook):
    client.cookies["django_language"] = "it"
    html = client.get("/handbook/").content.decode()

    assert 'class="world-search"' in html and 'placeholder="Cerca nel manuale"' in html


def test_a_hit_is_headed_by_the_breadcrumb_of_its_headings():
    entries = [{"type": "entries", "name": "Actions", "entries": ["Take the Dash action."]}]

    (snippet,), total = find_hits(entries, query_pattern("dash"))

    assert total == 1
    assert snippet == (
        '<span class="hit"><b>Actions ›</b> Take the <mark>Dash</mark> action.</span>'
    )


def test_fold_drops_accents_and_case_but_keeps_the_length():
    text = "Proprietà dell'Àmbito – ÉCCO ñ"

    assert fold(text) == "proprieta dell'ambito – ecco n"
    assert len(fold(text)) == len(text)


def test_search_ignores_accents_in_the_query_and_in_the_text_and_marks_the_original_wording():
    entries = ["Le proprietà delle armi", "Dopo l'attacco, la Reazione."]

    (snippet,), _ = find_hits(entries, query_pattern("PROPRIETA"))
    assert "Le <mark>proprietà</mark> delle armi" in snippet

    (snippet,), _ = find_hits(entries, query_pattern("reazióne"))  # accent the text lacks
    assert "<mark>Reazione</mark>" in snippet

    # a decomposed accent (a + combining grave), as some keyboards send it
    assert find_hits(entries, query_pattern("proprieta\u0300"))[1] == 1


def test_names_match_without_accents_in_either_language():
    class Named:
        name_en = "Opportunity"
        name_it = "Opportunità"

    assert name_matches(Named, query_pattern("opportunita"))
    assert name_matches(Named, query_pattern("OPPORTUNITÀ"))
    assert not name_matches(Named, query_pattern("opportunitas"))


def test_search_finds_accented_italian_text_typed_without_accents(client, handbook):
    html = _results(_search(client, "opportunita", "it"))

    assert 'href="/handbook/06b/"' in html  # Combattimento
    assert "<mark>opportunità</mark>" in html


def test_the_search_box_sits_under_the_header_and_above_the_results(client, handbook):
    for q in ("", "death"):
        html = _search(client, q)

        before_main, main = html.split("<main>", 1)
        # under the header - not swapped by live search
        assert 'class="world-search"' in before_main
        assert 'class="world-search"' not in main
        assert 'id="search-results"' in main


def test_the_other_search_pages_keep_the_search_box_under_the_header(client, db):
    html = client.get("/handbook/rules-glossary/").content.decode()

    before_main, main = html.split("<main>", 1)
    assert 'class="world-search"' in before_main and 'class="world-search"' not in main
