from django.contrib import admin

from .models import (
    Alert,
    AvailabilityCheck,
    Device,
    MetricDefinition,
    MetricRecord,
    NetworkEvent,
    NetworkInterface,
)


# register Device with the Django admin site
@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "ip_address",
        "device_type",
        "vlan_id",
        "last_status",
        "last_response_time_ms",
        "last_checked_at",
        "is_enabled",
    )
    list_filter = ("device_type", "vlan_id", "last_status", "is_enabled")
    search_fields = ("name", "hostname", "ip_address")
    readonly_fields = (
        "last_status",
        "last_response_time_ms",
        "last_checked_at",
        "created_at",
        "updated_at",
    )


@admin.register(AvailabilityCheck)
# register availability history records in the admin
class AvailabilityCheckAdmin(admin.ModelAdmin):
    list_display = (
        "device",
        "checked_at",
        "is_reachable",
        "response_time_ms",
        "error",
    )
    list_filter = ("is_reachable", "checked_at")
    search_fields = ("device__name", "device__ip_address", "error")
    readonly_fields = (
        "device",
        "checked_at",
        "is_reachable",
        "response_time_ms",
        "error",
    )


@admin.register(Alert)
# register alert records so outages can be viewed in admin
class AlertAdmin(admin.ModelAdmin):
    list_display = ("device", "status", "opened_at", "resolved_at", "message")
    list_filter = ("status", "opened_at")
    search_fields = ("device__name", "device__ip_address", "message")
    readonly_fields = ("device", "status", "message", "opened_at", "resolved_at")


@admin.register(NetworkInterface)
class NetworkInterfaceAdmin(admin.ModelAdmin):
    """Display interfaces discovered on each monitored device."""

    list_display = (
        "device",
        "interface_index",
        "name",
        "admin_status",
        "operational_status",
    )
    list_filter = ("admin_status", "operational_status")
    search_fields = ("device__name", "device__ip_address", "name")


@admin.register(MetricDefinition)
class MetricDefinitionAdmin(admin.ModelAdmin):
    """Display the catalogue describing every collected metric."""

    list_display = (
        "key",
        "display_name",
        "unit",
        "data_type",
        "source_protocol",
        "oid",
    )
    list_filter = ("data_type", "source_protocol")
    search_fields = ("key", "display_name", "oid")


@admin.register(MetricRecord)
class MetricRecordAdmin(admin.ModelAdmin):
    """Provide a read-only history of automatically collected measurements."""

    list_display = (
        "device",
        "metric_definition",
        "numeric_value",
        "text_value",
        "collected_at",
        "collection_successful",
    )
    list_filter = (
        "collection_successful",
        "metric_definition",
        "device",
        "collected_at",
    )
    search_fields = (
        "device__name",
        "device__ip_address",
        "metric_definition__display_name",
    )
    list_select_related = ("device", "metric_definition", "interface")
    readonly_fields = (
        "device",
        "interface",
        "metric_definition",
        "numeric_value",
        "text_value",
        "collected_at",
        "collection_successful",
    )


@admin.register(NetworkEvent)
class NetworkEventAdmin(admin.ModelAdmin):
    """Display received syslog and SNMP-trap events."""

    list_display = (
        "source_ip",
        "device",
        "protocol",
        "severity",
        "received_at",
        "message",
    )
    list_filter = ("protocol", "severity", "received_at")
    search_fields = ("source_ip", "device__name", "message")
    readonly_fields = (
        "device",
        "source_ip",
        "protocol",
        "severity",
        "message",
        "received_at",
    )
