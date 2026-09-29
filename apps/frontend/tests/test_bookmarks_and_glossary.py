import pytest
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string

from apps.frontend.models import Bookmark
from apps.frontend.views import _index_letter
from apps.rules.models import Class, ClassLevel, Feat, Feature, Rule


@pytest.fixture
def client(client, db):
    """Bookmarks are per account, so every test here browses signed in."""
    client.force_login(get_user_model().objects.create_user("tester"))
    return client


@pytest.fixture
def rules(db):
    for rule_id, name in [
        ("advantage", "Advantage"),
        ("armor-class", "Armor Class"),
        ("bonus-action", "Bonus Action"),
        ("cover", "Cover"),
    ]:
        Rule.objects.create(id=rule_id, name=name, page=1, rule_type="V")


@pytest.fixture
def feats(db):
    Feat.objects.create(id="alert", name="Alert", page=1, category="Origin")
    Feat.objects.create(id="tough", name="Tough", page=1, category="Origin")


@pytest.fixture
def class_feature(db):
    klass = Class.objects.create(id="wizard", name="Wizard", page=1, hit_die="d6")
    level = ClassLevel.objects.create(klass=klass, level=1)
    return Feature.objects.create(class_level=level, name="Arcane Recovery")


def _toggle(client, kind, object_id, **extra):
    return client.post("/bookmarks/toggle/", {"kind": kind, "object_id": object_id, **extra})


def test_index_letter_strips_accents_and_files_non_letters_under_hash():
    assert _index_letter("Àmbito") == "A"
    assert _index_letter("  élite") == "E"
    assert _index_letter("1st Level") == "#"
    assert _index_letter("(odd)") == "O"
    assert _index_letter("") == "#"


def test_toggling_a_bookmark_creates_then_removes_it(client, feats):
    response = _toggle(client, "feat", "alert", next="/world/feats/alert/")
    assert response.status_code == 302 and response["Location"] == "/world/feats/alert/"
    assert Bookmark.objects.filter(kind="feat", object_id="alert").exists()

    ajax = client.post(
        "/bookmarks/toggle/",
        {"kind": "feat", "object_id": "alert"},
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    assert ajax.json() == {"bookmarked": False}
    assert not Bookmark.objects.exists()


def test_toggle_rejects_unknown_targets_and_offsite_redirects(client, feats):
    assert _toggle(client, "monster", "alert").status_code == 404
    assert _toggle(client, "feat", "no-such-feat").status_code == 404
    assert _toggle(client, "feat", "alert", next="https://evil.example/").url == "/world/"
    assert client.get("/bookmarks/toggle/").status_code == 405


def test_detail_page_shows_the_bookmark_button_in_its_current_state(client, feats):
    html = client.get("/world/feats/alert/").content.decode()
    assert 'id="bookmark-form"' in html
    assert 'class="bookmark-btn"' in html and 'aria-pressed="false"' in html

    _toggle(client, "feat", "alert")
    html = client.get("/world/feats/alert/").content.decode()
    assert 'class="bookmark-btn active"' in html and 'aria-pressed="true"' in html


def test_list_moves_bookmarked_entries_to_a_highlighted_block_above_the_list(client, feats):
    html = client.get("/world/feats/").content.decode()
    assert "item-list bookmark-list" not in html
    # every entry has its own toggle, all tied to the one shared form
    assert html.count('class="item-bookmark"') == 2
    assert 'form="bookmark-list-form"' in html and 'value="tough"' in html

    _toggle(client, "feat", "tough")
    html = client.get("/world/feats/").content.decode()
    pinned = html.split("item-list bookmark-list")[1].split("</ul>")[0]
    rest = html.split('class="item-list main-list')[1]
    assert "Tough" in pinned and "Alert" not in pinned
    assert "Tough" not in rest and "Alert" in rest  # not listed twice
    assert 'class="item-bookmark active"' in html and 'class="item-bookmark"' in html

    # ... and only while it matches the current search
    found = client.get("/world/feats/?q=alert").content.decode()
    assert "item-list bookmark-list" not in found


def test_a_class_feature_bookmarks_under_its_own_kind_alongside_feats(client, feats, class_feature):
    # The merged Features list mixes Feat rows (kind "feat", a string pk) with Feature rows
    # (kind "feature", an int pk) under the one shared bookmark form - each entry's own
    # `<kind>:<pk>` button value (see `_list_item.html`) must reach the right `BOOKMARK_MODELS`
    # catalog, and
    # the int pk must still compare equal to `Bookmark.object_id`, a `CharField`.
    html = client.get("/world/feats/").content.decode()
    assert "Arcane Recovery" in html
    row = next(chunk for chunk in html.split("<li") if "Arcane Recovery" in chunk)
    assert f'value="feature:{class_feature.pk}"' in row

    # The list's own kind is "feat": the entry's prefix must win over it.
    client.post("/bookmarks/toggle/", {"kind": "feat", "object_id": f"feature:{class_feature.pk}"})
    client.post("/bookmarks/toggle/", {"kind": "feat", "object_id": "feature:nope"})
    client.post("/bookmarks/toggle/", {"kind": "feature", "object_id": "alert"})
    _toggle(client, "feature", str(class_feature.pk), next="/world/feats/")
    client.post("/bookmarks/toggle/", {"kind": "feat", "object_id": f"feature:{class_feature.pk}"})
    assert Bookmark.objects.filter(kind="feature", object_id=str(class_feature.pk)).exists()

    html = client.get("/world/feats/").content.decode()
    pinned = html.split("item-list bookmark-list")[1].split("</ul>")[0]
    rest = html.split('class="item-list main-list')[1]
    assert "Arcane Recovery" in pinned and "Arcane Recovery" not in rest


def test_a_list_with_only_bookmarked_entries_still_renders_them(client, feats):
    _toggle(client, "feat", "alert")
    _toggle(client, "feat", "tough")
    html = client.get("/world/feats/").content.decode()
    assert "Alert" in html and "Tough" in html and "No entries" not in html


def test_handbook_chapter_and_glossary_rows_have_no_icon(client, rules):
    for url in ("/handbook/", "/handbook/rules-glossary/"):
        html = client.get(url).content.decode()
        assert "page-icon" not in html and '<svg viewBox="0 0 36 26"' not in html


def test_glossary_searches_live_from_the_first_letter_and_indexes_by_letter(client, rules):
    html = client.get("/handbook/rules-glossary/").content.decode()
    assert 'class="world-search"' in html
    assert '<li data-letter="A">' in html
    strip = html.split('class="alpha-index"')[1].split("</div>")[0]
    assert [f'data-letter="{letter}"' in strip for letter in "ABC"] == [True, True, True]
    assert 'data-letter="D"' not in strip

    found = client.get("/handbook/rules-glossary/?q=c").content.decode()
    assert "Cover" in found and "Armor Class" in found  # "c" anywhere in the name
    assert "Advantage" not in found.split('id="search-results"')[1]


def test_vignette_is_an_overlay_wrapper_not_a_box_shadow_on_the_image():
    # An inset box-shadow on the <img> itself is painted beneath the image and never shows,
    # so the vignette needs a wrapper (its ::after draws over the picture).
    item = {"name": "Acolyte", "url": "/x/", "image": "/static/images/backgrounds/acolyte.jpeg"}
    with_vignette = render_to_string(
        "frontend/_list_item.html", {"item": item, "image_vignette": True}
    )
    without = render_to_string("frontend/_list_item.html", {"item": item, "image_vignette": False})

    assert '<span class="thumb-vignette">' in with_vignette
    assert "thumb-vignette" not in without and 'class="item-thumb"' in without
