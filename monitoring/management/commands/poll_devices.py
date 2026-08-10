from django.core.management.base import BaseCommand

from monitoring.models import Device
from monitoring.services import poll_device


class Command(BaseCommand):
    """One-shot poller used for testing and targeted troubleshooting."""

    help = "Poll all enabled devices once and store availability results."

    def add_arguments(self, parser):
        parser.add_argument(
            "--device",
            help="Poll only the device with this name.",
        )

    def handle(self, *args, **options):
        # The optional name filter makes it possible to test one device without
        # changing the enabled state of the rest of the inventory.
        devices = Device.objects.filter(is_enabled=True)
        if options["device"]:
            devices = devices.filter(name=options["device"])

        if not devices.exists():
            self.stdout.write(self.style.WARNING("No enabled devices matched."))
            return

        for device in devices:
            check = poll_device(device)
            state = "UP" if check.is_reachable else "DOWN"
            response = (
                f"{check.response_time_ms:.2f} ms"
                if check.response_time_ms is not None
                else "no response"
            )
            style = self.style.SUCCESS if check.is_reachable else self.style.ERROR
            self.stdout.write(style(f"{device.name}: {state} ({response})"))
