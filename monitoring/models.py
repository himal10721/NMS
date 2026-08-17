from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Device(models.Model):
    """A network device approved for monitoring by the NMS."""

    class DeviceType(models.TextChoices):
        ROUTER = "router", "Router"
        SWITCH = "switch", "Switch"
        SERVER = "server", "Server"
        WORKSTATION = "workstation", "Workstation"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        UP = "up", "Up"
        DOWN = "down", "Down"

    name = models.CharField(max_length=100, unique=True)
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(protocol="IPv4", unique=True)
    device_type = models.CharField(
        max_length=20,
        choices=DeviceType.choices,
        default=DeviceType.OTHER,
    )
    vlan_id = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4094)],
    )
    description = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)
    polling_interval_seconds = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(3600)],
    )
    # Cached status fields make the latest state quick to display in the admin
    # and, later, on the dashboard without querying the full check history.
    last_status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.UNKNOWN,
    )
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_response_time_ms = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.ip_address})"


class NetworkInterface(models.Model):
    """A physical or logical interface discovered on a monitored device."""

    class Status(models.TextChoices):
        UP = "up", "Up"
        DOWN = "down", "Down"
        TESTING = "testing", "Testing"
        UNKNOWN = "unknown", "Unknown"

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="interfaces",
    )
    interface_index = models.PositiveIntegerField()
    name = models.CharField(max_length=100)
    admin_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNKNOWN,
    )
    operational_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNKNOWN,
    )

    class Meta:
        ordering = ["device", "interface_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "interface_index"],
                name="unique_interface_index_per_device",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.device.name}: {self.name}"


class MetricDefinition(models.Model):
    """Describes a reusable metric that can be collected from many devices."""

    class DataType(models.TextChoices):
        INTEGER = "integer", "Integer"
        FLOAT = "float", "Float"
        TEXT = "text", "Text"
        BOOLEAN = "boolean", "Boolean"

    class SourceProtocol(models.TextChoices):
        SNMP = "snmp", "SNMP"
        SYSTEM = "system", "System"
        OTHER = "other", "Other"

    key = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=150)
    unit = models.CharField(max_length=30, blank=True)
    data_type = models.CharField(max_length=20, choices=DataType.choices)
    source_protocol = models.CharField(
        max_length=20,
        choices=SourceProtocol.choices,
        default=SourceProtocol.SNMP,
    )
    oid = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["display_name"]

    def __str__(self) -> str:
        return self.display_name


class MetricRecord(models.Model):
    """One metric value collected from a device at a particular time."""

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="metric_records",
    )
    interface = models.ForeignKey(
        NetworkInterface,
        on_delete=models.CASCADE,
        related_name="metric_records",
        null=True,
        blank=True,
    )
    metric_definition = models.ForeignKey(
        MetricDefinition,
        on_delete=models.PROTECT,
        related_name="records",
    )
    numeric_value = models.FloatField(null=True, blank=True)
    text_value = models.TextField(blank=True)
    collected_at = models.DateTimeField()
    collection_successful = models.BooleanField(default=True)

    class Meta:
        ordering = ["-collected_at"]
        indexes = [
            models.Index(fields=["device", "metric_definition", "-collected_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.device.name}: {self.metric_definition.key}"


class NetworkEvent(models.Model):
    """A syslog message or SNMP trap received from a network source."""

    class Protocol(models.TextChoices):
        SYSLOG = "syslog", "Syslog"
        SNMP_TRAP = "snmp_trap", "SNMP trap"

    device = models.ForeignKey(
        Device,
        on_delete=models.SET_NULL,
        related_name="network_events",
        null=True,
        blank=True,
    )
    source_ip = models.GenericIPAddressField()
    protocol = models.CharField(max_length=20, choices=Protocol.choices)
    severity = models.CharField(max_length=20, blank=True)
    message = models.TextField()
    received_at = models.DateTimeField()

    class Meta:
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["source_ip", "-received_at"])]

    def __str__(self) -> str:
        return f"{self.protocol} from {self.source_ip}"


class AvailabilityCheck(models.Model):
    """An immutable record of one availability poll for one device."""

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="availability_checks",
    )
    checked_at = models.DateTimeField()
    is_reachable = models.BooleanField()
    response_time_ms = models.FloatField(null=True, blank=True)
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        # Device/time lookups are the main query used for status history graphs.
        ordering = ["-checked_at"]
        indexes = [models.Index(fields=["device", "-checked_at"])]

    def __str__(self) -> str:
        state = "up" if self.is_reachable else "down"
        return f"{self.device.name}: {state} at {self.checked_at:%Y-%m-%d %H:%M:%S}"


class Alert(models.Model):
    """An outage event that remains open until the device becomes reachable."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    class Category(models.TextChoices):
        AVAILABILITY = "availability", "Availability"
        PERFORMANCE = "performance", "Performance"
        NETWORK_EVENT = "network_event", "Network event"

    class Severity(models.TextChoices):
        INFO = "info", "Information"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    network_event = models.ForeignKey(
        NetworkEvent,
        on_delete=models.SET_NULL,
        related_name="alerts",
        null=True,
        blank=True,
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.AVAILABILITY,
    )
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        default=Severity.CRITICAL,
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
    )
    message = models.CharField(max_length=500)
    opened_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-opened_at"]
        indexes = [models.Index(fields=["device", "status"])]

    def __str__(self) -> str:
        return f"{self.device.name}: {self.status}"
