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

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="alerts",
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
