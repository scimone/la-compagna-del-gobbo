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


def test_the_list_is_public_newest_last_with_one_dot_per_entry(client, alice):
    _entry(alice, date=datetime.date(2026, 8, 1), title="Old tale", text="Goblin ambush")
    _entry(alice, date=datetime.date(2026, 9, 1), title="New tale", text="Waterdeep")

    html = client.get("/logbook/").content.decode()

    assert html.count('class="log-dot"') == 2
    assert html.index("Old tale") < html.index("New tale")
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


def test_a_player_writes_a_personal_entry_as_their_only_character(
    client, alice, bob, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    hero = _hero(alice, "Gobbo")
    _hero(bob, "Other")
    client.force_login(alice)

    page = client.get("/logbook/new/?kind=personal").content.decode()
    assert "id_character" not in page and "kinds" not in page  # nothing to choose, no kind switch

    # Even a forged `character` cannot make someone else's character write.
    response = client.post(
        "/logbook/new/?kind=personal",
        {
            "date": "2026-09-02",
            "character": _hero(bob, "Third").pk,
            "text": "I did not like the duke.",
        },
    )
    entry = LogEntry.objects.get()
    assert response.status_code == 302
    assert entry.kind == "personal" and entry.character == hero and entry.title == ""

    html = client.get("/logbook/").content.decode()
    assert "log-entry personal" in html and "Gobbo" in html and "log-avatar" in html
    assert "log-bubble" in html and "log-kind" not in html and "?kind=personal" in html
    assert "I did not like the duke." in html
    assert "full backstory" not in html  # nothing is added to new messages by itself


def test_a_player_with_several_characters_chooses_among_their_own(client, alice, bob):
    mine, also = _hero(alice, "Aa"), _hero(alice, "Bb")
    theirs = _hero(bob, "Cc")
    client.force_login(alice)

    page = client.get("/logbook/new/?kind=personal").content.decode()
    assert "id_character" in page and "Aa" in page and "Bb" in page and "Cc" not in page

    bad = client.post("/logbook/new/?kind=personal", {"date": "2026-09-02", "character": theirs.pk})
    assert bad.status_code == 200 and LogEntry.objects.count() == 0
    client.post("/logbook/new/?kind=personal", {"date": "2026-09-02", "character": also.pk})
    assert LogEntry.objects.get().character == also and mine


def test_only_an_admin_picks_any_character_and_without_one_nothing_is_saved(
    client, alice, bob, settings
):
    hero = _hero(alice, "Gobbo")
    client.force_login(bob)
    page = client.get("/logbook/new/?kind=personal").content.decode()
    assert "id_character" not in page
    response = client.post("/logbook/new/?kind=personal", {"date": "2026-09-02", "text": "x"})
    assert response.status_code == 200 and LogEntry.objects.count() == 0
    assert "need a finished character" in response.content.decode()

    settings.ADMIN_ACCOUNTS = ["bob"]
    page = client.get("/logbook/new/?kind=personal").content.decode()
    assert "id_character" in page and "Gobbo" in page
    client.post("/logbook/new/?kind=personal", {"date": "2026-09-02", "character": hero.pk})
    assert LogEntry.objects.get().character == hero


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
    assert "log-avatar" not in html.split("<ol")[1] and "log-entry personal" not in html


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


def test_the_markdown_preview_renders_for_signed_in_users_only(client, alice):
    assert client.post("/logbook/preview/", {"text": "**x**"}).status_code == 404
    client.force_login(alice)
    response = client.post("/logbook/preview/", {"text": "**x** <i>"})
    assert response.content.decode() == "<p><strong>x</strong> &lt;i&gt;</p>"
    assert client.get("/logbook/preview/").status_code == 405


def test_links_in_the_text_become_links_but_only_safe_ones(client, alice):
    _entry(
        alice,
        title="T",
        text="[bio](/characters/1/?tab=biography). [x](javascript:alert(1)) [y](https://e.org)",
    )

    html = client.get("/logbook/").content.decode()
    assert '<a href="/characters/1/?tab=biography">bio</a>.' in html
    assert '<a href="javascript' not in html
    assert '<a href="https://e.org" target="_blank" rel="noopener noreferrer">y</a>' in html


def test_messages_sit_above_the_entries_of_their_day_oldest_first(client, alice):
    from apps.characters.models import Character

    hero = Character.objects.create(name="Gobbo", owner=alice)
    day, earlier = datetime.date(2026, 9, 6), datetime.date(2026, 9, 1)
    _entry(alice, date=day, kind="personal", character=hero, text="msg-one")
    _entry(alice, date=day, kind="personal", character=hero, text="msg-two")
    _entry(alice, date=day, title="entry-b", text="x")
    _entry(alice, date=earlier, title="entry-old", text="y")
    _entry(alice, date=day, title="entry-c", text="x")

    html = client.get("/logbook/").content.decode()
    order = [html.index(x) for x in ("entry-old", "msg-one", "msg-two", "entry-b", "entry-c")]

    assert order == sorted(order)
    assert "Adventure Log of 6 Sep 2026" in html
    assert "machine-translated" not in html.lower()


def test_only_the_dm_and_admins_can_post_as_dm(client, alice, bob, settings, tmp_path):
    from apps.frontend.models import LogEntry

    settings.MEDIA_ROOT = tmp_path
    settings.ADMIN_ACCOUNTS = []
    settings.DM_ACCOUNTS = ["alice"]
    _hero(alice, "Gobbo")
    _hero(bob, "Other")
    data = {"date": "2026-09-02", "text": "The door creaks open.", "character": ""}

    client.force_login(bob)  # a plain player: no DM option, and a forged empty choice is no DM
    assert "DM</option>" not in client.get("/logbook/new/?kind=personal").content.decode()
    client.post("/logbook/new/?kind=personal", data)
    assert not LogEntry.objects.filter(as_dm=True).exists()

    client.force_login(alice)  # the DM
    assert "DM</option>" in client.get("/logbook/new/?kind=personal").content.decode()
    assert client.post("/logbook/new/?kind=personal", data).status_code == 302
    entry = LogEntry.objects.get(as_dm=True)
    assert entry.character is None
    page = client.get("/logbook/").content.decode()
    assert "log-entry personal dm" in page

    settings.DM_ACCOUNTS = []  # an administrator may too
    settings.ADMIN_ACCOUNTS = ["alice"]
    assert "DM</option>" in client.get("/logbook/new/?kind=personal").content.decode()
