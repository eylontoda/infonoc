from django.apps import AppConfig

class IncidentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # [AJUSTE] O nome deve ser o caminho completo de importação Python
    name = 'apps.incidents' 
    verbose_name = 'Gestão de Incidentes'