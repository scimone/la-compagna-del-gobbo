import pytest

from apps.rules.models import Feat, Rule, Spell


@pytest.fixture
def content(db):
    Spell.objects.create(
        id="fireball",
        name="Fireball",
        page=1,
        level=3,
        school="Evocation",
        entries=["A bright streak of flame explodes."],
    )
    Spell.objects.create(
        id="shield", name="Shield", page=1, level=1, school="Abjuration", entries=["Flame ward."]
    )
    Feat.objects.create(id="alert", name="Alert", page=1, category="Origin", entries=["Flame."])
    Rule.objects.create(id="cover", name="Cover", page=1, entries=["Cover gives a bonus."])


def _get(client, **params):
    response = client.get("/world/", params)
    assert response.status_code == 200
    return response.content.decode()


def test_home_without_a_query_shows_a_tile_per_category(client, content):
    html = _get(client)
    for url in ("/handbook/", "/world/spells/", "/world/classes/", "/world/items/"):
        assert f'class="category-tile" href="{url}"' in html
    assert "<h2>" not in html


def test_search_spans_categories_and_ranks_name_matches_first(client, content):
    html = _get(client, q="flame")
    assert 'id="results-spells"' in html and 'id="results-features"' in html
    assert "<mark>flame</mark>" in html.lower() or "<mark>Flame</mark>" in html
    # Fireball's text mentions flame, Shield's too - both appear under Spells.
    spells = html.split('id="results-spells"')[1].split("</section>")[0]
    assert "Fireball" in spells and "Shield" in spells


def test_search_finds_a_rule_by_name(client, content):
    html = _get(client, q="cover")
    assert 'id="results-rules"' in html and "/world/rules/cover/" in html


def test_too_short_and_empty_queries(client, content):
    assert "at least two letters" in _get(client, q="f")
    assert "No results" in _get(client, q="zzzzqq")


def test_category_search_without_hits_offers_the_whole_handbook(client, content):
    html = client.get("/world/spells/", {"q": "zzzzqq"}).content.decode()
    assert "/world/?q=zzzzqq" in html
