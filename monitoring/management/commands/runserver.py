"""Development server that supervises the NMS background workers."""

import os
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import (
    Command as DjangoRunserverCommand,
)
from django.core.management.base import CommandError


class Command(DjangoRunserverCommand):
    """Run Django and the local monitoring commands from one terminal."""

    help = (
        "Starts Django's development server and the ICMP, SNMP, and syslog "
        "monitoring workers."
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--no-monitoring",
            action="store_true",
            help="Start only Django's development web server.",
        )

    def handle(self, *args, **options):
        # Django's Windows auto-reloader creates and replaces child processes.
        # That can bypass the worker-cleanup finally block and leave duplicate
        # monitors running. Use a single server process when supervision is on.
        if not options["no_monitoring"] and options.get("use_reloader"):
            options["use_reloader"] = False
            self.stdout.write(
                self.style.WARNING(
                    "Auto-reload disabled while monitoring workers are managed."
                )
            )
        return super().handle(*args, **options)

    def inner_run(self, *args, **options):
        if options["no_monitoring"]:
            return super().inner_run(*args, **options)

        workers = self._start_monitoring_workers()
        try:
            return super().inner_run(*args, **options)
        finally:
            self._stop_monitoring_workers(workers)

    def _start_monitoring_workers(self):
        """Start each existing worker as a managed child process."""

        community = os.environ.get("SNMP_COMMUNITY")
        if not community:
            raise CommandError(
                "SNMP_COMMUNITY is not set. Set it before runserver, or use "
                "--no-monitoring to run only the website."
            )

        manage_py = Path(settings.BASE_DIR) / "manage.py"
        device_name = os.environ.get("NMS_SNMP_DEVICE", "R1")
        snmp_interval = os.environ.get("NMS_SNMP_INTERVAL", "60")
        syslog_host = os.environ.get("NMS_SYSLOG_HOST", "0.0.0.0")
        syslog_port = os.environ.get("NMS_SYSLOG_PORT", "514")

        commands = (
            ("ICMP monitor", ["run_monitor"]),
            (
                "SNMP monitor",
                [
                    "run_snmp_monitor",
                    "--device",
                    device_name,
                    "--interval",
                    snmp_interval,
                ],
            ),
            (
                "Syslog listener",
                ["run_syslog_listener", "--host", syslog_host, "--port", syslog_port],
            ),
        )

        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        workers = []
        for label, command_arguments in commands:
            process = subprocess.Popen(
                [sys.executable, str(manage_py), *command_arguments],
                cwd=settings.BASE_DIR,
                env=os.environ.copy(),
                creationflags=creation_flags,
            )
            workers.append((label, process))
            self.stdout.write(
                self.style.SUCCESS(f"Started {label} (PID {process.pid}).")
            )

        # Binding failures such as an occupied UDP 514 port happen immediately.
        time.sleep(1)
        failed_workers = [
            f"{label} exited with code {process.returncode}"
            for label, process in workers
            if process.poll() is not None
        ]
        if failed_workers:
            self._stop_monitoring_workers(workers)
            raise CommandError("; ".join(failed_workers))

        return workers

    def _stop_monitoring_workers(self, workers):
        """Stop every child worker when runserver exits or startup fails."""

        for _label, process in workers:
            if process.poll() is None:
                process.terminate()

        for label, process in workers:
            if process.poll() is not None:
                continue
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            self.stdout.write(self.style.WARNING(f"Stopped {label}."))
