#basecommand is the base class for custom django management commands
from django.core.management.base import BaseCommand
#device is the django models imported from the monitoring.models
from monitoring.models import Device


# This idempotent inventory represents the initial GNS3 laboratory. Running the
# seed command again updates these records instead of creating duplicates.
LAB_DEVICES = (
    {
        "name": "R1",
        "defaults": {
            "hostname": "R1",
            "ip_address": "192.168.10.1",
            "device_type": Device.DeviceType.ROUTER,
            "vlan_id": 10,
            "description": "GNS3 router and VLAN gateway.",
        },
    },
    {
        "name": "Ubuntu Server",
        "defaults": {
            "hostname": "ubuntu-server",
            "ip_address": "192.168.20.20",
            "device_type": Device.DeviceType.SERVER,
            "vlan_id": 20,
            "description": "GNS3 server used for monitoring tests.",
        },
    },
    {
        "name": "ESW2",
        "defaults": {
            "hostname": "ESW2",
            "ip_address": "192.168.10.2",
            "device_type": Device.DeviceType.SWITCH,
            "vlan_id": 10,
            "description": "GNS3 EtherSwitch management interface.",
        },
    },
)

# command defines a custom django management command.
class Command(BaseCommand):
    """Populate the database with the known baseline GNS3 devices."""
# help is the text shown when python manage.py help is rna
    help = "Create or update the initial GNS3 lab device inventory."

# handle is the method django runs whenever a command is executed and loops through each device defines in lab devices


    def handle(self, *args, **options):
        for item in LAB_DEVICES:
            device, created = Device.objects.update_or_create(
                name=item["name"],
                defaults=item["defaults"],
            )
            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} {device}."))
