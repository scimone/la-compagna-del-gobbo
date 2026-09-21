import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-key-change-me")

DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# Comma-separated list of scheme+host origins allowed to POST here (e.g. the language
# switcher). Django's CSRF check compares the request's Origin header against this list -
# ALLOWED_HOSTS alone doesn't cover it. Needed for any origin that isn't plain http(s)://
# <a host already covered by autodetection>, which in practice means anything served through
# a reverse proxy under its own domain (e.g. https://dnd.scimone.uk via nginx-proxy-manager).
CSRF_TRUSTED_ORIGINS = [
    origin for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin
]

# This app sits behind a reverse proxy (nginx-proxy-manager / Cloudflare tunnel) that terminates
# TLS and forwards plain HTTP to uvicorn - without this, Django thinks every request is
# insecure (wrong scheme in generated URLs, secure-cookie logic never triggers, and the CSRF
# check has less context to work with). The header name must match what the proxy actually
# sets; X-Forwarded-Proto is the standard one and is what nginx-proxy-manager sends.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    # Must come before `django.contrib.admin` so the admin picks up its translated-field support.
    "modeltranslation",
    "django.contrib.admin",
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
    "apps.frontend.middleware.TrackLastSectionUrlMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
PWA_APP_START_URL = "/"
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
