"""Central role names and model-permission policy for the monitoring system."""

MONITORING_USERS_GROUP = "Monitoring Users"
NETWORK_ADMINISTRATORS_GROUP = "Network Administrators"

# Automatically collected history is read-only for both roles. Administrators
# receive additional write access only to inventory and alert-management data.
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
