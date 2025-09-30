from django.apps import AppConfig


class SystemHealthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.system_health'
    verbose_name = 'System Health Monitoring'