from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from .models import Alert, AvailabilityCheck, Device


@staff_member_required
def dashboard(request):
    """Show the latest device states, checks, and unresolved alerts."""
    devices = Device.objects.all()

    context = {
        "devices": devices,
        "total_devices": devices.count(),
        "up_devices": devices.filter(last_status=Device.Status.UP).count(),
        "down_devices": devices.filter(last_status=Device.Status.DOWN).count(),
        "unknown_devices": devices.filter(
            last_status=Device.Status.UNKNOWN
        ).count(),
        "open_alerts": Alert.objects.filter(
            status=Alert.Status.OPEN
        ).select_related("device"),
        "recent_checks": AvailabilityCheck.objects.select_related("device")[:10],
    }

    return render(request, "monitoring/dashboard.html", context)
