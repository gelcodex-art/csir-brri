from django.apps import AppConfig


class AccidentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accidents'
    verbose_name = 'Accident data'

    def ready(self):
        from django.apps import apps
        apps.get_app_config('auth').verbose_name = 'Analyst accounts'
