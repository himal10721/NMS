from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    # default PK field type for models in this app
    default_auto_field = 'django.db.models.BigAutoField'
    # Django app label used by the project
    name = 'monitoring'
