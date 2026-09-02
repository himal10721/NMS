"""Collect one internet-performance sample and store it through Django ORM."""

from django.core.management.base import BaseCommand, CommandError

from monitoring.models import Device
from monitoring.services import collect_network_performance


class Command(BaseCommand):
    """Measure latency, packet loss, download speed, and upload speed once."""

    help = "Collect and store one network-performance sample."

    def add_arguments(self, parser):
        parser.add_argument(
            "--device",
            default="Monitoring PC",
            help="Device that represents the monitoring host (default: Monitoring PC).",
        )
        parser.add_argument(
            "--target",
            default="8.8.8.8",
            help="Internet host used for the ICMP test (default: 8.8.8.8).",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=4,
            help="Number of ping packets (default: 4).",
        )
        parser.add_argument(
            "--ping-only",
            action="store_true",
            help="Store latency and packet loss without a bandwidth test.",
        )

    def handle(self, *args, **options):
        if options["count"] < 1:
            raise CommandError("--count must be at least 1.")

        try:
            device = Device.objects.get(name=options["device"], is_enabled=True)
        except Device.DoesNotExist as exc:
            raise CommandError(
                f"No enabled device named {options['device']!r} was found."
            ) from exc

        self.stdout.write(
            f"Collecting network performance for {device.name}; please wait..."
        )
        records = collect_network_performance(
            device=device,
            target=options["target"],
            count=options["count"],
            include_speedtest=not options["ping_only"],
        )

        for record in records.values():
            label = record.metric_definition.display_name
            unit = record.metric_definition.unit
            if record.collection_successful:
                self.stdout.write(
                    self.style.SUCCESS(f"{label}: {record.numeric_value:.2f} {unit}")
                )
            else:
                reason = record.text_value or "not collected"
                self.stdout.write(self.style.WARNING(f"{label}: {reason}"))
