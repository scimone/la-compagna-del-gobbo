"""The Logbook menu: a shared timeline anyone reads, anyone signed in adds to."""

import datetime

import pytest
from django.contrib.auth import get_user_model

from apps.frontend.models import LogEntry


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


@pytest.fixture
def bob(db):
    return get_user_model().objects.create_user("bob")


def _entry(author, **fields):
    fields.setdefault("date", datetime.date(2026, 9, 1))
    return LogEntry.objects.create(author=author, **fields)


def test_the_list_is_public_newest_first_with_one_dot_per_entry(client, alice):
    _entry(alice, date=datetime.date(2026, 8, 1), title="Old tale", text="Goblin ambush")
    _entry(alice, date=datetime.date(2026, 9, 1), title="New tale", text="Waterdeep")

    html = client.get("/logbook/").content.decode()

    assert html.count('class="log-dot"') == 2
    assert html.index("New tale") < html.index("Old tale")
    assert "Waterdeep" in html and "Goblin ambush" in html
    assert "/logbook/new/" in html


def test_the_bottom_nav_has_a_logbook_item(client, db):
    html = client.get("/handbook/").content.decode()

    assert 'data-menu="logbook"' in html and 'data-root="/logbook/"' in html


def test_signed_out_visitors_are_sent_to_sign_in_to_add(client, db):
    assert client.get("/logbook/new/").url.startswith("/account/?next=")
    assert client.post("/logbook/new/", {"date": "2026-09-01"}).status_code == 302
    assert LogEntry.objects.count() == 0


def test_a_new_entry_form_prefills_today_and_saves_with_the_author(client, alice):
    client.force_login(alice)

    html = client.get("/logbook/new/").content.decode()
    assert f'value="{datetime.date.today().isoformat()}"' in html

    response = client.post(
        "/logbook/new/",
        {
            "date": "2026-09-20",
            "title": "The map",
            "text": "The duke lies",
        },
    )

    entry = LogEntry.objects.get()
    assert response.url == f"/logbook/#entry-{entry.pk}"
    assert entry.author == alice and entry.date == datetime.date(2026, 9, 20)
    assert entry.kind == "objective" and entry.title == "The map" and entry.text == "The duke lies"


def test_an_entry_needs_a_date(client, alice):
    client.force_login(alice)

    response = client.post("/logbook/new/", {"date": "", "text": "Nowhere"})

    assert response.status_code == 200 and LogEntry.objects.count() == 0


def test_only_the_author_or_an_admin_edits_or_deletes(client, alice, bob, settings):
    entry = _entry(alice, title="Mine")

    client.force_login(bob)
    assert client.get(f"/logbook/{entry.pk}/edit/").status_code == 404
    assert client.post(f"/logbook/{entry.pk}/delete/").status_code == 404
    assert "Edit entry" not in client.get("/logbook/").content.decode()

    client.force_login(alice)
    assert (
        client.post(
            f"/logbook/{entry.pk}/edit/", {"date": "2026-09-02", "title": "Better"}
        ).status_code
        == 302
    )
    entry.refresh_from_db()
    assert entry.title == "Better" and entry.date == datetime.date(2026, 9, 2)

    settings.ADMIN_ACCOUNTS = ["bob"]
    client.force_login(bob)
    assert client.post(f"/logbook/{entry.pk}/delete/").status_code == 302
    assert LogEntry.objects.count() == 0


def _hero(owner, name="Hero", **fields):
    from apps.characters.models import Character

    return Character.objects.create(name=name, owner=owner, **fields)


def test_a_personal_entry_needs_a_character_and_shows_it_apart(client, alice, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    hero = _hero(alice, "Gobbo")
    client.force_login(alice)

    page = client.get("/logbook/new/?kind=personal").content.decode()
    assert "Gobbo" in page and f'value="{hero.pk}" selected' in page  # own character preselected

    assert (
        client.post("/logbook/new/?kind=personal", {"date": "2026-09-02", "text": "x"}).status_code
        == 200
    )
    assert LogEntry.objects.count() == 0

    response = client.post(
        "/logbook/new/?kind=personal",
        {"date": "2026-09-02", "character": hero.pk, "text": "I did not like the duke."},
    )
    entry = LogEntry.objects.get()
    assert response.status_code == 302
    assert entry.kind == "personal" and entry.character == hero and entry.title == ""

    html = client.get("/logbook/").content.decode()
    assert "log-entry personal" in html and "Gobbo" in html and "log-avatar" in html
    assert "I did not like the duke." in html


def test_a_personal_entry_shows_the_characters_round_picture(client, alice, settings, tmp_path):
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    from apps.characters.services import portrait

    settings.MEDIA_ROOT = tmp_path
    hero = _hero(alice)
    raw = BytesIO()
    Image.new("RGB", (200, 400), "teal").save(raw, "PNG")
    portrait.set_portrait(hero, SimpleUploadedFile("x.png", raw.getvalue()), (0.5, 0.2, 2))
    _entry(alice, kind="personal", character=hero, text="Hi")

    html = client.get("/logbook/").content.decode()
    assert f"/characters/{hero.pk}/avatar/?v=" in html

    avatar = client.get(f"/characters/{hero.pk}/avatar/")
    image = Image.open(BytesIO(avatar.content))
    assert avatar.status_code == 200 and image.size == (256, 256)


def test_an_objective_entry_has_no_character_picture(client, alice):
    _entry(alice, title="Tale", text="Body")

    html = client.get("/logbook/").content.decode()
    assert "log-avatar" not in html.split("<ol")[1] and "personal" not in html.split("<ol")[1]


def test_the_form_has_the_editor_and_the_list_renders_the_formatting(client, alice):
    client.force_login(alice)
    page = client.get("/logbook/new/").content.decode()
    assert "data-rte" in page and "logbook_editor.js" in page

    client.post(
        "/logbook/new/", {"date": "2026-09-20", "title": "T", "text": "**bold**\n\n- a\n- b"}
    )
    html = client.get("/logbook/").content.decode()
    assert "<strong>bold</strong>" in html and "<ul><li>a</li><li>b</li></ul>" in html

    entry = LogEntry.objects.get()
    edit = client.get(f"/logbook/{entry.pk}/edit/").content.decode()
    assert "<strong>bold</strong>" in edit  # the editor starts from the stored text, rendered
