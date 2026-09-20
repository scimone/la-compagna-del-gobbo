"""The server-rendered half of the navigation behaviour. The other half - the per-menu history
stacks and the phone back button - is `static/js/navigation.js`; it reads the markup pinned down
here (`#back-btn`, `data-menu`, `data-nav`, the language form's `next`)."""

import re

import pytest

from apps.rules.models import Feat


@pytest.fixture
def feats(db):
    Feat.objects.create(id="alert", name="Alert", page=1, category="Origin")
    Feat.objects.create(id="tough", name="Tough", page=1, category="Origin")


def _html(client, url):
    response = client.get(url)
    assert response.status_code == 200, url
    return response.content.decode()


@pytest.mark.parametrize(
    "url",
    [
        "/characters/",
        "/handbook/",
        "/world/backgrounds/",
        "/world/classes/",
        "/world/species/",
        "/world/feats/",
        "/world/spells/",
    ],
)
def test_menu_roots_have_no_back_arrow(client, db, url):
    # Back at a menu's root does nothing, so there is no arrow to press.
    assert 'id="back-btn"' not in _html(client, url)


def test_nested_pages_link_to_their_parent(client, feats):
    detail = _html(client, "/world/feats/alert/")
    assert re.search(r'id="back-btn" class="back-btn" href="/world/feats/"', detail)

    glossary = _html(client, "/handbook/rules-glossary/")
    assert re.search(r'id="back-btn" class="back-btn" href="/handbook/"', glossary)


def test_language_switch_returns_to_the_same_url_including_the_query(client, feats):
    html = _html(client, "/world/feats/?q=tou")
    form = re.search(r'<form[^>]*class="lang-switcher".*?</form>', html, re.S).group(0)
    assert 'name="next" value="/world/feats/?q=tou"' in form
    assert 'data-nav="replace"' in form


def test_setlang_keeps_the_query_string_of_next(client, db):
    # A page's tab lives in `?tab=`; dropping it sent the user back to the first tab.
    response = client.post(
        "/i18n/setlang/", {"language": "it", "next": "/world/feats/alert/?tab=levels"}
    )
    assert response.status_code == 302
    assert response["Location"] == "/world/feats/alert/?tab=levels"


def test_tab_switches_and_search_replace_the_history_entry(client, feats):
    html = _html(client, "/world/feats/")
    for url in (
        "/world/backgrounds/",
        "/world/classes/",
        "/world/species/",
        "/world/feats/",
        "/world/spells/",
    ):
        assert re.search(rf'data-nav="replace"\s+href="{re.escape(url)}"', html), url
    assert re.search(r'<form class="world-search"[^>]*data-nav="replace"', html)


def test_bottom_nav_items_declare_their_menu_and_the_script_is_loaded(client, db):
    html = _html(client, "/handbook/")
    for menu in ("characters", "handbook", "world"):
        assert re.search(rf'<a\s+href="[^"]+"\s+data-menu="{menu}"', html), menu
    assert '<script src="/static/js/navigation.js"></script>' in html


def test_account_forms_leave_the_navigation_history(client, db):
    # Sign-in returns to where you came from; the account page must not stay in between.
    assert 'action="/account/" data-nav="pop"' in _html(client, "/account/")
