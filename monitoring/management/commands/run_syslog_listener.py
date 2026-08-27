import socket

from django.core.management.base import BaseCommand, CommandError

from monitoring.services import record_syslog_event


class Command(BaseCommand):
    """Receive UDP syslog messages and store them as Django NetworkEvents."""

    help = "Continuously receive UDP syslog messages and store them in the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            default="0.0.0.0",
            help="Local IPv4 address on which to listen (default: 0.0.0.0).",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=514,
            help="UDP port on which to listen (default: 514).",
        )

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]
        if not 1 <= port <= 65535:
            raise CommandError("--port must be between 1 and 65535.")

        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            listener.bind((host, port))
        except OSError as exc:
            raise CommandError(f"Could not start the UDP listener: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Django syslog listener running on {host}:{port}/UDP. "
                "Press Ctrl+C to stop."
            )
        )

        try:
            with listener:
                while True:
                    data, sender = listener.recvfrom(65535)
                    source_ip, _source_port = sender
                    message = data.decode("utf-8", errors="replace").strip()
                    event = record_syslog_event(source_ip, message)
                    device_name = event.device.name if event.device else "unknown device"
                    self.stdout.write(
                        f"Stored event #{event.pk} from {source_ip} "
                        f"({device_name}, {event.severity or 'unknown severity'})"
                    )
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Django syslog listener stopped."))
