import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.frontend import cloudflare_access

AUD = "test-aud-tag"
TEAM = "travolator"
ISSUER = f"https://{TEAM}.cloudflareaccess.com"
User = get_user_model()


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def access_on(settings, monkeypatch, private_key):
    settings.CF_ACCESS_TEAM_DOMAIN = TEAM
    settings.CF_ACCESS_AUD = AUD
    # The real key set is fetched over the network; hand out the test key instead.
    client = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key())
    )
    monkeypatch.setattr(cloudflare_access, "_jwks_client", lambda url: client)


def token(private_key, email="gino@example.com", aud=AUD, iss=ISSUER, exp=3600):
    claims = {"aud": [aud], "iss": iss, "exp": int(time.time()) + exp, "sub": "abc"}
    if email is not None:
        claims["email"] = email
    return jwt.encode(claims, private_key, algorithm="RS256")


def get(client, jwt_value=None):
    headers = {"HTTP_CF_ACCESS_JWT_ASSERTION": jwt_value} if jwt_value else {}
    return client.get("/account/", **headers)


@pytest.mark.django_db
def test_first_visit_creates_and_signs_in_the_account(client, private_key):
    response = get(client, token(private_key, "Gino@Example.com"))
    user = User.objects.get(email="gino@example.com")
    assert user.username == "gino@example.com"
    assert not user.has_usable_password()
    assert response.wsgi_request.user == user
    # No name yet: every page leads to the welcome page, which asks for one.
    assert response.status_code == 302 and response["Location"].startswith("/welcome/")
    jwt_value = token(private_key, "Gino@Example.com")
    headers = {"HTTP_CF_ACCESS_JWT_ASSERTION": jwt_value}
    assert (
        client.post("/welcome/", {"name": "Gino", "next": "/account/"}, **headers).status_code
        == 302
    )
    user.refresh_from_db()
    assert user.first_name == "Gino"
    assert b"Gino" in get(client, jwt_value).content


@pytest.mark.django_db
def test_second_visit_reuses_the_account(client, private_key):
    get(client, token(private_key))
    get(client, token(private_key))
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_email_is_matched_to_an_existing_account(client, private_key):
    anna = User.objects.create_user(username="anna")
    call_command("link_account_email", "Anna", "Scimone.Mail@gmail.com")
    response = get(client, token(private_key, "scimone.mail@gmail.com"))
    assert response.wsgi_request.user == anna
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_a_lookalike_email_cannot_become_an_admin_username(client, private_key):
    response = get(client, token(private_key, "anna@evil.example"))
    assert response.wsgi_request.user.get_username() == "anna@evil.example"


@pytest.mark.django_db
def test_switching_identity_signs_in_the_new_account(client, private_key):
    get(client, token(private_key, "a@example.com"))
    response = get(client, token(private_key, "b@example.com"))
    assert response.wsgi_request.user.email == "b@example.com"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad",
    [
        lambda k: None,  # no header at all
        lambda k: "garbage",
        lambda k: token(k, aud="another-app"),
        lambda k: token(k, iss="https://evil.cloudflareaccess.com"),
        lambda k: token(k, exp=-10),
        lambda k: token(k, email=None),  # service token: no e-mail
        lambda k: token(rsa.generate_private_key(public_exponent=65537, key_size=2048)),
    ],
)
def test_invalid_token_is_refused(client, private_key, bad):
    assert get(client, bad(private_key)).status_code == 403
    assert not User.objects.exists()


@pytest.mark.django_db
def test_the_plain_email_header_alone_is_not_trusted(client):
    response = client.get("/account/", HTTP_CF_ACCESS_AUTHENTICATED_USER_EMAIL="x@example.com")
    assert response.status_code == 403


@pytest.mark.django_db
def test_off_when_not_configured(client, settings):
    settings.CF_ACCESS_AUD = ""
    assert get(client).status_code == 200


@pytest.mark.django_db
def test_account_page_signs_out_through_access(client, private_key):
    User.objects.create_user(
        username="gino@example.com", email="gino@example.com", first_name="Gino"
    )
    response = get(client, token(private_key))
    assert f"{ISSUER}/cdn-cgi/access/logout".encode() in response.content


@pytest.mark.django_db
def test_link_refuses_an_address_used_by_another_account():
    User.objects.create_user(username="b", email="x@example.com")
    User.objects.create_user(username="a")
    with pytest.raises(CommandError):
        call_command("link_account_email", "a", "x@example.com")
