from django.contrib import admin

from .models import Alert, AvailabilityCheck, Device


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
class AlertAdmin(admin.ModelAdmin):
    list_display = ("device", "status", "opened_at", "resolved_at", "message")
    list_filter = ("status", "opened_at")
    search_fields = ("device__name", "device__ip_address", "message")
    readonly_fields = ("device", "status", "message", "opened_at", "resolved_at")
