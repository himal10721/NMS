import time

from django.core.management.base import BaseCommand

from monitoring.models import Device
from monitoring.services import poll_device


class Command(BaseCommand):
    """Long-running lightweight scheduler for device availability polling."""

    help = "Continuously poll enabled devices using their configured intervals."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tick",
            type=float,
            default=1.0,
            help="Seconds between scheduler checks (default: 1).",
        )
        parser.add_argument(
            "--iterations",
            type=int,
            default=0,
            help="Stop after this many scheduler iterations; 0 runs indefinitely.",
        )

    def handle(self, *args, **options):
        tick = options["tick"]
        max_iterations = options["iterations"]
        if tick < 0.1:
            self.stderr.write(self.style.ERROR("--tick must be at least 0.1 seconds."))
            return
        if max_iterations < 0:
            self.stderr.write(self.style.ERROR("--iterations cannot be negative."))
            return

        # Store each device's next due time in memory. monotonic timestamps avoid
        # missed or duplicated polls when the Windows wall clock changes.
        next_poll_at: dict[int, float] = {}
        iteration = 0
        self.stdout.write(
            self.style.SUCCESS(
                "Monitoring worker started. Press Ctrl+C to stop it safely."
            )
        )

        try:
            while True:
                now = time.monotonic()
                # Reload enabled devices on every tick so admin changes take effect
                # without restarting the worker.
                devices = list(Device.objects.filter(is_enabled=True))
                enabled_ids = {device.pk for device in devices}
                # Remove schedule entries for devices disabled or deleted in admin.
                next_poll_at = {
                    device_id: due_at
                    for device_id, due_at in next_poll_at.items()
                    if device_id in enabled_ids
                }

                for device in devices:
                    # A missing schedule entry makes newly added devices poll now.
                    if now < next_poll_at.get(device.pk, 0):
                        continue

                    check = poll_device(device)
                    state = "UP" if check.is_reachable else "DOWN"
                    response = (
                        f"{check.response_time_ms:.2f} ms"
                        if check.response_time_ms is not None
                        else "no response"
                    )
                    style = self.style.SUCCESS if check.is_reachable else self.style.ERROR
                    self.stdout.write(style(f"{device.name}: {state} ({response})"))
                    next_poll_at[device.pk] = (
                        time.monotonic() + device.polling_interval_seconds
                    )

                iteration += 1
                if max_iterations and iteration >= max_iterations:
                    break
                time.sleep(tick)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Monitoring worker stopped."))
