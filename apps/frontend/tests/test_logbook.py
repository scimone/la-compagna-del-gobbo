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
    _entry(alice, date=datetime.date(2026, 8, 1), title="Old tale", fights="Goblin ambush")
    _entry(alice, date=datetime.date(2026, 9, 1), title="New tale", location="Waterdeep")

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
            "location": "Neverwinter",
            "characters_met": "Sildar",
            "fights": "Wolves",
            "objectives": "Find the map",
            "insights": "The duke lies",
        },
    )

    entry = LogEntry.objects.get()
    assert response.url == f"/logbook/#entry-{entry.pk}"
    assert entry.author == alice and entry.date == datetime.date(2026, 9, 20)
    assert entry.characters_met == "Sildar" and entry.insights == "The duke lies"


def test_an_entry_needs_a_date(client, alice):
    client.force_login(alice)

    response = client.post("/logbook/new/", {"date": "", "location": "Nowhere"})

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
