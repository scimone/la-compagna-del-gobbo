"""The server-rendered half of the navigation behaviour. The other half - the per-menu history
stacks and the phone back button - is `static/js/navigation.js`; it reads the markup pinned down
here (`#back-btn`, `data-menu`, `data-nav`, the language form's `next`)."""

import re

import pytest
from django.contrib.auth import get_user_model

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
        "/logbook/",
        "/world/backgrounds/",
        "/world/classes/",
        "/world/species/",
        "/world/feats/",
        "/world/spells/",
    ],
)
def test_menu_roots_have_no_back_arrow(client, db, url):
    # Back at a menu's root does nothing, so there is no arrow to press.
    from django.contrib.auth import get_user_model

    client.force_login(get_user_model().objects.create_user(username="viewer"))
    assert 'id="back-btn"' not in _html(client, url)


def test_glossary_links_back_to_the_handbook(client, db):
    assert re.search(
        r'id="back-btn" class="back-btn" href="/handbook/"',
        _html(client, "/handbook/rules-glossary/"),
    )


def test_nested_pages_link_to_their_parent(client, feats):
    detail = _html(client, "/world/feats/alert/")
    assert re.search(r'id="back-btn" class="back-btn" href="/world/feats/"', detail)


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


def test_handbook_links_to_the_glossary(client, db):
    chapters = _html(client, "/handbook/")
    assert re.search(r'<a class="glossary-button" href="/handbook/rules-glossary/"', chapters)


def test_handbook_is_the_first_world_tab_and_not_in_the_bottom_nav(client, db):
    html = _html(client, "/handbook/")
    assert 'data-menu="handbook"' not in html
    tabs = re.search(r'<nav class="world-tabs">(.*?)</nav>', html, re.S).group(1)
    first = re.search(r'<a\s+data-nav="replace"\s+href="([^"]+)"\s+class="([^"]*)"', tabs)
    assert first.groups() == ("/handbook/", "active")
    other = re.search(
        r'<nav class="world-tabs">(.*?)</nav>', _html(client, "/world/backgrounds/"), re.S
    )
    assert 'href="/handbook/"' in other.group(1)


def test_bottom_nav_items_declare_their_menu_and_the_script_is_loaded(client, db):
    html = _html(client, "/handbook/")
    roots = {
        "characters": "/characters/",
        "logbook": "/logbook/",
        "world": "/world/backgrounds/",
    }
    for menu, root in roots.items():
        # `data-root` is where tapping the menu you are already in leads: World's first tab.
        pattern = rf'<a\s+href="[^"]+"\s+data-menu="{menu}"\s+data-root="{root}"'
        assert re.search(pattern, html), menu
    assert re.search(r'<script src="/static/js/navigation\.js\?v=\d+"></script>', html)


def test_account_forms_leave_the_navigation_history(client, db):
    # Sign-in returns to where you came from; the account page must not stay in between.
    assert 'action="/account/" data-nav="pop"' in _html(client, "/account/")


def _header_actions(client, url="/world/feats/"):
    html = _html(client, url)
    return re.search(r'<div class="header-actions">.*?</header>', html, re.S).group(0)


def test_signed_out_account_button_says_login_after_the_language_switch(client, feats):
    actions = _header_actions(client)
    assert actions.index('class="lang-switcher"') < actions.index("account-link")
    assert re.search(r'class="account-link"[^>]*>\s*<span aria-hidden="true">Login</span>', actions)


def test_signed_in_account_button_shows_the_first_letter_of_the_name(client, feats):
    client.force_login(get_user_model().objects.create_user("anna"))
    actions = _header_actions(client)
    assert actions.index('class="lang-switcher"') < actions.index("account-link")
    assert re.search(
        r'class="account-link signed-in".*?<span aria-hidden="true">A</span>', actions, re.S
    )
    assert "Login" not in actions


def test_login_button_is_translated(client, feats):
    client.cookies["django_language"] = "it"
    assert ">Accedi</span>" in _header_actions(client)
