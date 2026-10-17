import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0002_default_campaign"),
        ("frontend", "0010_logentry_campaign"),
    ]

    operations = [
        migrations.AlterField(
            model_name="logentry",
            name="campaign",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="log_entries",
                to="campaigns.campaign",
            ),
        ),
    ]
