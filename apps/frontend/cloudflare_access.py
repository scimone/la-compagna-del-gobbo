"""Sign-in through Cloudflare Access.

Access authenticates the visitor (Google) before a request reaches the tunnel and forwards it with
a signed JWT in `Cf-Access-Jwt-Assertion`. `CloudflareAccessMiddleware` verifies that JWT against
the team's public keys (signature, audience, issuer, expiry) and signs the visitor in as the
`auth.User` owning that e-mail - creating the account on the first visit. The plain
`Cf-Access-Authenticated-User-Email` header is deliberately ignored: only the signed token is
trusted, so a request that reaches the app some other way can't claim an identity.

Enabled only when both `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` are set; then a request
without a valid token is refused outright (403).
"""

import logging
from functools import lru_cache
from urllib.parse import quote

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.db import IntegrityError
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse

log = logging.getLogger(__name__)

JWT_HEADER = "Cf-Access-Jwt-Assertion"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def is_enabled() -> bool:
    return bool(settings.CF_ACCESS_TEAM_DOMAIN and settings.CF_ACCESS_AUD)


def _issuer() -> str:
    domain = settings.CF_ACCESS_TEAM_DOMAIN
    if "." not in domain:
        domain += ".cloudflareaccess.com"
    return f"https://{domain}"


def logout_url() -> str:
    """Ends the Access session itself (Django's own logout would be undone on the next request)."""
    return f"{_issuer()}/cdn-cgi/access/logout"


@lru_cache(maxsize=4)
def _jwks_client(certs_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(certs_url)  # caches the key set itself


def verified_email(token: str) -> str | None:
    """The lower-cased e-mail in a valid Access JWT, or `None` (bad/expired/foreign token, or one
    with no e-mail such as a service token)."""
    if not token:
        return None
    try:
        key = _jwks_client(f"{_issuer()}/cdn-cgi/access/certs").get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=settings.CF_ACCESS_AUD,
            issuer=_issuer(),
        )
    except jwt.PyJWTError:
        log.warning("rejected an invalid Cloudflare Access token", exc_info=True)
        return None
    email = claims.get("email")
    return email.strip().lower() if isinstance(email, str) and email.strip() else None


def get_or_create_user_by_email(email: str):
    """The account whose `email` is `email` (case-insensitive), created if there is none.

    A new account's username is the full e-mail, never a friendlier local part: usernames are what
    `ADMIN_ACCOUNTS` matches on, so "anna@somewhere.else" must not be able to become "anna". An
    existing account is linked to an address with the `link_account_email` command.
    """
    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        try:
            user = User.objects.create_user(username=email, email=email)  # unusable password
        except IntegrityError:  # a concurrent first request created it
            user = User.objects.get(username__iexact=email)
    return user


class RequireNameMiddleware:
    """Right after the first Google sign-in the account has no name: send every page load to the
    welcome page until one is given. Only under Cloudflare Access (the password-less sign-in
    already asks for a name)."""

    _EXEMPT_PREFIXES = ("/welcome/", "/static/", "/media/", "/i18n/", "/account/logout/")
    _EXEMPT_PATHS = ("/manifest.json", "/serviceworker.js", "/favicon.ico")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            is_enabled()
            and request.method == "GET"
            and user.is_authenticated
            and not (user.first_name or "").strip()
            and not request.path.startswith(self._EXEMPT_PREFIXES)
            and request.path not in self._EXEMPT_PATHS
        ):
            return redirect(f"{reverse('welcome')}?next={quote(request.get_full_path())}")
        return self.get_response(request)


class CloudflareAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not is_enabled():
            return self.get_response(request)
        email = verified_email(request.headers.get(JWT_HEADER, ""))
        if email is None:
            return HttpResponseForbidden("Cloudflare Access authentication required.")
        user = request.user
        if not (user.is_authenticated and (user.email or "").lower() == email):
            login(request, get_or_create_user_by_email(email), backend=_BACKEND)
        return self.get_response(request)
