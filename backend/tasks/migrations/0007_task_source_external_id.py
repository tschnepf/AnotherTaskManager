from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0006_taskchangeevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="source_external_id",
            field=models.CharField(blank=True, db_index=True, max_length=512),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.UniqueConstraint(
                condition=Q(source_type="email") & ~Q(source_external_id=""),
                fields=("organization", "source_type", "source_external_id"),
                name="task_email_source_external_id_uniq",
            ),
        ),
    ]
