from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("characters", "0011_character_picture"),
    ]

    operations = [
        migrations.AddField(
            model_name="character",
            name="portrait_cx",
            field=models.FloatField(default=0.5),
        ),
        migrations.AddField(
            model_name="character",
            name="portrait_cy",
            field=models.FloatField(default=0.5),
        ),
        migrations.AddField(
            model_name="character",
            name="portrait_zoom",
            field=models.FloatField(default=1.0),
        ),
    ]
