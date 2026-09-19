import pytest
from django.utils import translation


@pytest.fixture(autouse=True)
def _english_by_default():
    """`LocaleMiddleware` leaves the language it activated for a request (e.g. Italian, from a
    test's `django_language` cookie) active on the thread. On a translated model `name=` means
    "the active language's column", so without this a later test's fixtures would write into
    `name_it` and the next English request would read NULL.
    """
    translation.activate("en")
    yield
    translation.activate("en")
