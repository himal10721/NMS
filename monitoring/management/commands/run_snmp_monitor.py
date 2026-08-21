import os
import time

from django.core.management.base import BaseCommand, CommandError

from monitoring.models import Device
from monitoring.services import poll_memory_usage, poll_system_uptime


class Command(BaseCommand):
    """Continuously collect SNMP uptime and memory metrics for one device."""

    help = "Continuously poll one enabled device through SNMP and store its metrics."

    def add_arguments(self, parser):
        parser.add_argument("--device", required=True, help="Device name, for example R1.")
        parser.add_argument(
            "--interval",
            type=float,
            default=60,
            help="Seconds between collections (default: 60).",
        )
        parser.add_argument(
            "--community",
            help="SNMPv2c community; defaults to SNMP_COMMUNITY.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Collect one sample and stop; useful for testing.",
        )

    def handle(self, *args, **options):
        community = options["community"] or os.environ.get("SNMP_COMMUNITY")
        if not community:
            raise CommandError(
                "Provide --community or set the SNMP_COMMUNITY environment variable."
            )

        interval = options["interval"]
        if interval < 5:
            raise CommandError("--interval must be at least 5 seconds.")

        device_name = options["device"]
        self.stdout.write(
            self.style.SUCCESS(
                f"SNMP monitor started for {device_name} every {interval:g} seconds. "
                "Press Ctrl+C to stop."
            )
        )

        try:
            while True:
                # Reload the device so changes made in Django Admin take effect.
                try:
                    device = Device.objects.get(name=device_name, is_enabled=True)
                except Device.DoesNotExist as exc:
                    raise CommandError(
                        f"No enabled device named {device_name!r} was found."
                    ) from exc

                uptime = poll_system_uptime(device, community)
                memory = poll_memory_usage(device, community)
                memory_percent = memory["memory_usage_percent"]

                if uptime.collection_successful and memory_percent.collection_successful:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"{device.name}: uptime {uptime.numeric_value:.2f} min; "
                            f"RAM {memory_percent.numeric_value:.2f}% "
                            f"({memory['memory_used_mb'].numeric_value:.2f} MB used)"
                        )
                    )
                else:
                    errors = [
                        record.text_value
                        for record in (uptime, memory_percent)
                        if not record.collection_successful and record.text_value
                    ]
                    self.stderr.write(
                        self.style.ERROR(
                            f"{device.name}: collection failed: " + "; ".join(errors)
                        )
                    )

                if options["once"]:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("SNMP monitor stopped."))
