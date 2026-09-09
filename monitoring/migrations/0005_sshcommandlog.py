from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("monitoring", "0004_convert_uptime_to_minutes"),
    ]

    operations = [
        migrations.CreateModel(
            name="SSHCommandLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("command_key", models.CharField(max_length=50)),
                ("command", models.CharField(max_length=200)),
                ("successful", models.BooleanField(default=False)),
                ("output", models.TextField(blank=True)),
                ("error", models.TextField(blank=True)),
                ("executed_at", models.DateTimeField(auto_now_add=True)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ssh_command_logs", to="monitoring.device")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ssh_command_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-executed_at"],
                "permissions": [("execute_ssh_command", "Can execute approved SSH commands")],
            },
        ),
    ]
