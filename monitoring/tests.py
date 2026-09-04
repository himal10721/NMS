from datetime import timedelta
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
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
from .services import (
    MemoryResult,
    InterfaceSample,
    NetworkPerformanceResult,
    PingResult,
    SnmpResult,
    collect_network_performance,
    poll_memory_usage,
    poll_system_uptime,
    record_availability_result,
    record_cpu_usage,
    record_interface_samples,
    record_network_performance,
    record_syslog_event,
)
from .rbac import MONITORING_USERS_GROUP, NETWORK_ADMINISTRATORS_GROUP


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

    def test_single_failed_check_does_not_open_false_alarm(self):
        record_availability_result(
            self.device,
            PingResult(False, None, "Request timed out"),
        )

        self.assertEqual(Alert.objects.count(), 0)


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

    def test_interface_samples_create_rates_and_failure_alert(self):
        device = Device.objects.create(
            name="R1-interface",
            ip_address="192.168.10.21",
            device_type=Device.DeviceType.ROUTER,
            vlan_id=10,
        )
        first_at = timezone.now()
        record_interface_samples(
            device,
            [InterfaceSample(1, "FastEthernet0/0", 1000, 1, 1, 1000, 2000)],
            first_at,
        )
        record_interface_samples(
            device,
            [InterfaceSample(1, "FastEthernet0/0", 1000, 1, 2, 1600, 2600)],
            first_at + timedelta(seconds=60),
        )

        interface = device.interfaces.get(interface_index=1)
        inbound = MetricRecord.objects.filter(
            interface=interface,
            metric_definition__key="interface_in_bps",
            collection_successful=True,
        ).first()
        self.assertEqual(interface.operational_status, NetworkInterface.Status.DOWN)
        self.assertEqual(inbound.numeric_value, 80.0)
        self.assertTrue(
            Alert.objects.filter(message__startswith="[INTERFACE:1]").exists()
        )


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


class SnmpPollingTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name="R1-snmp",
            ip_address="192.168.10.101",
            device_type=Device.DeviceType.ROUTER,
            vlan_id=10,
        )

    @patch("monitoring.services.fetch_snmp_timeticks", new_callable=AsyncMock)
    def test_poll_system_uptime_stores_successful_metric(self, mock_fetch):
        mock_fetch.return_value = SnmpResult(True, 52.97)

        record = poll_system_uptime(self.device, "test-community")

        self.assertTrue(record.collection_successful)
        self.assertEqual(record.numeric_value, 52.97)
        self.assertEqual(record.metric_definition.key, "system_uptime")
        self.assertEqual(record.metric_definition.unit, "minutes")

    @patch("monitoring.services.fetch_snmp_timeticks", new_callable=AsyncMock)
    def test_poll_system_uptime_stores_failed_collection(self, mock_fetch):
        mock_fetch.return_value = SnmpResult(False, None, "No SNMP response")

        record = poll_system_uptime(self.device, "invalid-community")

        self.assertFalse(record.collection_successful)
        self.assertIsNone(record.numeric_value)
        self.assertEqual(record.text_value, "No SNMP response")

    @patch("monitoring.services.fetch_memory_usage", new_callable=AsyncMock)
    def test_poll_memory_usage_stores_mb_and_percentage(self, mock_fetch):
        mock_fetch.return_value = MemoryResult(
            True,
            used_bytes=50 * 1024 * 1024,
            free_bytes=350 * 1024 * 1024,
        )

        records = poll_memory_usage(self.device, "test-community")

        self.assertEqual(records["memory_used_mb"].numeric_value, 50.0)
        self.assertEqual(records["memory_free_mb"].numeric_value, 350.0)
        self.assertEqual(records["memory_usage_percent"].numeric_value, 12.5)
        self.assertTrue(records["memory_usage_percent"].collection_successful)

    @patch("monitoring.services.fetch_memory_usage", new_callable=AsyncMock)
    def test_poll_memory_usage_stores_failed_collection(self, mock_fetch):
        mock_fetch.return_value = MemoryResult(False, None, None, "SNMP timeout")

        records = poll_memory_usage(self.device, "invalid-community")

        self.assertEqual(len(records), 3)
        for record in records.values():
            self.assertFalse(record.collection_successful)
            self.assertIsNone(record.numeric_value)
            self.assertEqual(record.text_value, "SNMP timeout")

    def test_cpu_usage_is_stored_and_generates_threshold_alert(self):
        record = record_cpu_usage(self.device, SnmpResult(True, 7.0))

        self.assertEqual(record.metric_definition.key, "cpu_usage_percent")
        self.assertEqual(record.numeric_value, 7.0)
        self.assertTrue(Alert.objects.filter(message__startswith="[CPU]").exists())

        record_cpu_usage(self.device, SnmpResult(True, 0.5))
        self.assertFalse(
            Alert.objects.filter(
                message__startswith="[CPU]",
                status=Alert.Status.OPEN,
            ).exists()
        )


class NetworkPerformanceTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name="Performance Host",
            ip_address="192.168.20.25",
            device_type=Device.DeviceType.SERVER,
            vlan_id=20,
        )

    def test_record_network_performance_stores_five_metrics(self):
        result = NetworkPerformanceResult(
            average_latency_ms=18.0,
            packet_loss_percent=0.0,
            speedtest_latency_ms=30.5,
            download_mbps=300.25,
            upload_mbps=40.75,
        )

        records = record_network_performance(self.device, result)

        self.assertEqual(len(records), 5)
        self.assertEqual(MetricRecord.objects.count(), 5)
        self.assertEqual(
            records["internet_download_mbps"].numeric_value,
            300.25,
        )
        self.assertEqual(
            records["internet_download_mbps"].metric_definition.unit,
            "Mbps",
        )
        self.assertTrue(
            all(record.collection_successful for record in records.values())
        )

    def test_speedtest_failure_preserves_successful_ping_metrics(self):
        result = NetworkPerformanceResult(
            average_latency_ms=20.0,
            packet_loss_percent=25.0,
            error="Speed test failed: unavailable",
        )

        records = record_network_performance(self.device, result)

        self.assertTrue(records["internet_icmp_latency_ms"].collection_successful)
        self.assertTrue(
            records["internet_packet_loss_percent"].collection_successful
        )
        self.assertFalse(records["internet_download_mbps"].collection_successful)
        self.assertIn(
            "Speed test failed",
            records["internet_download_mbps"].text_value,
        )

    def test_performance_threshold_alert_opens_and_resolves(self):
        record_network_performance(
            self.device,
            NetworkPerformanceResult(150.0, 10.0),
        )

        self.assertEqual(
            Alert.objects.filter(category=Alert.Category.PERFORMANCE).count(),
            2,
        )

        record_network_performance(
            self.device,
            NetworkPerformanceResult(0.5, 0.0),
        )

        self.assertEqual(
            Alert.objects.filter(
                category=Alert.Category.PERFORMANCE,
                status=Alert.Status.OPEN,
            ).count(),
            0,
        )

    @patch("monitoring.services.measure_network_performance")
    def test_collect_network_performance_uses_measurement_service(self, mock_measure):
        mock_measure.return_value = NetworkPerformanceResult(12.0, 0.0)

        records = collect_network_performance(
            self.device,
            target="1.1.1.1",
            count=3,
            include_speedtest=False,
        )

        mock_measure.assert_called_once_with(
            target="1.1.1.1",
            count=3,
            include_speedtest=False,
        )
        self.assertEqual(records["internet_icmp_latency_ms"].numeric_value, 12.0)

    @patch("monitoring.management.commands.collect_network_performance.collect_network_performance")
    def test_management_command_runs_one_collection(self, mock_collect):
        result = NetworkPerformanceResult(10.0, 0.0)
        mock_collect.return_value = record_network_performance(self.device, result)

        call_command(
            "collect_network_performance",
            device=self.device.name,
            target="8.8.8.8",
            count=2,
            ping_only=True,
            verbosity=0,
        )

        mock_collect.assert_called_once_with(
            device=self.device,
            target="8.8.8.8",
            count=2,
            include_speedtest=False,
        )

    @patch(
        "monitoring.management.commands.run_performance_monitor."
        "collect_network_performance"
    )
    def test_continuous_performance_command_supports_one_collection(
        self,
        mock_collect,
    ):
        result = NetworkPerformanceResult(
            average_latency_ms=15.0,
            packet_loss_percent=0.0,
            speedtest_latency_ms=25.0,
            download_mbps=100.0,
            upload_mbps=20.0,
        )
        mock_collect.return_value = record_network_performance(self.device, result)

        call_command(
            "run_performance_monitor",
            device=self.device.name,
            target="1.1.1.1",
            interval=1,
            once=True,
            verbosity=0,
        )

        mock_collect.assert_called_once_with(
            device=self.device,
            target="1.1.1.1",
            include_speedtest=True,
        )


class SyslogRecordingTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name="R1-syslog",
            ip_address="192.168.10.101",
            device_type=Device.DeviceType.ROUTER,
            vlan_id=10,
        )

    def test_known_sender_is_matched_and_stored(self):
        event = record_syslog_event(
            "192.168.10.101",
            "<189>%LINEPROTO-5-UPDOWN: Interface Loopback99 changed state to up",
        )

        self.assertEqual(event.device, self.device)
        self.assertEqual(event.protocol, NetworkEvent.Protocol.SYSLOG)
        self.assertEqual(event.severity, "notice")
        self.assertIn("Loopback99", event.message)

    def test_unknown_sender_is_stored_without_device(self):
        event = record_syslog_event(
            "192.168.10.250",
            "Message without a priority value",
        )

        self.assertIsNone(event.device)
        self.assertEqual(event.source_ip, "192.168.10.250")
        self.assertEqual(event.severity, "")

    def test_three_failed_logins_from_one_source_raise_warning(self):
        now = timezone.now()
        for attempt in range(3):
            record_syslog_event(
                str(self.device.ip_address),
                "<188>%SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: admin] "
                "[Source: 192.168.10.50] [localport: 22] "
                "[Reason: Login Authentication Failed]",
                received_at=now + timedelta(seconds=attempt * 10),
            )

        alert = Alert.objects.get(message__startswith="[BRUTE_FORCE:192.168.10.50]")
        self.assertEqual(alert.severity, Alert.Severity.WARNING)
        self.assertIn("3 failed login attempts", alert.message)

    def test_five_failed_logins_escalate_one_alert_to_critical(self):
        now = timezone.now()
        for attempt in range(5):
            record_syslog_event(
                str(self.device.ip_address),
                "%SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: admin] "
                "[Source: 192.168.10.51] [Reason: Login Authentication Failed]",
                received_at=now + timedelta(seconds=attempt * 5),
            )

        alerts = Alert.objects.filter(message__startswith="[BRUTE_FORCE:192.168.10.51]")
        self.assertEqual(alerts.count(), 1)
        self.assertEqual(alerts.get().severity, Alert.Severity.CRITICAL)
        self.assertIn("5 failed login attempts", alerts.get().message)

    def test_failed_logins_from_different_sources_are_not_combined(self):
        now = timezone.now()
        for attempt, source in enumerate(
            ("192.168.10.60", "192.168.10.61", "192.168.10.60")
        ):
            record_syslog_event(
                str(self.device.ip_address),
                f"%SEC_LOGIN-4-LOGIN_FAILED: Login failed [Source: {source}]",
                received_at=now + timedelta(seconds=attempt),
            )

        self.assertFalse(
            Alert.objects.filter(message__startswith="[BRUTE_FORCE:").exists()
        )


class DashboardTests(TestCase):
    def setUp(self):
        call_command("setup_rbac", verbosity=0)
        self.user = get_user_model().objects.create_user(
            username="monitoring-user",
            password="test-password",
        )
        self.user.groups.add(Group.objects.get(name=MONITORING_USERS_GROUP))
        self.client.force_login(self.user)

    def test_dashboard_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("monitoring:dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

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

    def test_dashboard_hides_admin_link_from_monitoring_user(self):
        response = self.client.get(reverse("monitoring:dashboard"))

        self.assertNotContains(response, "Administration")

    def test_dashboard_displays_latest_performance_metric(self):
        device = Device.objects.create(
            name="Monitoring PC",
            ip_address="192.168.10.10",
            device_type=Device.DeviceType.WORKSTATION,
            vlan_id=10,
        )
        definition = MetricDefinition.objects.create(
            key="internet_download_mbps",
            display_name="Internet download speed",
            unit="Mbps",
            data_type=MetricDefinition.DataType.FLOAT,
            source_protocol=MetricDefinition.SourceProtocol.SYSTEM,
        )
        MetricRecord.objects.create(
            device=device,
            metric_definition=definition,
            numeric_value=48.09,
            collected_at=timezone.now(),
            collection_successful=True,
        )

        response = self.client.get(reverse("monitoring:dashboard"))

        self.assertContains(response, "48.09")
        self.assertContains(response, "Internet throughput")
        self.assertEqual(
            response.context["performance_metrics"][0]["record"].numeric_value,
            48.09,
        )

    def test_dashboard_hides_stale_snmp_values_when_router_is_down(self):
        router = Device.objects.create(
            name="R1-down",
            ip_address="192.168.10.1",
            device_type=Device.DeviceType.ROUTER,
            vlan_id=10,
            last_status=Device.Status.DOWN,
        )
        definition = MetricDefinition.objects.create(
            key="system_uptime",
            display_name="System uptime",
            unit="minutes",
            data_type=MetricDefinition.DataType.FLOAT,
            source_protocol=MetricDefinition.SourceProtocol.SNMP,
        )
        MetricRecord.objects.create(
            device=router,
            metric_definition=definition,
            numeric_value=108,
            collected_at=timezone.now(),
            collection_successful=True,
        )

        response = self.client.get(reverse("monitoring:dashboard"))

        self.assertIsNone(response.context["latest_uptime"])
        self.assertContains(response, "Router uptime")
        self.assertContains(response, "N/A")


class AuthenticationFlowTests(TestCase):
    def setUp(self):
        call_command("setup_rbac", verbosity=0)
        self.user = get_user_model().objects.create_user(
            username="readonly-user",
            password="safe-test-password",
        )
        self.user.groups.add(Group.objects.get(name=MONITORING_USERS_GROUP))

    def test_login_page_is_available(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Login")

    def test_valid_login_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {"username": "readonly-user", "password": "safe-test-password"},
        )

        self.assertRedirects(response, reverse("monitoring:dashboard"))

    def test_invalid_login_does_not_authenticate_user(self):
        response = self.client.post(
            reverse("login"),
            {"username": "readonly-user", "password": "incorrect-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "username or password was incorrect")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_authenticated_user_without_permission_receives_forbidden(self):
        unauthorized_user = get_user_model().objects.create_user(
            username="no-role-user",
            password="safe-test-password",
        )
        self.client.force_login(unauthorized_user)

        response = self.client.get(reverse("monitoring:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_logout_uses_post_and_returns_to_login(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)


class RbacSetupTests(TestCase):
    def test_setup_rbac_creates_read_only_monitoring_group(self):
        call_command("setup_rbac", verbosity=0)

        group = Group.objects.get(name=MONITORING_USERS_GROUP)
        codenames = set(group.permissions.values_list("codename", flat=True))

        self.assertEqual(len(codenames), 7)
        self.assertTrue(all(name.startswith("view_") for name in codenames))
        self.assertNotIn("change_device", codenames)

    def test_setup_rbac_gives_administrators_limited_write_access(self):
        call_command("setup_rbac", verbosity=0)

        group = Group.objects.get(name=NETWORK_ADMINISTRATORS_GROUP)
        codenames = set(group.permissions.values_list("codename", flat=True))

        self.assertIn("add_device", codenames)
        self.assertIn("change_device", codenames)
        self.assertIn("change_alert", codenames)
        self.assertIn("view_metricrecord", codenames)
        self.assertNotIn("delete_metricrecord", codenames)

    def test_setup_rbac_can_be_run_more_than_once(self):
        call_command("setup_rbac", verbosity=0)
        call_command("setup_rbac", verbosity=0)

        self.assertEqual(
            Group.objects.filter(name=MONITORING_USERS_GROUP).count(),
            1,
        )
        self.assertEqual(
            Group.objects.filter(name=NETWORK_ADMINISTRATORS_GROUP).count(),
            1,
        )
