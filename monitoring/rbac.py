"""Central role names and model-permission policy for the monitoring system."""

MONITORING_USERS_GROUP = "Monitoring Users"
NETWORK_ADMINISTRATORS_GROUP = "Network Administrators"


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
)
