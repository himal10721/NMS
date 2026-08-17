from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Alert,
    AvailabilityCheck,
    Device,
    MetricDefinition,
    MetricRecord,
    NetworkEvent,
    NetworkInterface,
)
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


class NetworkInterfaceModelTests(TestCase):
    def test_device_can_have_multiple_network_interfaces(self):
        device = Device.objects.create(
            name="ESW2",
            ip_address="192.168.10.2",
            device_type=Device.DeviceType.SWITCH,
            vlan_id=10,
        )
        NetworkInterface.objects.create(
            device=device,
            interface_index=1,
            name="FastEthernet0/0",
            admin_status=NetworkInterface.Status.UP,
            operational_status=NetworkInterface.Status.UP,
        )
        NetworkInterface.objects.create(
            device=device,
            interface_index=2,
            name="FastEthernet0/1",
            admin_status=NetworkInterface.Status.UP,
            operational_status=NetworkInterface.Status.UP,
        )

        self.assertEqual(device.interfaces.count(), 2)


class ExpandedDatabaseModelTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name="R1-metrics",
            ip_address="192.168.10.101",
            device_type=Device.DeviceType.ROUTER,
            vlan_id=10,
        )

    def test_metric_definition_is_reused_by_metric_records(self):
        definition = MetricDefinition.objects.create(
            key="device_uptime",
            display_name="Device uptime",
            unit="seconds",
            data_type=MetricDefinition.DataType.INTEGER,
            source_protocol=MetricDefinition.SourceProtocol.SNMP,
            oid="1.3.6.1.2.1.1.3.0",
        )
        MetricRecord.objects.create(
            device=self.device,
            metric_definition=definition,
            numeric_value=1200,
            collected_at=timezone.now(),
        )
        MetricRecord.objects.create(
            device=self.device,
            metric_definition=definition,
            numeric_value=1260,
            collected_at=timezone.now(),
        )

        self.assertEqual(definition.records.count(), 2)
        self.assertEqual(self.device.metric_records.count(), 2)

    def test_metric_record_can_belong_to_an_interface(self):
        interface = NetworkInterface.objects.create(
            device=self.device,
            interface_index=1,
            name="FastEthernet0/0",
            admin_status=NetworkInterface.Status.UP,
            operational_status=NetworkInterface.Status.UP,
        )
        definition = MetricDefinition.objects.create(
            key="interface_in_octets",
            display_name="Interface inbound octets",
            unit="octets",
            data_type=MetricDefinition.DataType.INTEGER,
            source_protocol=MetricDefinition.SourceProtocol.SNMP,
            oid="1.3.6.1.2.1.2.2.1.10",
        )
        record = MetricRecord.objects.create(
            device=self.device,
            interface=interface,
            metric_definition=definition,
            numeric_value=4096,
            collected_at=timezone.now(),
        )

        self.assertEqual(record.interface, interface)
        self.assertEqual(interface.metric_records.count(), 1)

    def test_network_event_can_generate_an_alert(self):
        event = NetworkEvent.objects.create(
            device=self.device,
            source_ip=self.device.ip_address,
            protocol=NetworkEvent.Protocol.SYSLOG,
            severity="critical",
            message="Interface FastEthernet0/0 changed state to down",
            received_at=timezone.now(),
        )
        alert = Alert.objects.create(
            device=self.device,
            network_event=event,
            category=Alert.Category.NETWORK_EVENT,
            severity=Alert.Severity.CRITICAL,
            message="Critical network event received",
            opened_at=timezone.now(),
        )

        self.assertEqual(event.alerts.count(), 1)
        self.assertEqual(alert.network_event, event)


class DashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="dashboard-admin",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(self.user)

    def test_dashboard_requires_staff_login(self):
        self.client.logout()

        response = self.client.get(reverse("monitoring:dashboard"))

        self.assertEqual(response.status_code, 302)

    def test_dashboard_displays_device_summary(self):
        Device.objects.create(
            name="R1-dashboard",
            ip_address="192.168.10.11",
            device_type=Device.DeviceType.ROUTER,
            vlan_id=10,
            last_status=Device.Status.UP,
        )

        response = self.client.get(reverse("monitoring:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "R1-dashboard")
        self.assertEqual(response.context["total_devices"], 1)
        self.assertEqual(response.context["up_devices"], 1)
