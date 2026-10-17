import pytest
from django.db.models.signals import post_save, pre_save
from django.utils import translation

DEFAULT_CAMPAIGN_NAME = "Test campaign"


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


@pytest.fixture(autouse=True)
def _cloudflare_access_off(settings):
    """The deployment's `.env` turns Cloudflare Access on; the tests speak to the app directly.
    `test_cloudflare_access.py` switches it back on for itself."""
    settings.CF_ACCESS_TEAM_DOMAIN = ""
    settings.CF_ACCESS_AUD = ""


def default_campaign():
    """The campaign every test user and character is in unless a test says otherwise."""
    from apps.campaigns.models import Campaign

    return Campaign.objects.get_or_create(name=DEFAULT_CAMPAIGN_NAME)[0]


@pytest.fixture(autouse=True)
def _everyone_in_the_default_campaign(request):
    """Characters and Logbook entries need a campaign and their viewers need a membership; most
    tests are not about campaigns, so by default every new account joins one shared campaign (as a
    player) and every new character / entry lands in it. A test about campaigns builds its own and
    opts out with `@pytest.mark.no_default_campaign`."""
    if request.node.get_closest_marker("no_default_campaign"):
        yield
        return

    from django.contrib.auth import get_user_model

    from apps.campaigns.models import CampaignMembership
    from apps.characters.models import Character
    from apps.frontend.models import LogEntry

    def place(sender, instance, **kwargs):
        if instance.campaign_id is None:
            instance.campaign = default_campaign()

    def join(sender, instance, created, **kwargs):
        if created:
            CampaignMembership.objects.get_or_create(
                campaign=default_campaign(), user=instance, defaults={"role": "player"}
            )

    user_model = get_user_model()
    pre_save.connect(place, sender=Character, dispatch_uid="test-place-character")
    pre_save.connect(place, sender=LogEntry, dispatch_uid="test-place-entry")
    post_save.connect(join, sender=user_model, dispatch_uid="test-join-default")
    yield
    pre_save.disconnect(sender=Character, dispatch_uid="test-place-character")
    pre_save.disconnect(sender=LogEntry, dispatch_uid="test-place-entry")
    post_save.disconnect(sender=user_model, dispatch_uid="test-join-default")


def make_dm(user, campaign=None):
    """Make `user` the DM of `campaign` (the shared test campaign by default); whoever was the DM
    becomes a player."""
    from apps.campaigns.models import CampaignMembership
    from apps.campaigns.services import lifecycle

    campaign = campaign or default_campaign()
    CampaignMembership.objects.get_or_create(
        campaign=campaign, user=user, defaults={"role": "player"}
    )
    lifecycle.transfer_dm(campaign, user)
