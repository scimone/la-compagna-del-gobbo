import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.frontend.models import Bookmark
from apps.rules.models import Feat

User = get_user_model()


@pytest.fixture
def feats(db):
    Feat.objects.create(id="alert", name="Alert", page=1, category="Origin")


def _sign_in(client, name, **extra):
    return client.post("/account/", {"username": name, **extra})


def _toggle(client, kind, object_id, **extra):
    return client.post("/bookmarks/toggle/", {"kind": kind, "object_id": object_id, **extra})


def test_typing_a_new_name_creates_a_passwordless_account_and_signs_in(client, db):
    response = _sign_in(client, "Alice", next="/world/feats/")
    assert response.status_code == 302 and response["Location"] == "/world/feats/"

    user = User.objects.get(username="Alice")
    assert not user.has_usable_password()
    assert client.session["_auth_user_id"] == str(user.pk)


def test_the_same_name_in_any_case_signs_in_to_the_same_account(client, db):
    _sign_in(client, "Alice")
    other_device = Client()
    _sign_in(other_device, "aLICE")

    assert User.objects.count() == 1
    assert other_device.session["_auth_user_id"] == client.session["_auth_user_id"]


def test_a_password_protected_account_cannot_be_signed_into_by_name(client, db):
    User.objects.create_superuser("admin", password="s3cret-pass")
    response = _sign_in(client, "admin")

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert "can&#x27;t be used to sign in" in response.content.decode()


def test_invalid_names_are_rejected(client, db):
    assert _sign_in(client, "two words").status_code == 200
    assert _sign_in(client, "   ").status_code == 200
    assert not User.objects.exists()


def test_sign_in_never_redirects_offsite(client, db):
    response = _sign_in(client, "Alice", next="https://evil.example/")
    assert response["Location"] == "/world/"


def test_sign_out_ends_the_session(client, db):
    _sign_in(client, "Alice")
    assert client.post("/account/logout/").status_code == 302
    assert "_auth_user_id" not in client.session
    assert client.get("/account/logout/").status_code == 405


def test_account_page_shows_the_form_signed_out_and_the_name_signed_in(client, db):
    assert 'name="username"' in client.get("/account/").content.decode()

    _sign_in(client, "Alice")
    html = client.get("/account/").content.decode()
    assert "<strong>Alice</strong>" in html and 'name="username"' not in html


def test_signed_out_pages_have_no_bookmark_buttons(client, feats):
    detail = client.get("/world/feats/alert/").content.decode()
    listing = client.get("/world/feats/").content.decode()
    assert 'id="bookmark-form"' not in detail
    assert "item-bookmark" not in listing.split('id="search-results"')[1]
    assert "Alert" in listing  # the list itself still renders


def test_bookmarks_are_private_to_each_account(client, feats):
    _sign_in(client, "Alice")
    _toggle(client, "feat", "alert")

    bob = Client()
    _sign_in(bob, "Bob")
    assert 'aria-pressed="false"' in bob.get("/world/feats/alert/").content.decode()
    assert "item-list bookmark-list" not in bob.get("/world/feats/").content.decode()

    # Bob bookmarking the same feat doesn't touch Alice's, and un-bookmarking his leaves hers.
    _toggle(bob, "feat", "alert")
    assert Bookmark.objects.count() == 2
    _toggle(bob, "feat", "alert")
    assert list(Bookmark.objects.values_list("user__username", flat=True)) == ["Alice"]
    assert 'aria-pressed="true"' in client.get("/world/feats/alert/").content.decode()


def test_toggling_signed_out_is_refused(client, feats):
    ajax = client.post(
        "/bookmarks/toggle/",
        {"kind": "feat", "object_id": "alert"},
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    assert ajax.status_code == 401

    plain = _toggle(client, "feat", "alert", next="/world/feats/alert/")
    assert plain.status_code == 302
    assert plain["Location"] == "/account/?next=/world/feats/alert/"
    assert not Bookmark.objects.exists()
