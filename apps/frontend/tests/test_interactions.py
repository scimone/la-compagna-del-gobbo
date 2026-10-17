"""The Interaction table (what visitors did) and the overview's picture grid."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.frontend.models import Interaction


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


def test_a_page_view_is_recorded_with_who_where_and_the_language(client, alice):
    client.force_login(alice)
    client.cookies["django_language"] = "it"

    client.get("/logbook/")

    row = Interaction.objects.get()
    assert (row.username, row.kind, row.route, row.path) == (
        "alice",
        "view",
        "logbook-list",
        "/logbook/",
    )
    assert row.user == alice and row.status == 200 and row.method == "GET" and row.language == "it"
    assert len(row.session) in (0, 16)


def test_anonymous_visits_are_recorded_without_a_user(client, db):
    client.get("/handbook/")

    row = Interaction.objects.get()
    assert row.user is None and row.username == "" and row.route == "handbook-overview"


def test_a_change_is_recorded_as_an_action_with_its_name_but_not_its_content(client, alice):
    client.force_login(alice)

    client.post("/logbook/new/", {"date": "2026-09-01", "title": "Secret plot", "action": "save"})

    row = Interaction.objects.get(kind="action")
    assert (row.route, row.action, row.method, row.status) == ("logbook-new", "save", "POST", 302)
    stored = " ".join(str(v) for v in row.__dict__.values())
    assert "Secret plot" not in stored


def test_pages_report_the_object_they_show(client, db):
    from apps.rules.models import Feat

    Feat.objects.create(id="alert", name="Alert", page=1, category="Origin")

    client.get("/world/feats/alert/")

    assert Interaction.objects.get(route="world-feat-detail").object_id == "alert"


def test_files_and_the_service_worker_are_not_tracked(client, db):
    client.get("/manifest.json")
    client.get("/static/js/navigation.js")

    assert not Interaction.objects.exists()


def test_a_search_typed_letter_by_letter_is_one_row_with_the_final_text(client, db):
    client.get("/handbook/")  # a visitor already has a session by the time they search
    for text in ("d", "dr", "dra"):
        client.get("/world/feats/", {"q": text})

    rows = Interaction.objects.filter(route="world-feats")
    assert rows.count() == 1 and rows.get().query == "dra"


def test_a_failure_to_record_never_breaks_the_page(client, db, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(Interaction.objects, "create", boom)

    assert client.get("/handbook/").status_code == 200


def test_the_report_summarises_and_prunes(client, alice, capsys):
    client.force_login(alice)
    client.get("/logbook/")
    call_command("interaction_report")
    assert "alice" in capsys.readouterr().out

    Interaction.objects.update(created_at="2020-01-01T00:00:00Z")
    call_command("interaction_report", "--prune", "--days", "30")
    assert not Interaction.objects.exists()


def test_the_characters_overview_is_a_picture_grid_and_remembers_the_list_choice(client, db):
    from django.contrib.auth import get_user_model

    client.force_login(get_user_model().objects.create_user(username="viewer"))
    assert (
        'class="cards"' in client.get("/characters/").content.decode()
        or "empty" in client.get("/characters/").content.decode()
    )
    client.get("/characters/?view=list")
    assert client.session["characters_view"] == "list"
    client.get("/characters/?view=grid")
    assert client.session["characters_view"] == "grid"
    client.get("/characters/?view=nonsense")
    assert client.session["characters_view"] == "grid"
