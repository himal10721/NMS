from datetime import timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from .models import (
    Alert,
    AvailabilityCheck,
    Device,
    MetricRecord,
    NetworkEvent,
    NetworkInterface,
)


PERFORMANCE_METRICS = (
    ("internet_download_mbps", "Download", "Mbps"),
    ("internet_upload_mbps", "Upload", "Mbps"),
    ("internet_icmp_latency_ms", "Latency", "ms"),
    ("internet_packet_loss_percent", "Packet loss", "%"),
)


def _latest_metric(key):
    return (
        MetricRecord.objects.filter(
            metric_definition__key=key,
            collection_successful=True,
            numeric_value__isnull=False,
        )
        .select_related("device", "metric_definition")
        .first()
    )


def _latest_reachable_router_metric(key):
    """Return a router metric only while its device is currently reachable."""
    return (
        MetricRecord.objects.filter(
            metric_definition__key=key,
            device__device_type=Device.DeviceType.ROUTER,
            device__last_status=Device.Status.UP,
            collection_successful=True,
            numeric_value__isnull=False,
        )
        .select_related("device", "metric_definition")
        .first()
    )


@login_required
@permission_required("monitoring.view_device", raise_exception=True)
def dashboard(request):
    """Show monitoring data only to users granted device-view permission."""
    devices = Device.objects.all()
    up_count = devices.filter(last_status=Device.Status.UP).count()
    down_count = devices.filter(last_status=Device.Status.DOWN).count()
    unknown_count = devices.filter(last_status=Device.Status.UNKNOWN).count()
    range_key = request.GET.get("range", "24h")
    range_options = {"1h": ("Last hour", 1), "24h": ("Last 24 hours", 24), "7d": ("Last 7 days", 168)}
    if range_key not in range_options:
        range_key = "24h"
    range_label, range_hours = range_options[range_key]
    range_start = timezone.now() - timedelta(hours=range_hours)

    performance_metrics = []
    for key, label, unit in PERFORMANCE_METRICS:
        performance_metrics.append(
            {"key": key, "label": label, "unit": unit, "record": _latest_metric(key)}
        )

    performance_records = list(
        MetricRecord.objects.filter(
            metric_definition__key__in=[item[0] for item in PERFORMANCE_METRICS],
            collection_successful=True,
            numeric_value__isnull=False,
            collected_at__gte=range_start,
        )
        .select_related("metric_definition")
        .order_by("collected_at")
    )
    chart_series = {}
    for key, label, unit in PERFORMANCE_METRICS:
        points = [
            {
                "time": record.collected_at.isoformat(),
                "label": timezone.localtime(record.collected_at).strftime("%H:%M"),
                "value": round(record.numeric_value, 2),
            }
            for record in performance_records
            if record.metric_definition.key == key
        ][-24:]
        chart_series[key] = {"label": label, "unit": unit, "points": points}

    recent_checks = AvailabilityCheck.objects.select_related("device")[:10]
    checked_count = AvailabilityCheck.objects.count()
    reachable_count = AvailabilityCheck.objects.filter(is_reachable=True).count()
    availability_percent = (
        round((reachable_count / checked_count) * 100, 1) if checked_count else None
    )
    device_type_counts = list(
        devices.values("device_type").annotate(total=Count("id")).order_by("device_type")
    )
    event_source_counts = list(
        NetworkEvent.objects.filter(received_at__gte=range_start)
        .values("source_ip")
        .annotate(total=Count("id"))
        .order_by("-total")[:6]
    )
    alert_severity_counts = {
        item["severity"]: item["total"]
        for item in Alert.objects.filter(status=Alert.Status.OPEN)
        .values("severity")
        .annotate(total=Count("id"))
    }
    interface_counts = {
        item["operational_status"]: item["total"]
        for item in NetworkInterface.objects.values("operational_status").annotate(total=Count("id"))
    }
    interface_utilization = []
    for interface in NetworkInterface.objects.select_related("device"):
        latest = (
            MetricRecord.objects.filter(
                interface=interface,
                metric_definition__key="interface_utilization_percent",
                collection_successful=True,
                numeric_value__isnull=False,
            )
            .select_related("metric_definition")
            .first()
        )
        if latest:
            interface_utilization.append({"interface": interface, "record": latest})
    interface_utilization.sort(
        key=lambda item: item["record"].numeric_value,
        reverse=True,
    )
    open_alert_total = sum(alert_severity_counts.values())
    alert_critical_end = round(
        alert_severity_counts.get(Alert.Severity.CRITICAL, 0) * 100 / open_alert_total
    ) if open_alert_total else 0
    alert_warning_end = round(
        (
            alert_severity_counts.get(Alert.Severity.CRITICAL, 0)
            + alert_severity_counts.get(Alert.Severity.WARNING, 0)
        ) * 100 / open_alert_total
    ) if open_alert_total else 0
    total_device_count = devices.count()
    device_down_end = round(
        down_count * 100 / total_device_count
    ) if total_device_count else 0
    device_unknown_end = round(
        (down_count + unknown_count) * 100 / total_device_count
    ) if total_device_count else 0

    context = {
        "devices": devices,
        "total_devices": devices.count(),
        "up_devices": up_count,
        "down_devices": down_count,
        "unknown_devices": unknown_count,
        "open_alerts": Alert.objects.filter(
            status=Alert.Status.OPEN
        ).select_related("device"),
        "recent_checks": recent_checks,
        "recent_events": NetworkEvent.objects.select_related("device")[:6],
        "performance_metrics": performance_metrics,
        "chart_series": chart_series,
        "availability_percent": availability_percent,
        "latest_uptime": _latest_reachable_router_metric("system_uptime"),
        "latest_memory": _latest_reachable_router_metric("memory_usage_percent"),
        "latest_cpu": _latest_reachable_router_metric("cpu_usage_percent"),
        "range_key": range_key,
        "range_label": range_label,
        "device_type_counts": device_type_counts,
        "event_source_counts": event_source_counts,
        "alert_severity_counts": alert_severity_counts,
        "interface_counts": interface_counts,
        "interface_utilization": interface_utilization[:5],
        "alert_critical_end": alert_critical_end,
        "alert_warning_end": alert_warning_end,
        "device_down_end": device_down_end,
        "device_unknown_end": device_unknown_end,
    }

    return render(request, "monitoring/dashboard.html", context)
