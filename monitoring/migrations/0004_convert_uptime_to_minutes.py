from django.db import migrations


def convert_uptime_to_minutes(apps, schema_editor):
    """Convert existing system-uptime values from seconds to minutes."""

    MetricDefinition = apps.get_model("monitoring", "MetricDefinition")
    MetricRecord = apps.get_model("monitoring", "MetricRecord")

    try:
        definition = MetricDefinition.objects.get(key="system_uptime")
    except MetricDefinition.DoesNotExist:
        return

    if definition.unit == "seconds":
        for record in MetricRecord.objects.filter(
            metric_definition=definition,
            numeric_value__isnull=False,
        ):
            record.numeric_value = round(record.numeric_value / 60, 2)
            record.save(update_fields=["numeric_value"])

        definition.unit = "minutes"
        definition.save(update_fields=["unit"])


def convert_uptime_to_seconds(apps, schema_editor):
    """Reverse the conversion if this migration is rolled back."""

    MetricDefinition = apps.get_model("monitoring", "MetricDefinition")
    MetricRecord = apps.get_model("monitoring", "MetricRecord")

    try:
        definition = MetricDefinition.objects.get(key="system_uptime")
    except MetricDefinition.DoesNotExist:
        return

    if definition.unit == "minutes":
        for record in MetricRecord.objects.filter(
            metric_definition=definition,
            numeric_value__isnull=False,
        ):
            record.numeric_value = round(record.numeric_value * 60, 2)
            record.save(update_fields=["numeric_value"])

        definition.unit = "seconds"
        definition.save(update_fields=["unit"])


class Migration(migrations.Migration):
    dependencies = [
        (
            "monitoring",
            "0003_metricdefinition_alert_category_alert_severity_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            convert_uptime_to_minutes,
            convert_uptime_to_seconds,
        ),
    ]
