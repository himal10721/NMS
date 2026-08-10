import platform
import subprocess
import time
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import Alert, AvailabilityCheck, Device


@dataclass(frozen=True)
class PingResult:
    """Normalized result returned by the operating-system ping command."""

    is_reachable: bool
    response_time_ms: float | None
    error: str = ""


def ping_device(ip_address: str, timeout_seconds: int = 2) -> PingResult:
    """Ping one IPv4 address safely and normalize platform-specific output."""
    # Windows and Unix ping utilities use different flags for count and timeout.
    if platform.system() == "Windows":
        command = ["ping", "-n", "1", "-w", str(timeout_seconds * 1000), ip_address]
    else:
        command = ["ping", "-c", "1", "-W", str(timeout_seconds), ip_address]

    started_at = time.perf_counter()
    try:
        # shell=False (the default) prevents an address from being interpreted as
        # a shell command. Device addresses are also validated by Django as IPv4.
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return PingResult(False, None, str(exc))

    # perf_counter measures elapsed duration independently of system-clock changes.
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    if completed.returncode == 0:
        return PingResult(True, elapsed_ms)

    error = (completed.stderr or completed.stdout or "Ping failed").strip()
    return PingResult(False, None, error[-500:])


@transaction.atomic
def record_availability_result(
    device: Device,
    result: PingResult,
    checked_at=None,
) -> AvailabilityCheck:
    """Persist a poll result and apply outage/recovery state transitions."""
    checked_at = checked_at or timezone.now()
    previous_status = device.last_status
    current_status = Device.Status.UP if result.is_reachable else Device.Status.DOWN

    check = AvailabilityCheck.objects.create(
        device=device,
        checked_at=checked_at,
        is_reachable=result.is_reachable,
        response_time_ms=result.response_time_ms,
        error=result.error,
    )

    device.last_status = current_status
    device.last_checked_at = checked_at
    device.last_response_time_ms = result.response_time_ms
    device.save(
        update_fields=[
            "last_status",
            "last_checked_at",
            "last_response_time_ms",
            "updated_at",
        ]
    )

    # Open only one alert when the state first changes to DOWN. Repeated failed
    # polls remain in AvailabilityCheck history without causing alert flooding.
    if current_status == Device.Status.DOWN and previous_status != Device.Status.DOWN:
        Alert.objects.create(
            device=device,
            status=Alert.Status.OPEN,
            message=f"{device.name} is unreachable at {device.ip_address}.",
            opened_at=checked_at,
        )
    # A successful poll following a DOWN state resolves every open outage alert
    # for that device and preserves both the opening and recovery timestamps.
    elif current_status == Device.Status.UP and previous_status == Device.Status.DOWN:
        Alert.objects.filter(
            device=device,
            status=Alert.Status.OPEN,
        ).update(
            status=Alert.Status.RESOLVED,
            resolved_at=checked_at,
        )

    return check


def poll_device(device: Device) -> AvailabilityCheck:
    """Run and record one availability poll for a device."""
    result = ping_device(device.ip_address)
    return record_availability_result(device, result)
