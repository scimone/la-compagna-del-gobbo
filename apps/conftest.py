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


@pytest.fixture(autouse=True)
def _plain_http_client(settings):
    """Production redirects http to https; the test client speaks plain http."""
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture(scope="module")
def imported_rules(django_db_setup, django_db_blocker):
    """The full `import_rules_data` result, loaded once per test module and committed (not rolled
    back per test), for tests that check the real catalogs rather than hand-made fixtures.

    Torn down by wiping the rules tables again, so a module that uses it can't leak rows into one
    that creates its own `Class(id="wizard")` and the like. Tests that use it must not write to the
    rules tables themselves; per-test `Character` rows are fine (the `db` fixture rolls them back).
    """
    from django.core.management import call_command

    from apps.rules.management.commands.import_rules_data import Command

    with django_db_blocker.unblock():
        call_command("import_rules_data", verbosity=0)
    yield
    with django_db_blocker.unblock():
        Command()._delete_existing()
