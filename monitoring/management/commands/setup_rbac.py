from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError

from monitoring.rbac import (
    ADMINISTRATOR_WRITE_PERMISSIONS,
    MONITORING_MODEL_NAMES,
    MONITORING_USERS_GROUP,
    NETWORK_ADMINISTRATORS_GROUP,
)


class Command(BaseCommand):
    """Create the project's RBAC groups and assign their model permissions."""

    help = "Create or refresh the Monitoring Users and Network Administrators groups."

    def handle(self, *args, **options):
        content_types = ContentType.objects.filter(
            app_label="monitoring",
            model__in=MONITORING_MODEL_NAMES,
        )
        if content_types.count() != len(MONITORING_MODEL_NAMES):
            raise CommandError(
                "Monitoring model permissions are incomplete. Run migrations first."
            )

        view_permissions = Permission.objects.filter(
            content_type__in=content_types,
            codename__startswith="view_",
        )
        administrator_write_permissions = Permission.objects.filter(
            content_type__in=content_types,
            codename__in=ADMINISTRATOR_WRITE_PERMISSIONS,
        )

        monitoring_group, _ = Group.objects.get_or_create(
            name=MONITORING_USERS_GROUP
        )
        administrator_group, _ = Group.objects.get_or_create(
            name=NETWORK_ADMINISTRATORS_GROUP
        )

        # set() makes the command idempotent and removes permissions that no
        # longer belong to the documented access-control policy.
        monitoring_group.permissions.set(view_permissions)
        administrator_group.permissions.set(
            view_permissions | administrator_write_permissions
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"RBAC configured: {MONITORING_USERS_GROUP} "
                f"({monitoring_group.permissions.count()} permissions), "
                f"{NETWORK_ADMINISTRATORS_GROUP} "
                f"({administrator_group.permissions.count()} permissions)."
            )
        )
