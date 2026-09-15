"""Central role names and model-permission policy for the monitoring system."""

MONITORING_USERS_GROUP = "Monitoring Users"  # Read-only dashboard users.
NETWORK_ADMINISTRATORS_GROUP = "Network Administrators"  # Users allowed to act.


MONITORING_MODEL_NAMES = (
    "device",
    "networkinterface",
    "metricdefinition",
    "metricrecord",
    "networkevent",
    "availabilitycheck",
    "alert",
)

ADMINISTRATOR_WRITE_PERMISSIONS = (
    "add_device",
    "change_device",
    "change_alert",
    "view_sshcommandlog",  # Lets administrators review the audit history.
    "execute_ssh_command",  # Unlocks the remote command page and service.
)
