"""Continuously collect general internet-performance measurements."""

import time

from django.core.management.base import BaseCommand, CommandError

from monitoring.models import Device
from monitoring.services import collect_network_performance


class Command(BaseCommand):
    """Run the internet-performance collector at a bandwidth-safe interval."""

    help = "Continuously collect and store general internet-performance metrics."

    def add_arguments(self, parser):
        parser.add_argument(
            "--device",
            default="Monitoring PC",
            help="Monitoring host device name (default: Monitoring PC).",
        )
        parser.add_argument(
            "--target",
            default="8.8.8.8",
            help="Host used for ICMP measurements (default: 8.8.8.8).",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=3600,
            help="Seconds between full speed tests (default: 3600).",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Collect one sample and stop; useful for testing.",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        if interval < 300 and not options["once"]:
            raise CommandError(
                "--interval must be at least 300 seconds because speed tests "
                "consume bandwidth."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Performance monitor started; full collection every "
                f"{interval:g} seconds. Press Ctrl+C to stop."
            )
        )

        try:
            while True:
                try:
                    device = Device.objects.get(
                        name=options["device"],
                        is_enabled=True,
                    )
                except Device.DoesNotExist as exc:
                    raise CommandError(
                        f"No enabled device named {options['device']!r} was found."
                    ) from exc

                records = collect_network_performance(
                    device=device,
                    target=options["target"],
                    include_speedtest=True,
                )
                download = records["internet_download_mbps"]
                upload = records["internet_upload_mbps"]
                if download.collection_successful and upload.collection_successful:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Internet: {download.numeric_value:.2f} Mbps down; "
                            f"{upload.numeric_value:.2f} Mbps up."
                        )
                    )
                else:
                    reason = download.text_value or upload.text_value or "collection failed"
                    self.stderr.write(self.style.ERROR(f"Internet: {reason}"))

                if options["once"]:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Performance monitor stopped."))
