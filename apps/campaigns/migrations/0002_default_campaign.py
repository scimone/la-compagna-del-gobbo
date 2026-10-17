"""The app used to have one shared table of characters and one Logbook: put them all into the
campaign "Obelisco infranto", whose DM is Riccardo, with every existing account as a player.

Nothing is created on a database with no accounts, characters or entries (a fresh install, the
tests)."""

from django.db import migrations

CAMPAIGN_NAME = "Obelisco infranto"
DM_EMAIL = "rikyfr95@gmail.com"


def forwards(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Campaign = apps.get_model("campaigns", "Campaign")
    Membership = apps.get_model("campaigns", "CampaignMembership")
    Character = apps.get_model("characters", "Character")
    LogEntry = apps.get_model("frontend", "LogEntry")

    if not (User.objects.exists() or Character.objects.exists() or LogEntry.objects.exists()):
        return
    dm = User.objects.filter(username__iexact=DM_EMAIL).first() or User.objects.filter(
        email__iexact=DM_EMAIL
    ).first()
    if dm is None:  # Cloudflare Access links the account to this e-mail on the first visit
        dm = User.objects.create(username=DM_EMAIL, email=DM_EMAIL, password="!")
    campaign = Campaign.objects.create(name=CAMPAIGN_NAME, created_by=dm)
    for user in User.objects.order_by("date_joined", "pk"):
        Membership.objects.create(
            campaign=campaign, user=user, role="dm" if user.pk == dm.pk else "player"
        )
    Character.objects.filter(campaign__isnull=True).update(campaign=campaign)
    LogEntry.objects.filter(campaign__isnull=True).update(campaign=campaign)


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("characters", "0023_character_campaign"),
        ("frontend", "0010_logentry_campaign"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
