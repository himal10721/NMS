import os

from django.core.management.base import BaseCommand, CommandError

from monitoring.models import Device
from monitoring.services import poll_memory_usage, poll_system_uptime


class Command(BaseCommand):
    """Collect and store SNMP uptime and processor-memory values."""

    help = "Poll one device's SNMP uptime and memory usage and store the metrics."

    def add_arguments(self, parser):
        parser.add_argument(
            "--device",
            required=True,
            help="Name of the enabled device to poll.",
        )
        parser.add_argument(
            "--community",
            help="SNMPv2c community; defaults to SNMP_COMMUNITY.",
        )

    def handle(self, *args, **options):
        community = options["community"] or os.environ.get("SNMP_COMMUNITY")
        if not community:
            raise CommandError(
                "Provide --community or set the SNMP_COMMUNITY environment variable."
            )

        try:
            device = Device.objects.get(name=options["device"], is_enabled=True)
        except Device.DoesNotExist as exc:
            raise CommandError("No enabled device matched that name.") from exc

        uptime_record = poll_system_uptime(device, community)
        if not uptime_record.collection_successful:
            raise CommandError(
                f"{device.name}: SNMP uptime failed ({uptime_record.text_value})"
            )

        memory_records = poll_memory_usage(device, community)
        memory_percent = memory_records["memory_usage_percent"]
        if not memory_percent.collection_successful:
            raise CommandError(
                f"{device.name}: SNMP memory collection failed "
                f"({memory_percent.text_value})"
            )

        uptime_minutes = uptime_record.numeric_value
        uptime_hours = uptime_minutes / 60
        self.stdout.write(
            self.style.SUCCESS(
                f"{device.name}: uptime = {uptime_minutes:.2f} minutes "
                f"({uptime_hours:.2f} hours); "
                f"RAM used = {memory_records['memory_used_mb'].numeric_value:.2f} MB; "
                f"RAM free = {memory_records['memory_free_mb'].numeric_value:.2f} MB; "
                f"RAM usage = {memory_percent.numeric_value:.2f}%"
            )
        )
