import os
from pathlib import Path

from django.utils.csp import CSP
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# Secure by default: every value below is the production one unless the environment says
# otherwise. DEBUG is opt-in (`DJANGO_DEBUG=true` in a local .env), never the fallback.
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"

# No fallback key outside DEBUG: a missing DJANGO_SECRET_KEY must stop the app, not quietly sign
# sessions with a key that is public in the repository.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "dev-only-insecure-key-never-use-in-production" if DEBUG else None
)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is not true")

ALLOWED_HOSTS = [
    host
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "dnd.scimone.uk").split(",")
    if host.strip()
]

# Comma-separated list of scheme+host origins allowed to POST here (e.g. the language
# switcher). Django's CSRF check compares the request's Origin header against this list -
# ALLOWED_HOSTS alone doesn't cover it, and behind a TLS-terminating proxy the scheme it sees
# is the proxy's, so the public https:// origin has to be listed explicitly.
CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "https://dnd.scimone.uk").split(",")
    if origin.strip()
]

# This app sits behind a reverse proxy (nginx-proxy-manager / Cloudflare tunnel) that terminates
# TLS and forwards plain HTTP to uvicorn - without this, Django thinks every request is
# insecure (wrong scheme in generated URLs, secure-cookie logic never triggers, and the CSRF
# check has less context to work with). The header name must match what the proxy actually
# sets; X-Forwarded-Proto is the standard one and is what nginx-proxy-manager sends. Only safe
# while the proxy is the sole way to reach port 3000 (a direct client could forge the header).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Transport and cookie hardening -------------------------------------------------------
# Everything that only makes sense over HTTPS is tied to `not DEBUG`, so a local `DEBUG=true` run
# over plain http keeps working while the default (production) configuration is fully locked down.
_HTTPS_ONLY = not DEBUG

SECURE_SSL_REDIRECT = _HTTPS_ONLY
# One year, subdomains included, preload directive emitted. The `preload` flag is inert until the
# domain is submitted to hstspreload.org - which is hard to undo, so that is a separate decision.
SECURE_HSTS_SECONDS = 31536000 if _HTTPS_ONLY else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = _HTTPS_ONLY
SECURE_HSTS_PRELOAD = _HTTPS_ONLY

# `__Host-` cookies are only accepted by browsers when Secure, Path=/ and with no Domain
# attribute, so a sibling subdomain can't overwrite or shadow them.
SESSION_COOKIE_NAME = "__Host-sessionid" if _HTTPS_ONLY else "sessionid"
SESSION_COOKIE_SECURE = _HTTPS_ONLY
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "__Host-csrftoken" if _HTTPS_ONLY else "csrftoken"
CSRF_COOKIE_SECURE = _HTTPS_ONLY
# Safe: the sheet's JS reads the token from the form's hidden input, never from the cookie.
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
LANGUAGE_COOKIE_SECURE = _HTTPS_ONLY
LANGUAGE_COOKIE_HTTPONLY = True
LANGUAGE_COOKIE_SAMESITE = "Lax"

# --- Response headers ---------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Content-Security-Policy (Django's own middleware, below). Nothing is loaded from another
# origin, so everything is 'self'. 'unsafe-inline' remains for script and style only because the
# templates still carry inline <script> blocks, `on*=` handlers and `style=` attributes; moving
# those into static files would let script-src drop it. Framing, <base>, <object> and form
# targets are locked outright.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:", "blob:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "manifest-src": [CSP.SELF],
    "worker-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}

# --- Request size limits ------------------------------------------------------------------
# Non-file request bodies (forms) never legitimately approach this; portraits are files and are
# capped separately in `apps/characters/services/portrait.py`.
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# With DEBUG off Django's default only e-mails tracebacks to ADMINS (none are configured), so
# unhandled errors would vanish. Send them to stderr, where `docker logs` picks them up.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

INSTALLED_APPS = [
    "modeltranslation",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "pwa",
    "apps.rules",
    "apps.characters",
    "apps.builder",
    "apps.frontend",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves STATIC_ROOT directly from the ASGI app - there's no separate web server (nginx,
    # etc.) sharing a volume with this container, and uvicorn doesn't serve static files on its
    # own the way `runserver` does under DEBUG=True. Placed right after SecurityMiddleware per
    # WhiteNoise's own setup docs.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "apps.frontend.cloudflare_access.CloudflareAccessMiddleware",
    "apps.frontend.middleware.TrackLastSectionUrlMiddleware",
    "apps.frontend.middleware.InteractionMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.frontend.context_processors.last_section_urls",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ["POSTGRES_PORT"],
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", "English"),
    ("it", "Italiano"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

# Game-content translation (`rules` tables) - see `apps/rules/translation.py`. Translated columns
# (`name_en`/`name_it`, ...) sit next to the original field, which then reads back in whichever
# language `LocaleMiddleware` activated for the request, falling back to English when a
# translation is missing so a partly translated catalog never shows blanks.
MODELTRANSLATION_DEFAULT_LANGUAGE = "en"
MODELTRANSLATION_FALLBACK_LANGUAGES = ("en",)
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Files the players upload (character portraits). Kept outside the image: docker-compose mounts a
# host folder here, so a redeploy does not lose them. Served by a view, never by URL - see
# `character_portrait` - so it has no MEDIA_URL.
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Plain compression, not the hashed/manifest variant - PWA_APP_ICONS below and django-pwa's
    # own manifest.json template reference `/static/...` paths directly rather than going
    # through the `{% static %}` tag, so nothing would know to look up a hashed filename.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# django-pwa: manifest.json / serviceworker.js generation
PWA_SERVICE_WORKER_PATH = str(BASE_DIR / "static" / "js" / "serviceworker.js")
PWA_APP_NAME = "La Compagna del Gobbo"
PWA_APP_DESCRIPTION = "D&D 5.5e (2024) player backend"
PWA_APP_THEME_COLOR = "#7a1f1f"
PWA_APP_BACKGROUND_COLOR = "#f7f5f2"
PWA_APP_DISPLAY = "standalone"
PWA_APP_SCOPE = "/"
PWA_APP_ORIENTATION = "any"
PWA_APP_START_URL = "/characters/"
PWA_APP_STATUS_BAR_COLOR = "default"
PWA_APP_ICONS = [
    {"src": "/static/images/icons/icon-192x192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/static/images/icons/icon-512x512.png", "sizes": "512x512", "type": "image/png"},
]
PWA_APP_ICONS_APPLE = [
    {"src": "/static/images/icons/icon-180x180.png", "sizes": "180x180", "type": "image/png"},
]
PWA_APP_SPLASH_SCREEN = []
PWA_APP_DIR = "ltr"
PWA_APP_LANG = "en-US"

# Accounts (usernames, lower case) that may see and change every character, other accounts' too -
# see `apps.characters.services.access.is_admin`.
ADMIN_ACCOUNTS = ["anna"]

# Cloudflare Access sits in front of the app (via the tunnel) and signs every request it lets
# through with a JWT; `CloudflareAccessMiddleware` verifies it and signs the visitor in as the
# `auth.User` with that Google e-mail (creating it on the first visit). Both values come from
# the Access application (team name: `<team>.cloudflareaccess.com`; AUD tag: its Overview tab).
# Leave either empty - a local run, the tests - and the middleware is off, with the password-less
# sign-in of `apps/frontend/accounts.py` still working.
CF_ACCESS_TEAM_DOMAIN = os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip()
CF_ACCESS_AUD = os.environ.get("CF_ACCESS_AUD", "").strip()
