"""Language lookups (list_languages)."""

from apps.rules.models import Language


def list_languages():
    return Language.objects.all()
