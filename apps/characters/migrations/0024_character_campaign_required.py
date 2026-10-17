import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0002_default_campaign"),
        ("characters", "0023_character_campaign"),
    ]

    operations = [
        migrations.AlterField(
            model_name="character",
            name="campaign",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="characters",
                to="campaigns.campaign",
            ),
        ),
    ]
