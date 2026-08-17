#used to import time
import time
# importing django's base class for custom management commands
from django.core.management.base import BaseCommand
# imports the device model so the command can query from the databse
from monitoring.models import Device
# imports the function that perfoms a monitoring check of one device
from monitoring.services import poll_device


class Command(BaseCommand):
    """Long-running lightweight scheduler for device availability polling."""

    help = "Continuously poll enabled devices using their configured intervals."

    # text shown by django help output for this command
    # starts the method that adds the command-line arguments
    # add arguments is a special method django call when building the commands CLI interface
    # parser is a django arugementparser object, similar to pythons argparse.argumentparser
    # the first argument "--tick" defines an optional flag.
    # accepts a value that is converted to float, if the user doesnot provide "--tick", the value defaults to 1.0

    def add_arguments(self, parser):
        parser.add_argument(
            "--tick",
            type=float,
            default=1.0,
            help="Seconds between scheduler checks (default: 1).",
        )
        # the second argument is --iterations which accepts a value converted to an integer and defaults a value of 0
        # iterations limit how many scheduler cycles the comand performs
        # each loop through the device-check logic couts as one iteration
        # hence, 0 means there is no limit and the command can run forever until interupted.

        parser.add_argument(
            "--iterations",
            type=int,
            default=0,
            help="Stop after this many scheduler iterations; 0 runs indefinitely.",
        )


    def handle(self, *args, **options):
        tick = options["tick"] # reads the parsed command options passed from add_arguments and "tick" is how many seconds
        
        max_iterations = options["iterations"] # how many loops iterations to run before stopping
        if tick < 0.1:
            self.stderr.write(self.style.ERROR("--tick must be at least 0.1 seconds."))
            return
        if max_iterations < 0: # if the tick value is too small, prints an error and stops
            self.stderr.write(self.style.ERROR("--iterations cannot be negative."))
            return

        # Store each device's next due time in memory. monotonic timestamps avoid
        # missed or duplicated polls when the Windows wall clock changes.
        next_poll_at: dict[int, float] = {} 
        iteration = 0
        self.stdout.write( #prints a startup message in green
            self.style.SUCCESS(
                "Monitoring worker started. Press Ctrl+C to stop it safely."
            )
        )

        try:    # begins an infinite loop
            while True:
                now = time.monotonic() # used so scheduling is not broken by system clock changes
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

                for device in devices: #iterates over each enabled devices
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
