import asyncio
import platform
import subprocess
import time
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

from .models import (
    Alert,
    AvailabilityCheck,
    Device,
    MetricDefinition,
    MetricRecord,
    NetworkEvent,
)


SYS_UPTIME_OID = "1.3.6.1.2.1.1.3.0"
CISCO_MEMORY_USED_OID = "1.3.6.1.4.1.9.9.48.1.1.1.5.1"
CISCO_MEMORY_FREE_OID = "1.3.6.1.4.1.9.9.48.1.1.1.6.1"

SYSLOG_SEVERITIES = {
    0: "emergency",
    1: "alert",
    2: "critical",
    3: "error",
    4: "warning",
    5: "notice",
    6: "informational",
    7: "debug",
}


@dataclass(frozen=True)
class PingResult:
    """Normalized result returned by the operating-system ping command."""

    is_reachable: bool
    response_time_ms: float | None
    error: str = ""


@dataclass(frozen=True)
class SnmpResult:
    """Normalized result of one SNMP metric request."""

    successful: bool
    value: float | None
    error: str = ""


@dataclass(frozen=True)
class MemoryResult:
    """Normalized Cisco processor-memory values returned through SNMP."""

    successful: bool
    used_bytes: int | None
    free_bytes: int | None
    error: str = ""

    @property
    def usage_percent(self) -> float | None:
        """Calculate used memory as a percentage of total processor memory."""

        if self.used_bytes is None or self.free_bytes is None:
            return None
        total_bytes = self.used_bytes + self.free_bytes
        if total_bytes == 0:
            return None
        return round((self.used_bytes / total_bytes) * 100, 2)


async def fetch_snmp_timeticks(
    ip_address: str,
    community: str,
    oid: str = SYS_UPTIME_OID,
    timeout_seconds: int = 2,
) -> SnmpResult:
    """Retrieve an SNMP TimeTicks value and convert it to minutes."""

    try:
        transport = await UdpTransportTarget.create(
            (ip_address, 161),
            timeout=timeout_seconds,
            retries=1,
        )
        error_indication, error_status, error_index, var_binds = await get_cmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1),
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
    except Exception as exc:  # PySNMP can raise transport and decoding errors.
        return SnmpResult(False, None, str(exc))

    if error_indication:
        return SnmpResult(False, None, str(error_indication))

    if error_status:
        error = f"{error_status.prettyPrint()} at index {error_index}"
        return SnmpResult(False, None, error)

    if not var_binds:
        return SnmpResult(False, None, "SNMP response contained no values.")

    try:
        # SNMP TimeTicks are hundredths of a second; 6,000 ticks equal a minute.
        uptime_minutes = round(int(var_binds[0][1]) / 6000, 2)
    except (TypeError, ValueError, IndexError) as exc:
        return SnmpResult(False, None, f"Invalid SNMP value: {exc}")

    return SnmpResult(True, uptime_minutes)


async def fetch_memory_usage(
    ip_address: str,
    community: str,
    timeout_seconds: int = 2,
) -> MemoryResult:
    """Retrieve used and free bytes from Cisco's Processor memory pool."""

    try:
        transport = await UdpTransportTarget.create(
            (ip_address, 161),
            timeout=timeout_seconds,
            retries=1,
        )
        error_indication, error_status, error_index, var_binds = await get_cmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1),
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(CISCO_MEMORY_USED_OID)),
            ObjectType(ObjectIdentity(CISCO_MEMORY_FREE_OID)),
        )
    except Exception as exc:
        return MemoryResult(False, None, None, str(exc))

    if error_indication:
        return MemoryResult(False, None, None, str(error_indication))

    if error_status:
        error = f"{error_status.prettyPrint()} at index {error_index}"
        return MemoryResult(False, None, None, error)

    if len(var_binds) != 2:
        return MemoryResult(False, None, None, "Incomplete SNMP memory response.")

    try:
        used_bytes = int(var_binds[0][1])
        free_bytes = int(var_binds[1][1])
    except (TypeError, ValueError, IndexError) as exc:
        return MemoryResult(False, None, None, f"Invalid memory value: {exc}")

    return MemoryResult(True, used_bytes, free_bytes)


def ping_device(ip_address: str, timeout_seconds: int = 2) -> PingResult:
    """Ping one IPv4 address safely and normalize platform-specific output."""
    # Windows and Unix ping utilities use different flags for count and timeout.
    if platform.system() == "Windows":
        command = ["ping", "-n", "1", "-w", str(timeout_seconds * 1000), ip_address]
    else:
        command = ["ping", "-c", "1", "-W", str(timeout_seconds), ip_address]

    started_at = time.perf_counter()
    try:
        # shell=False prevents address values from being treated as shell commands.
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
        # resolve any open outage alerts for this device after recovery
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


@transaction.atomic
def record_system_uptime(
    device: Device,
    result: SnmpResult,
    collected_at=None,
) -> MetricRecord:
    """Store one successful or failed SNMP system-uptime collection."""

    definition, _ = MetricDefinition.objects.update_or_create(
        key="system_uptime",
        defaults={
            "display_name": "System uptime",
            "unit": "minutes",
            "data_type": MetricDefinition.DataType.FLOAT,
            "source_protocol": MetricDefinition.SourceProtocol.SNMP,
            "oid": SYS_UPTIME_OID,
        },
    )

    return MetricRecord.objects.create(
        device=device,
        metric_definition=definition,
        numeric_value=result.value,
        text_value=result.error,
        collected_at=collected_at or timezone.now(),
        collection_successful=result.successful,
    )


def poll_system_uptime(device: Device, community: str) -> MetricRecord:
    """Retrieve and store one device-uptime measurement through SNMP."""

    result = asyncio.run(
        fetch_snmp_timeticks(
            ip_address=str(device.ip_address),
            community=community,
        )
    )
    return record_system_uptime(device, result)


@transaction.atomic
def record_memory_usage(
    device: Device,
    result: MemoryResult,
    collected_at=None,
) -> dict[str, MetricRecord]:
    """Store Cisco processor-memory usage, free memory, and percentage."""

    collected_at = collected_at or timezone.now()
    definitions = {
        "memory_used_mb": {
            "display_name": "Memory used",
            "unit": "MB",
            "oid": CISCO_MEMORY_USED_OID,
        },
        "memory_free_mb": {
            "display_name": "Memory free",
            "unit": "MB",
            "oid": CISCO_MEMORY_FREE_OID,
        },
        "memory_usage_percent": {
            "display_name": "Memory usage",
            "unit": "%",
            "oid": f"{CISCO_MEMORY_USED_OID} + {CISCO_MEMORY_FREE_OID}",
        },
    }
    values = {
        "memory_used_mb": (
            round(result.used_bytes / (1024 * 1024), 2)
            if result.used_bytes is not None
            else None
        ),
        "memory_free_mb": (
            round(result.free_bytes / (1024 * 1024), 2)
            if result.free_bytes is not None
            else None
        ),
        "memory_usage_percent": result.usage_percent,
    }

    records = {}
    for key, metadata in definitions.items():
        definition, _ = MetricDefinition.objects.update_or_create(
            key=key,
            defaults={
                **metadata,
                "data_type": MetricDefinition.DataType.FLOAT,
                "source_protocol": MetricDefinition.SourceProtocol.SNMP,
            },
        )
        records[key] = MetricRecord.objects.create(
            device=device,
            metric_definition=definition,
            numeric_value=values[key],
            text_value=result.error,
            collected_at=collected_at,
            collection_successful=result.successful,
        )

    return records


def poll_memory_usage(device: Device, community: str) -> dict[str, MetricRecord]:
    """Retrieve and store Cisco processor-memory measurements."""

    result = asyncio.run(
        fetch_memory_usage(
            ip_address=str(device.ip_address),
            community=community,
        )
    )
    return record_memory_usage(device, result)


def get_syslog_severity(message: str) -> str:
    """Extract the severity from a leading syslog PRI value such as <189>."""

    if not message.startswith("<"):
        return ""

    closing_bracket = message.find(">", 1, 6)
    if closing_bracket == -1:
        return ""

    try:
        priority = int(message[1:closing_bracket])
    except ValueError:
        return ""

    if not 0 <= priority <= 191:
        return ""
    return SYSLOG_SEVERITIES[priority % 8]


def record_syslog_event(
    source_ip: str,
    message: str,
    received_at=None,
) -> NetworkEvent:
    """Match a syslog sender to a device and store its message through Django."""

    device = Device.objects.filter(ip_address=source_ip).first()
    return NetworkEvent.objects.create(
        device=device,
        source_ip=source_ip,
        protocol=NetworkEvent.Protocol.SYSLOG,
        severity=get_syslog_severity(message),
        message=message or "<empty message>",
        received_at=received_at or timezone.now(),
    )
