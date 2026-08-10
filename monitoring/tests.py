from django.test import TestCase
from django.utils import timezone

from .models import Alert, AvailabilityCheck, Device
from .services import PingResult, record_availability_result


class AvailabilityRecordingTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name="R1",
            hostname="R1",
            ip_address="192.168.10.1",
            device_type=Device.DeviceType.ROUTER,
            vlan_id=10,
        )

    def test_records_reachable_device(self):
        checked_at = timezone.now()

        record_availability_result(
            self.device,
            PingResult(True, 4.25),
            checked_at=checked_at,
        )

        self.device.refresh_from_db()
        self.assertEqual(self.device.last_status, Device.Status.UP)
        self.assertEqual(self.device.last_response_time_ms, 4.25)
        self.assertEqual(AvailabilityCheck.objects.count(), 1)
        self.assertEqual(Alert.objects.count(), 0)

    def test_opens_only_one_alert_while_device_remains_down(self):
        result = PingResult(False, None, "Request timed out")

        record_availability_result(self.device, result)
        record_availability_result(self.device, result)

        self.assertEqual(AvailabilityCheck.objects.count(), 2)
        self.assertEqual(Alert.objects.filter(status=Alert.Status.OPEN).count(), 1)

    def test_resolves_open_alert_when_device_recovers(self):
        record_availability_result(
            self.device,
            PingResult(False, None, "Request timed out"),
        )
        record_availability_result(self.device, PingResult(True, 3.5))

        self.device.refresh_from_db()
        alert = Alert.objects.get()
        self.assertEqual(self.device.last_status, Device.Status.UP)
        self.assertEqual(alert.status, Alert.Status.RESOLVED)
        self.assertIsNotNone(alert.resolved_at)
