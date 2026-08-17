from django.core.management.base import BaseCommand

# imports the device model so the command can load enabled network devices
from monitoring.models import Device
# imports the poll helper that checks device reachability
from monitoring.services import poll_device


class Command(BaseCommand):
    """One-shot poller used for testing and targeted troubleshooting."""

    help = "Poll all enabled devices once and store availability results."

    def add_arguments(self, parser):
        # add an optional --device argument so we can poll one named device
        parser.add_argument(
            "--device",
            help="Poll only the device with this name.",
        )

    def handle(self, *args, **options):
        # load only devices that are enabled in the admin
        devices = Device.objects.filter(is_enabled=True)
        # if a device name is passed, narrow the query to that device
        if options["device"]:
            devices = devices.filter(name=options["device"])

        # if no enabled device matches, show a warning and stop
        if not devices.exists():
            self.stdout.write(self.style.WARNING("No enabled devices matched."))
            return

        for device in devices:
            # perform the actual reachability check for this device
            check = poll_device(device)
            # set a simple UP/DOWN status based on the check result
            state = "UP" if check.is_reachable else "DOWN"
            # format response time if available, otherwise show no response
            response = (
                f"{check.response_time_ms:.2f} ms"
                if check.response_time_ms is not None
                else "no response"
            )
            # choose output style based on whether the device is reachable
            style = self.style.SUCCESS if check.is_reachable else self.style.ERROR
            # print the final status line for this device
            self.stdout.write(style(f"{device.name}: {state} ({response})"))
